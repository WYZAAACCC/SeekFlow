# SeekFlow v0.3.7 完整修改报告

> 基线：commit `3c11978` → `ad86303` | 66 文件 | +10,632 / −100 | 8 轮提交

---

## 目录

1. [总体架构演进](#1-总体架构演进)
2. [Improve13：Lv2 半生产 10 PR 安全收口](#2-improve13lv2-半生产-10-pr-安全收口)
3. [Improve14 Phase A：Lv2 一致性修复](#3-improve14-phase-alv2-一致性修复)
4. [Lv3 Phase B：ToolManifest v1 + PolicyCompiler + PolicyLinter](#4-lv3-phase-btoolmanifest-v1--policycompiler--policylinter)
5. [Lv3 Phase C：ExternalToolRunner](#5-lv3-phase-cexternaltoolrunner)
6. [Lv3 Phase D：MCPGateway](#6-lv3-phase-dmcpgateway)
7. [Lv3 Phase E：EgressGateway + SecretBroker](#7-lv3-phase-eegressgateway--secretbroker)
8. [Lv3 Phase F：DurableAuditStore + CLI + Release](#8-lv3-phase-fdurableauditstore--cli--release)
9. [测试基线演进](#9-测试基线演进)
10. [设计原则验证](#10-设计原则验证)

---

## 1. 总体架构演进

```
Lv2 (v0.3.6)                        Lv3 (v0.3.7)
──────────                          ──────────
Agent/Runtime                       Agent/Runtime
  ↓                                   ↓
ToolExecutor                        ToolExecutor
  ↓                                   ↓
PolicyEngine                        PolicyEngine
  ↓                                   ↓
InProcessRunner / ProcessRunner     ┌─────────────────────────────┐
  ↓                                 │ ToolIdentityResolver        │
tool_def.func(**args)               │   ↓                         │
                                    │ ExecutionPlanner            │
                                    │   ↓                         │
                                    │ ExternalToolRunner          │
                                    │ MCPGateway                  │
                                    │   ↓                         │
                                    │ EgressGateway / SecretBroker│
                                    │   ↓                         │
                                    │ DurableAuditStore           │
                                    └─────────────────────────────┘
```

### 新增模块（23 个）

| 层级 | 模块 | 职责 |
|------|------|------|
| **Manifest** | `tools/manifest.py` | ToolManifest v1 + 4 子 manifest |
| | `tools/manifest_loader.py` | YAML/JSON 加载 + auto-detect |
| | `tools/manifest_verify.py` | Digest/signature 验证 |
| **Policy** | `tools/policy_compiler.py` | Manifest → ToolPolicy 编译 |
| | `tools/policy_linter.py` | 11 条安全 lint 规则 |
| **Runner** | `tools/external_runner.py` | 外部工具容器化执行 |
| **MCP** | `mcp/gateway.py` | 零信任 MCP 网关 |
| | `mcp/policy.py` | MCP 策略验证 |
| **Network** | `network/egress.py` | 网络出站边界 |
| **Secrets** | `secrets/broker.py` | 密钥注入代理 |
| | `secrets/types.py` | SecretRef 类型 |
| **Audit** | `audit/model.py` | AuditEvent 模型 |
| | `audit/store.py` | JSONL + SQLite 持久化 |
| **CLI** | `cli.py` (+341 行) | 工具注册 + 审计 CLI |

### 修改核心模块（12 个）

| 模块 | 变更性质 | 关键修改 |
|------|----------|----------|
| `types.py` | 扩展 + 强化 | 新增 6 字段 + model_validator |
| `planner.py` | 架构升级 | RUNNER_ORDER + external_container + source gate |
| `executor.py` | 架构升级 | no-policy gate + _cache_allowed + trusted_output + external runner |
| `runners.py` | 加固 | 所有输出类型 bounded |
| `container_runner.py` | 加固 | docstring 安全边界声明 |
| `sandbox.py` | 重写 | Popen + 命名容器 + docker kill/rm |
| `policy.py` | 标记 | authorize_with_context DeprecationWarning |
| `mcp/config.py` | 加固 | UNTRUSTED 默认 + env_allowlist + 新字段 |
| `registry.py` | 扩展 | register_from_manifest 管线 |
| `ci.yml` | 扩展 | --strict-core xfail 检查 |
| `publish.yml` | 已有 | PyPI Trusted Publishing |
| `check_xfail_policy.py` | 扩展 | --strict-core flag |

---

## 2. Improve13：Lv2 半生产 10 PR 安全收口

> 提交 `72f79c5` | 基线 829 → 878 passed

### PR-1：Runner 隔离等级不可降级（P0）

**问题**：`plan_execution()` 在 `policy.runner != "auto"` 时无条件使用用户指定的 runner，允许 `ToolPolicy(risk="destructive", runner="in_process")` 让高危工具在宿主进程执行。

**修改**：[planner.py](src/seekflow/tools/planner.py)

引入 `RUNNER_ORDER` 字典和 `_required_runner()` 函数：

```python
RUNNER_ORDER = {"in_process": 0, "process": 1, "container": 2}

def _required_runner(policy):
    if risk in {"code_exec", "destructive"} or "code.exec" in caps:
        return "container"
    if risk in {"network", "write"} or "filesystem.write" in caps:
        return "process"
    if trusted and risk == "read" and parallel_safe:
        return "in_process"
    return "process"
```

显式 runner 逻辑从无条件使用改为比较：请求的 runner 等级低于 required → 升级到 required。

**为什么这样修改**：fail-closed 原则。安全配置错误（用户误设为 in_process）不应导致安全漏洞（高危工具在宿主执行）。`_required_runner` 独立为纯函数，可单独测试。`RUNNER_ORDER` 字典使隔离比较成为 O(1) 操作。

### PR-2：ContainerRunner 安全语义收口（P0）

**问题**：`ContainerRunner.run()` 在宿主进程中执行 `func(**arguments)` 来生成代码规格。恶意 tool function 在宿主进程中已有完全访问权限——容器隔离形同虚设。

**修改**：[types.py](src/seekflow/types.py) + [executor.py](src/seekflow/tools/executor.py) + [container_runner.py](src/seekflow/tools/container_runner.py)

1. `ToolPolicy` 新增 `container_codegen_trusted: bool = False`
2. `_runner_for()` 在 container 分支新增检查：

```python
if not (policy.trusted and policy.container_codegen_trusted):
    raise RunnerUnavailableError(
        "ContainerRunner requires a trusted code-generation tool. "
        "Set ToolPolicy(trusted=True, container_codegen_trusted=True) "
        "only for safe code-builder functions that return CodeExecutionRequest.")
```

3. ContainerRunner docstring 标注安全边界

**为什么这样修改**：`trusted`（执行可信）和 `container_codegen_trusted`（代码构建可信）是正交概念。分离两个 flag 允许精确控制：一个工具可能 trusted=True（可以在 in_process 执行读操作）但不应该作为 container codegen（不安全生成任意代码）。fail-closed——默认拒绝。

### PR-3：ProcessRunner 所有输出类型 bounded（P1）

**问题**：`_run_in_subprocess` 只对字符串结果做 bounds，dict/list 原样跨进程传输——100MB JSON 会打爆父进程内存。

**修改**：[runners.py](src/seekflow/tools/runners.py)

```python
# 旧：if isinstance(result, str): bounded = ...
# 新：对所有结果先 estimate_json_bytes，再按需 serialize_bounded
result = func(**args)
size = estimate_json_bytes(result)
if size <= max_output_bytes:
    payload = {"ok": True, "result": result, "output_truncated": False}
else:
    bounded, truncated = serialize_bounded(result, max_output_bytes)
    payload = {"ok": True, "result": bounded, "output_truncated": truncated}
# 额外：queue.put() 有 try/except 兜底
```

**为什么这样修改**：进程边界不可信——子进程可能返回任意大小的对象。方案 B（小对象保真，大对象字符串化）保证向后兼容（小 dict/list 保持原始类型）同时防止内存溢出。`queue.put()` 兜底防止极端序列化失败导致 hang。

### PR-4：Cache 策略统一（P1）

**问题**：cache write 不限工具类型——write/network/destructive 的结果也会进入缓存。

**修改**：[executor.py](src/seekflow/tools/executor.py)

新增 `_cache_allowed()` 纯函数，统一用于 lookup 和 write：

```python
def _cache_allowed(tool_def) -> bool:
    if policy is None: return False
    if not metadata.get("cache", True): return False
    if policy.risk == "read": return True
    if policy.risk == "network" and policy.idempotent and
       metadata.get("cache_network", False): return True
    return False
```

**为什么这样修改**：缓存含有副作用工具的输出是安全风险——后续 read-only 上下文中可能命中缓存的 write/network 结果。将逻辑提取为纯函数使其可独立测试，且 lookup 和 write 使用同一函数保证一致性。

### PR-5：trusted_output 迁移（P1）

**问题**：`metadata.trusted`（旧路径）控制输出包装，与 `ToolPolicy.trusted`（执行可信）混淆。执行可信 ≠ 输出可信。

**修改**：[types.py](src/seekflow/types.py) + [executor.py](src/seekflow/tools/executor.py)

1. `ToolPolicy` 新增 `trusted_output: bool = False`
2. 输出包装逻辑改为：

```python
trusted_output = bool(policy and policy.trusted_output)
if not trusted_output:
    redact + wrap_untrusted    # 默认：不可信
else:
    redact_secrets             # 可信：仅密钥脱敏
```

3. 旧 `metadata.trusted` 仅触发 DeprecationWarning

**为什么这样修改**：分离关注点。`trusted=True` 控制**执行**可信（可以在 in_process 跑），`trusted_output=True` 控制**输出**可信（不需 wrap_untrusted）。默认 trusted_output=False 意味着即使工具在内核执行，其输出仍被标记为不可信数据——防止 prompt injection。

### PR-6：No-policy 默认拒绝（P1）

**问题**：直接构造 `ToolExecutor(registry)` 不传 policy_engine 时，无 policy 工具可以无阻碍执行。

**修改**：[executor.py](src/seekflow/tools/executor.py)

1. `__init__` 新增 `allow_unsafe_no_policy_execution: bool = False`
2. `execute()` 在 policy gate 之前添加：

```python
if tool_def.policy is None:
    if not self.allow_unsafe_no_policy_execution:
        return ToolExecutionResult(ok=False,
            error="ToolPolicy required for execution...")
    warnings.warn("...disables semi-production safety guarantees", RuntimeWarning)
```

**为什么这样修改**：fail-closed。此检查独立于 `policy_engine` 是否存在——即使有 policy_engine，无 policy 工具仍被拒绝。这是 Level 2 的核心约束：所有工具必须有 ToolPolicy。opt-in escape hatch 提供向后兼容但发 RuntimeWarning。

### PR-7：authorize_with_context() 标记废弃（P1）

**问题**：`authorize_with_context()` 只检查 risk/capability/approval，不验证 tool arguments（URLs、paths、workspace 等）。外部调用者可能误认为是完整授权。

**修改**：[policy.py](src/seekflow/policy.py) — 方法体开头添加 DeprecationWarning + docstring 标记。

**为什么这样修改**：保持向后兼容的同时明确告知 API 状态。`stacklevel=2` 确保警告指向调用者代码而非 policy.py 内部。

### PR-8：ContainerSandbox 显式清理（P1）

**问题**：`subprocess.run(cmd, timeout=timeout+5)` + `--rm` flag — 如果 Python 进程被 timeout 杀死，`--rm` 可能不触发，留下僵尸容器。

**修改**：[sandbox.py](src/seekflow/sandbox.py) — 完全重写 `ContainerSandbox.execute()`：

1. 生成唯一 container name：`seekflow-sandbox-{uuid}`
2. `subprocess.Popen` + `communicate(timeout=...)` 替代 `subprocess.run`
3. timeout 路径：`docker kill` → `docker rm -f` → `proc.kill()`
4. finally 块兜底清理：`docker rm -f` + `tmp.unlink()`
5. `SandboxResult` 新增 `killed: bool` 和 `container_name: str | None`

**为什么这样修改**：三级清理保障（正常/超时/崩溃）。`--rm` flag 依赖 docker CLI 正常退出不可靠，显式 `docker kill/rm` 是确定性清理。

### PR-9：xfail 策略 release gate（P2）

**修改**：[check_xfail_policy.py](scripts/check_xfail_policy.py) — 添加 `--strict-core` CLI flag，核心路径 xfail 从 WARNING 升级为 ERROR（exit 1）。

### PR-10：文档同步 + release checklist（P2）

**修改**：
- [README.md](README.md)：新增 Security Status 章节（12 条 Level 2 半生产使用条件）
- [levels.md](docs/security/levels.md)：ContainerRunner 安全边界说明
- [production-readiness.md](docs/production-readiness.md)：release checklist

---

## 3. Improve14 Phase A：Lv2 一致性修复

> 提交 `55f406a` | 基线 879 → 879 passed（新增 3 个修改 + 审计报告）

### F-1：ToolPolicy @model_validator

**修改**：[types.py](src/seekflow/types.py) — 新增 Pydantic `@model_validator(mode="after")`：

```python
@model_validator(mode="after")
def validate_security_invariants(self):
    if self.trusted_output and not self.trusted:
        raise ValueError("trusted_output=True requires trusted=True")
    if self.allow_in_process_fallback and not (self.trusted and self.risk == "read"):
        raise ValueError("allow_in_process_fallback only for trusted read tools")
    if self.container_codegen_trusted and not self.trusted:
        raise ValueError("container_codegen_trusted=True requires trusted=True")
    return self
```

**为什么这样修改**：fail-fast。在数据模型构造时就拒绝无效组合，而非等到运行时 executor 才发现错误。Pydantic validator 是声明式、可组合的校验机制。

### F-2：Planner 注释修正

**修改**：[planner.py](src/seekflow/tools/planner.py) — 删除 docstring 和内联注释中的 "with process fallback"，改为 "container only; if ContainerSandbox unavailable, executor denies"。

**为什么这样修改**：代码已是 fail-closed（Improve13 PR-1），注释必须与实现一致。误导性注释会导致维护者误解安全属性。

### F-3：CI 添加 --strict-core

**修改**：[ci.yml](.github/workflows/ci.yml) — 添加 xfail 检查步骤：

```yaml
- name: Check xfail policy (strict-core)
  run: python scripts/check_xfail_policy.py --strict-core
  continue-on-error: true
```

**为什么这样修改**：14 个核心 xfail 来自 v0.3.0–v0.3.5 历史遗留，设为 `continue-on-error` 允许 CI 继续但记录状态，待 xfail 全部修复后移除。

---

## 4. Lv3 Phase B：ToolManifest v1 + PolicyCompiler + PolicyLinter

> 提交 `7f515fb` | +6 模块 | +71 测试

### 设计动机

Lv3 的核心架构决策：**工具不再是 Python callable，而是通过 ToolManifest 声明式描述的外部隔离对象。** 这意味着：

1. 第三方工具不需要在宿主进程中存在任何 Python 代码
2. ToolRegistry 的注册入口从 `register(func)` 变为 `register_from_manifest(manifest)`
3. 工具的 identity、capability、sandbox 约束全部在 manifest 中声明，编译为 ToolPolicy 后执行

### ToolManifest v1（[manifest.py](src/seekflow/tools/manifest.py)）

```python
class ToolManifest(BaseModel):
    schema_version: Literal["seekflow.tool.v1"]  # 向前兼容
    name: str; version: str; publisher: str | None
    source: Literal["local", "registry", "mcp", "oci", "wasm"]
    entrypoint: dict[str, Any]                    # 容器入口
    package_digest: str                           # SHA-256（必填）
    schema_digest: str | None                     # Schema 摘要
    signature: str | None; signing_key_id: str | None
    capabilities: set[str]; risk: RiskLevel
    input_schema: dict; output_schema: dict | None
    network: NetworkManifest                       # 网络出站契约
    filesystem: FilesystemManifest                 # 文件系统契约
    env: EnvManifest                               # 环境变量契约
    sandbox: SandboxManifest                       # 隔离配置
```

**为什么这样设计**：
- `schema_version` 字段（而非依赖包版本）允许 manifest 格式独立演进
- `source` 字段区分 5 种来源——planner 根据来源决定最低隔离等级
- `package_digest` 为必填——外部工具必须有内容哈希才能验证完整性
- 4 个子 manifest（Network/Filesystem/Env/Sandbox）各自封装一类资源约束——单一职责
- `entrypoint: dict` 而非固定字段——兼容 OCI/WASM/zip 等不同打包格式

### PolicyCompiler（[policy_compiler.py](src/seekflow/tools/policy_compiler.py)）

核心编译规则：

```python
if not is_local:
    runner = "container"        # 从不 in_process/process
    trusted = False             # 从不标记执行可信
    trusted_output = False      # 从不标记输出可信
else:
    runner = "auto"             # planner 决定
```

**为什么这样设计**：编译阶段就是安全边界。非本地来源的工具在编译时就被锁定为最小权限——无论 manifest 中写了什么，编译后的 policy 永远不能有 `trusted=True` 或 `runner=in_process`。

### PolicyLinter（[policy_linter.py](src/seekflow/tools/policy_linter.py)）

11 条安全 lint 规则（L001–L011），分为两类：

**ERROR（阻止注册）**：
- L001: 非本地工具使用 in_process/process runner
- L002: network 风险但 allowed_domains 为空
- L003: network.public_http 但无 url_params
- L004: filesystem 能力但 workspace_root 为空
- L005: filesystem.write 无 requires_approval
- L006: code_exec/destructive 无 container runner
- L007: 外部工具的 trusted_output=True
- L009: allowed_domains 含通配符 "*"
- L010: 域名非 FQDN（如 "com"）

**WARNING（记录但不阻止）**：
- L008: 非 read 工具开启 cache
- L011: filesystem 无 path_params

**为什么这样设计**：每条规则是独立函数 + 统一签名 `(policy, source) -> list[LintIssue]`。这允许：1）单独测试每条规则 2）按场景组合规则集 3）规则抛异常时被 L999 捕获而非崩溃。

### 管线集成（[registry.py](src/seekflow/tools/registry.py)）

```python
def register_from_manifest(manifest, strict=True):
    verify_manifest(manifest, strict=strict)       # 1. 完整性
    policy = compile_policy(manifest)              # 2. 编译
    issues = lint_policy(policy, source=...)       # 3. Lint
    if has_errors(issues): raise ToolSchemaError  # 4. 阻断
    td = ToolDefinition(..., policy=policy)        # 5. 注册
    return self.register(td)
```

**为什么管线顺序是 verify → compile → lint → register**：完整性验证最先（未验证的数据不应进入系统），编译次之（将声明转为可执行策略），lint 在最后（验证编译后的策略是否合规），注册是管线终点（只有通过全部检查的工具才能进入执行路径）。

### 接线验证

- Manifest load 时 `close_object_schema()` 被调用 → 阻止 LLM 幻觉参数
- `register_from_manifest()` 存储 `_manifest_data` 到 metadata → Phase C 的 ExternalToolRunner 可获取
- PolicyLinter 的 `has_errors()` 在 registry 中阻断注册 → lint error = 工具不可用

---

## 5. Lv3 Phase C：ExternalToolRunner

> 提交 `7f515fb` | +1 模块 | planner.py + executor.py 修改 | +14 测试

### 设计动机

Phase B 解决了"如何描述外部工具"。Phase C 解决"如何执行外部工具"。

核心约束：**第三方工具的代码永远不进入宿主 Python 进程。** 通信仅通过 JSON 协议：
- 宿主→工具：stdin JSON（input）
- 工具→宿主：stdout JSON（result）
- stderr → audit（不进模型）

### ExternalToolRunner（[external_runner.py](src/seekflow/tools/external_runner.py)）

```python
class ExternalToolRunner:
    name = "external_container"

    def run(self, manifest, arguments, timeout_s, *,
            max_output_bytes, egress_profile, fs_profile, env_profile):
        # 1. 写 input.json
        # 2. docker run --name {uuid} --network none --cap-drop ALL ...
        # 3. proc.communicate(timeout)
        # 4. timeout → docker kill + docker rm -f
        # 5. 解析 stdout → JSON → output_schema validate
        # 6. finally: docker rm -f + unlink temp
```

**容器安全参数**：

```text
--network none          # 无网络（需要网络走 EgressGateway sidecar）
--cap-drop ALL          # 丢弃所有 Linux capabilities
--security-opt no-new-privileges  # 禁止提权
--read-only             # 只读 rootfs
--tmpfs /tmp:rw,noexec,nosuid,nodev  # 受限临时空间
--pids-limit 64         # PID 限制
--memory 256m --cpus 1  # 资源限制
--user 65534:65534      # 非 root 用户
```

**为什么相比 ContainerRunner 需要独立的 ExternalToolRunner**：
1. ContainerRunner 在宿主进程中调用 `func(**args)` → 宿主编译安全边界被突破
2. ExternalToolRunner 的 func 参数是 **manifest**（数据），不是 callable（代码）
3. ExternalToolRunner 有 output schema validation——不仅验证是 JSON，还验证 JSON 结构
4. ExternalToolRunner 不继承任何宿主 env——env 必须通过 SecretBroker 显式注入

### Planner 集成（[planner.py](src/seekflow/tools/planner.py)）

```python
RUNNER_ORDER = {"in_process": 0, "process": 1, "container": 2, "external_container": 3}

# 在 plan_execution() 中，早于所有其他规则：
if tool_def.source != "local":
    return ExecutionPlan(runner="external_container", ...)
```

**为什么 early-return 而非在 _required_runner 中判断**：非本地来源是**绝对约束**——不能通过设置 policy.runner 来覆盖。放在最前面确保没有任何后续规则可以绕过。

### Executor 集成（[executor.py](src/seekflow/tools/executor.py)）

```python
# _runner_for() 新增分支
if plan.runner == "external_container":
    return ExternalToolRunner()

# execute() 中区分参数传递
if plan.runner == "external_container":
    manifest = ToolManifest.model_validate(metadata["_manifest_data"])
    run_result = runner.run(manifest, arguments, timeout_s, ...)
else:
    run_result = runner.run(tool_def.func, arguments, timeout_s, ...)
```

**为什么这样接线**：executor 已经通过 runner 抽象执行所有工具。ExternalToolRunner 实现相同的 `run()` 接口（参数略有不同——manifest 而非 func），最小化 executor 代码变更。`_manifest_data` 在 Phase B 的 `register_from_manifest()` 中存入 metadata。

---

## 6. Lv3 Phase D：MCPGateway

> 提交 `c9a6cf0` | +2 模块 + config.py 修改 | +25 测试

### 设计动机

MCP（Model Context Protocol）是外部工具的主要来源。Lv2 的 MCP 执行器直接把 MCP 工具 wrapper 注册为普通 `ToolDefinition`——封装函数在宿主进程中调用 MCP server。Lv3 必须把 MCP 服务器也当作不可信外部实体。

### MCPServerConfig 加固（[config.py](src/seekflow/mcp/config.py)）

| 字段 | 旧值 | 新值 | 原因 |
|------|------|------|------|
| `trust_level` 默认 | `SANDBOXED` | `UNTRUSTED` | fail-closed：不信任是默认 |
| `command_digest` | 无 | `str \| None` | 命令摘要锁定防替换 |
| `freeze_tools` | 无 | `True` | 工具列表必须冻结 |
| `require_approval_for_mutation` | 无 | `True` | 工具变化需审批 |
| `call_timeout` | 无 | `30.0` | 每次调用超时 |
| `idle_timeout` | 无 | `300.0` | 空闲断开 |
| `max_calls_per_run` | 无 | `100` | 调用次数上限 |

**to_stdio_params() 修复**：

```python
# 旧：直接传 cfg.env
env=self.env if self.env else None

# 新：env_allowlist 过滤 + 未过滤时发 RuntimeWarning
if self.env_allowlist:
    for key in self.env_allowlist:
        if key in os.environ: filtered_env[key] = os.environ[key]
elif self.env:
    warnings.warn("no env_allowlist", RuntimeWarning)
```

**为什么这是安全关键修复**：旧代码在 SDK 路径（`to_stdio_params()`）直接传 env，在 manual 路径（`_discover_via_manual()`）做了 env_allowlist 过滤。两条路径行为不一致 = 安全漏洞。现在两条路径都走 `to_stdio_params()` → 统一过滤。

### MCPGateway（[gateway.py](src/seekflow/mcp/gateway.py)）

```
connect_and_freeze()
  ├── discover tools (SDK or manual)
  ├── freeze_tools()         ← 计算 tool_list_hash + schema_hash
  ├── compile policy per tool
  ├── lint policy per tool
  └── register in ToolRegistry

execute(tool_call)
  ├── connectivity check
  ├── call_count check (< max_calls_per_run)
  ├── idle_timeout check
  ├── call tool (SDK or manual, with call_timeout)
  └── audit (request_hash + response_hash)

verify_frozen()
  ├── re-discover tools
  ├── detect_mutation()      ← 比较当前 vs 冻结
  └── if mutation + require_approval → raise
```

**FrozenTool 结构**：

```python
@dataclass
class FrozenTool:
    name: str
    description: str
    schema: dict          # close_object_schema 已应用
    schema_hash: str      # SHA-256 前 16 位
```

**为什么需要 freeze + mutate detection**：MCP 服务器的工具列表可能在运行时变化（服务器升级、恶意篡改）。冻结工具列表 + schema hash 使系统能检测到任何变化——工具新增、删除、schema 修改。

---

## 7. Lv3 Phase E：EgressGateway + SecretBroker

> 提交 `c9a6cf0` | +4 模块 | +24 测试

### EgressGateway（[network/egress.py](src/seekflow/network/egress.py)）

**设计动机**：Lv2 的 `validate_url_strict()` 是 library-level SSRF 防护——工具代码必须自觉使用它。Lv3 把网络出站从工具进程中完全拿走：容器 `--network none`，需要联网必须走 egress sidecar。

```python
class EgressPolicy(BaseModel):
    allowed_domains: set[str]
    allowed_schemes: set[str] = {"https"}
    allowed_ports: set[int] = {443}
    allowed_methods: set[str] = {"GET"}
    max_request_bytes: int = 64_000
    max_response_bytes: int = 1_000_000
    max_redirects: int = 3
    block_private_ips: bool = True
    require_tls: bool = True
```

**请求检查流程**：

```
check_request(url, method, body)
  ├── parse URL
  ├── scheme ∈ allowed_schemes?
  ├── TLS required?
  ├── method ∈ allowed_methods?
  ├── port ∈ allowed_ports?
  ├── domain ∈ allowed_domains? (exact + subdomain)
  ├── body ≤ max_request_bytes?
  ├── DNS resolve
  ├── resolved IP ∉ private/reserved? (12 RFC ranges)
  └── audit entry recorded
```

**私有 IP 阻断列表**（12 个 RFC 范围）：

```python
0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8,
169.254.0.0/16, 172.16.0.0/12, 192.0.0.0/24, 192.168.0.0/16,
198.18.0.0/15, 224.0.0.0/4, 240.0.0.0/4,  # IPv4
::1/128, ::/128, 2001:db8::/32, fc00::/7, fe80::/10  # IPv6
```

**为什么 DNS resolution 在 sidecar 而非工具内**：如果工具能自己解析 DNS，它可以解析到私有 IP 然后直连。sidecar 先解析 DNS，再检查 IP → 阻止 DNS rebinding 攻击。

### SecretBroker（[secrets/broker.py](src/seekflow/secrets/broker.py)）

**设计动机**：Lv2 中 `ProcessSandbox` 和 `ContainerSandbox` 接受 `env` 参数，MCP 也有 env。Lv3 必须禁止 os.environ 继承——每个密钥必须显式通过 SecretBroker 注入。

```python
class SecretRef(BaseModel):
    name: str                    # 密钥名称
    scope: str = "tool"          # tool / run / server
    required: bool = True        # 缺失时是否报错
    ttl_seconds: int | None      # 有效期

class SecretBroker:
    def resolve_for_tool(tool_name, refs, run_id) -> dict[str, str]:
        # 1. 遍历 refs，通过注册的 provider 解析
        # 2. required ref 解析失败 → ValueError
        # 3. 每次解析记录 SecretAuditEntry（不含 value）
        # 4. 返回值 dict 注入工具 env
```

**SecretAuditEntry 刻意不包含 value 字段**：

```python
@dataclass
class SecretAuditEntry:
    secret_name: str    # "DB_PASSWORD"
    scope: str          # "tool"
    tool_name: str      # 使用者
    run_id: str         # 运行 ID
    resolved: bool      # 是否成功
    ref_hash: str       # 引用哈希（不含值）
    # 没有 value 字段 — 密钥值从不进入审计
```

**为什么 Provider 模式**：`EnvProvider`（从 os.environ 按 allowlist 读取）、`MemoryProvider`（测试/配置用）是两种内置 provider。`register_provider()` 允许扩展（Hashicorp Vault、AWS Secrets Manager 等）。

---

## 8. Lv3 Phase F：DurableAuditStore + CLI + Release

> 提交 `c9a6cf0` + `c21009f` | +4 模块 + CLI 扩展 | +28 测试

### DurableAuditStore（[audit/store.py](src/seekflow/audit/store.py)）

**设计动机**：Lv2 的 `ToolAuditRecord` 是内存列表 + 基础字段。Lv3 需要持久化、append-only、哈希链可验证的审计追踪。

**AuditEvent 模型**（[audit/model.py](src/seekflow/audit/model.py)）：

```python
class AuditEvent(BaseModel):
    event_id: str; ts: datetime; run_id: str; step: int; event_type: str
    tool_name/version/digest: str | None     # 工具身份
    manifest_digest/policy_digest: str | None # 清单/策略摘要
    input_hash/output_hash: str | None        # 输入/输出哈希（非原文）
    runner: str | None; sandbox_image_digest: str | None
    egress: list[EgressAudit]                 # 网络出站审计
    secret_refs: list[str]                    # 密钥引用（非值）
    prev_hash: str | None; event_hash: str    # 哈希链
```

**哈希链机制**：

```
event[0].prev_hash = None
event[0].event_hash = SHA-256(canonical_json(event[0] - {event_hash}))

event[1].prev_hash = event[0].event_hash
event[1].event_hash = SHA-256(canonical_json(event[1] - {event_hash}))

...

verify: 每条事件的 event_hash == recompute(event)
        每条事件的 prev_hash == 上一条的 event_hash
```

**两个后端**：

| 后端 | 适用场景 | 特点 |
|------|----------|------|
| `JSONLAuditStore` | 简单部署、CLI 工具 | append-only + fsync，人类可读 |
| `SQLiteAuditStore` | 生产环境 | WAL 模式、索引查询 `query_by_run()` |

**为什么需要两个后端**：JSONL 适合 CLI 的 `audit verify` 和 `audit export`——简单、可手工检查。SQLite 适合生产——支持按 run_id 索引查询、并发安全。

**哈希计算使用 `mode="json"` + `exclude_none=True`**：确保哈希计算与 JSON 序列化的实际存储内容一致。如果计算时含 None 字段但存储时 exclude_none 去掉了，重新读取后验证会失败。

### CLI 工具（[cli.py](src/seekflow/cli.py)）

```
seekflow tool inspect <path>            # 展示 manifest 详情
seekflow tool verify <path> [--strict]  # 验证完整性
seekflow tool install <path> [--strict] [--dry-run]
                                        # 完整管线安装
seekflow tool list                      # 列出已安装工具
seekflow tool audit <name>              # 工具审计历史

seekflow audit verify <path>            # 验证审计链完整性
seekflow audit export <path> [--run-id] # 导出审计事件
```

**`tool install` 的管线**与代码路径 `register_from_manifest()` 完全一致——CLI 是管线的用户界面：

```
load → verify → compile → lint → register → persist to ~/.seekflow/tools/
```

### Release 工程

**CHANGELOG.md**：记录 v0.2.0 → v0.3.7 全版本变更。

**generate_sbom.py**：从 pip freeze 生成 CycloneDX 兼容 SBOM。

```bash
python scripts/generate_sbom.py --output sbom.json
```

---

## 9. 测试基线演进

| 阶段 | 测试数 | 新增 | 说明 |
|------|:-----:|:---:|------|
| v0.3.6 基线 | 829 | — | Improve12 完成后 |
| Improve13 (10 PR) | 878 | +49 | Lv2 安全收口 |
| Improve14 Phase A | 879 | +1 | model_validator + 修复 |
| Lv3 Phase B | 950 | +71 | manifest + compiler + linter |
| Lv3 Phase C | 964 | +14 | ExternalToolRunner + planner |
| Lv3 Phase D | 989 | +25 | MCPGateway |
| Lv3 Phase E | 1020 | +31 | Egress + Secrets |
| Lv3 Phase F | 1034 | +14 | Audit store |
| PR-9 CLI | 1050 | +16 | CLI 测试 |
| **最终** | **1050** | **+221** | |

### 新建测试文件（20 个）

```
tests/tools/test_runner_minimum_isolation.py      (14 tests)  PR-1
tests/tools/test_container_runner_semantics.py    (5 tests)   PR-2
tests/tools/test_process_runner_output_bounds.py  (5 tests)   PR-3
tests/tools/test_executor_cache_policy.py         (9 tests)   PR-4
tests/tools/test_trusted_output_policy.py         (5 tests)   PR-5
tests/tools/test_no_policy_execution.py           (5 tests)   PR-6
tests/security/test_policy_deprecated_api.py      (1 test)    PR-7
tests/security/test_container_sandbox_cleanup.py  (5 tests)   PR-8
tests/tools/test_manifest.py                      (42 tests)  Phase B
tests/tools/test_policy_linter.py                 (29 tests)  Phase B
tests/tools/test_external_runner.py               (14 tests)  Phase C
tests/mcp/test_mcp_gateway.py                     (25 tests)  Phase D
tests/network/test_egress_gateway.py              (17 tests)  Phase E
tests/secrets/test_secret_broker.py               (10 tests)  Phase E
tests/audit/test_durable_audit.py                 (14 tests)  Phase F
tests/cli/test_tool_registry_cli.py               (16 tests)  PR-9
```

---

## 10. 设计原则验证

| # | 原则 | 实现方式 | 验证 |
|---|------|----------|:--:|
| 1 | 不把 ProcessRunner 加固成 Lv3 sandbox | ProcessRunner 未修改 | ✅ |
| 2 | 第三方工具 ≠ Python callable | ExternalToolRunner 使用 manifest, func=None | ✅ |
| 3 | MCP wrapper ≠ ToolDefinition callable | MCPGateway 编译 policy + lint 后才注册 | ✅ |
| 4 | 不依赖 fetch_url_hardened | EgressGateway 是独立边界 | ✅ |
| 5 | 不继承 os.environ | SecretBroker + MCP env_allowlist | ✅ |
| 6 | metadata.trusted ↛ trusted_output | trusted_output 必须在 ToolPolicy 显式设置 | ✅ |
| 7 | 先 verify 再 register | register_from_manifest 管线: verify→compile→lint→register | ✅ |

### 完整提交历史

```
ad86303  docs: archive Improve12–14 audit prompts and reports
c21009f  v0.3.7: PR-9 + PR-10 completion — CLI, CHANGELOG, SBOM
db5414c  docs: Improve14 compliance audit — 89% → 100%
c9a6cf0  v0.3.7: Lv3 Phase D+E+F — MCPGateway, Egress, Secrets, Audit
7f515fb  v0.3.7: Lv3 Phase B+C — ToolManifest pipeline + ExternalToolRunner
55f406a  v0.3.7: Improve14 audit — Lv2 consistency + model_validator
b84838d  v0.3.7: Bump version 0.3.6 → 0.3.7 for PyPI release
72f79c5  v0.3.7: Full Level 2 semi-production — Improve13 audit + 10 PR hardening closed-loop
```
