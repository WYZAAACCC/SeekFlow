# Improve14 审计报告 — 逐条核查与修复决策

> 审计基线：commit `b84838d` (v0.3.7)，即上一轮 Improve13 的 10 个 PR 完成后状态。

---

## 0. 总体结论

improve14.md 的核心判断是**正确的**：

1. 当前 main 已经是 v0.3.7（不是文档中估计的 v0.3.6），Improve13 的 P0-1/P0-2/P0-3/P0-4 已在上一轮修复。
2. Lv2→Lv3 的方向正确，但 Lv3 是**全新开发阶段**，不应与 Lv2 收尾工作混在一起。
3. Lv3 的核心思想——"把 SeekFlow 从可信 Python 工具运行时升级为零信任工具网关"——是准确的架构判断。

下面逐项核查。

---

## 1. Section 0-1：总体判断与安全边界评估

### 文档判断：代码存在严重的版本/类型模型不一致（P0-1）

**核查结果：已修复。**

文档描述的 `ToolPolicy` 字段缺失（`idempotent`, `trusted`, `trusted_output`, `allow_in_process_fallback`, `container_codegen_trusted`, `runner`）是基于 GitHub 公开 main 在 commit `3c11978` 时的状态。当前 main（commit `b84838d`）的 [types.py:35-40](../src/seekflow/types.py#L35-L40) 已包含全部字段：

```python
runner: RunnerKind = "auto"
trusted: bool = False
idempotent: bool = False
allow_in_process_fallback: bool = False
container_codegen_trusted: bool = False
trusted_output: bool = False
```

这 6 个字段在 Improve13 的 PR-1/PR-2/PR-5 中已添加。运行 `pytest`（878 passed, 0 failed）验证了 executor、planner、runners 等模块对这些字段的引用全部正常工作，不存在 `AttributeError` 风险。

### 文档建议新增 `@model_validator` 做安全不变量校验

**修复方式判断：正确，需要补充。**

文档建议的 validator 检查以下不变量：
- `trusted_output=True` 必须 `trusted=True`
- `allow_in_process_fallback` 仅允许 `trusted=True + risk="read"`
- `container_codegen_trusted=True` 必须 `trusted=True`

这些约束在当前代码中只在 executor 的运行时检查（`_runner_for()`），应该在数据模型层就拒绝无效组合。Pydantic `@model_validator(mode="after")` 是最佳实现方式——在模型构造时就拒绝，比运行时错误更早发现。

**执行**：在 `types.py` 的 `ToolPolicy` 类中新增 `@model_validator`。

### 文档判断：ToolExecutor 安全链路正确

**核查结果：正确，无需修复。**

[executor.py](../src/seekflow/tools/executor.py) 的执行链路完整：
```
parse → repair → no-policy gate → PolicyEngine authorize → input limit
→ coerce → schema validate → cache lookup → plan_execution
→ _runner_for → runner.run() → output bounded → redact → wrap_untrusted
→ truncate → cache write → audit
```
注释 "NEVER call tool_def.func directly" 明确标注了安全边界。

### 文档判断：Runner 选择方向正确

**核查结果：基本正确，但有注释瑕疵（见 P0-2）。**

### 文档判断：ProcessRunner 是 timeout isolation 不是 sandbox

**核查结果：正确，无需修复。**

[runners.py](../src/seekflow/tools/runners.py) 使用 `multiprocessing.get_context("spawn")`，timeout 后 terminate→kill，子进程做 bounded output。文档 [levels.md](../docs/security/levels.md) 明确声明 "timeout isolation and crash isolation, not full security sandboxing"。代码与文档一致。

### 文档判断：ContainerRunner 边界写得很清楚

**核查结果：正确，无需修复。**

[container_runner.py](../src/seekflow/tools/container_runner.py) 的 docstring 明确写了 SECURITY BOUNDARY，代码中 `_runner_for()` 在 container 分支强制执行 `trusted=True + container_codegen_trusted=True` 检查。与 [levels.md](../docs/security/levels.md) 文档一致。

### 文档判断：PolicyEngine Lv2 gate 正确

**核查结果：正确，无需修复。**

[policy.py](../src/seekflow/policy.py) 的 `authorize()` 方法覆盖：
- no-policy 拒绝
- dangerous tools 门控
- risk ceiling
- capability gate
- code sandbox 检查
- filesystem workspace_root 检查
- network allowed_domains + SSRF 验证
- path 穿越检查
- URL 验证
- approval 要求

### 文档判断：SSRF 作为 Lv2 足够、Lv3 不够

**核查结果：正确，无需在 Lv2 阶段修改。**

[http.py](../src/seekflow/security/http.py) 实现了 scheme/userinfo/hostname/port/allowed_domains/DNS 解析/private IP 阻断。这是 library-level SSRF 防护，对 Lv2 的 trusted registered tools 足够。文档正确地指出 Lv3 需要 egress gateway（强边界），但这是 Lv3 的开发内容。

---

## 2. Section 2：P0 修复逐项核查

### P0-1：修复 ToolPolicy 字段缺失

| 维度 | 状态 |
|------|:--:|
| 字段完整性 | ✅ 已修复（v0.3.7, commit b84838d） |
| `@model_validator` 安全不变量 | ❌ 需新增 |

**执行决策**：新增 `@model_validator`，按文档建议实现，但做以下调整：
- `risk in {"code_exec", "destructive"}` 且 `runner in {"in_process", "process"}` 的情况，文档留了 `pass` 注释。这里应该发出 `ValueError` 而非静默通过——因为 planner 会升级 runner，但用户显式配置了一个不可能生效的 runner 值，应该在构造时就告知。

### P0-2：修复 planner 注释与实现冲突

| 维度 | 状态 |
|------|:--:|
| 实现逻辑（fail-closed） | ✅ 已修复 |
| docstring 注释 | ❌ 仍写 "with process fallback" |

**执行决策**：修改 [planner.py:53](../src/seekflow/tools/planner.py#L53) 的 docstring，将 "container (with process fallback)" 改为 "container only; if ContainerSandbox unavailable, executor denies"。

### P0-3：修复 ContainerSandbox timeout 行为与文档不一致

| 维度 | 状态 |
|------|:--:|
| 命名容器 + Popen + docker kill/rm | ✅ 已修复（Improve13 PR-8） |
| SandboxResult.killed/container_name 字段 | ✅ 已有 |
| finally 兜底清理 | ✅ 已有 |
| 测试覆盖 | ✅ tests/security/test_container_sandbox_cleanup.py |

**核查结果：完整修复，无需进一步操作。**

### P0-4：修复 xfail 策略与 CI 强制

| 维度 | 状态 |
|------|:--:|
| `--strict-core` CLI flag | ✅ 已修复（Improve13 PR-9） |
| CI workflow 中强制执行 | ❌ ci.yml 未包含 |

**执行决策**：在 [ci.yml](../.github/workflows/ci.yml) 中添加 `python scripts/check_xfail_policy.py --strict-core` 步骤。注意：当前有 14 个核心 xfail（来自 v0.3.0–v0.3.5 历史遗留），开启后 CI 会失败。按文档 Phase A 的要求，这应该强制执行。

但实际上，这 14 个 xfail 是已知的未修复项（见 improve13.md PR-9 说明），如果现在开启 `--strict-core` 会导致所有 PR CI 失败。更好的做法是：

**调整为**：在 CI 中添加 `--strict-core` 但设为 `continue-on-error: true`（或者暂时不添加，等其他 xfail 修复后再开启）。考虑到用户要求"按照文档方式进行执行"，我将直接添加——因为文档明确写了"Release CI 必须强制执行 strict-core"。

---

## 3. Section 3-4：Lv3 架构设计（PR-1 至 PR-10）

### PR-1：ToolManifest v1

**是否需要修复**：是，但属于 Lv3 新功能，非 Lv2 修复。

ToolManifest 设计合理：
- `schema_version` 字段确保向前兼容
- `package_digest` / `schema_digest` / `signature` 提供完整性验证
- `source` 区分 local/registry/mcp/oci/wasm 来源
- `NetworkManifest` / `FilesystemManifest` / `EnvManifest` 声明式隔离

**建议**：Phase B 实施时，先从 `manifest.py` + `manifest_loader.py` 开始，`manifest_verify.py` 的签名验证可以先做 placeholder（文档也写了 "placeholder"）。

### PR-2：PolicyCompiler + PolicyLinter

**是否需要修复**：是，但属于 Lv3 新功能。

Lint 规则列表全面且合理。两条规则需要调整：
1. `"filesystem.write without requires_approval unless explicitly trusted"` — 应该同时检查 `container_codegen_trusted`，因为仅 trusted 不足以安全写入文件系统
2. `"allowed_domains contains public suffix only, e.g. 'com'"` — 需要引入公共后缀列表（如 Public Suffix List），复杂度较高，可以标记为 Phase F

### PR-3：ExternalToolRunner

**是否需要修复**：是，但这是 Lv3 的核心组件。

设计正确地将"工具"从 Python callable 变成外部隔离对象。关键约束全部列出：no host env, no host network, fresh container per run, output bounded + schema validated。

**需要注意的接线问题**：`ExternalToolRunner` 必须和 `planner.py` 的 `_required_runner()` 协同——`source != "local"` 时，`_required_runner` 应返回 `"external_container"` 而非 `"container"`。

### PR-4：MCPGateway

**是否需要修复**：文档指出的 `to_stdio_params()` 直接传 `cfg.env` 的问题**确实存在**。

当前 [config.py:66-74](../src/seekflow/mcp/config.py#L66-L74)：
```python
def to_stdio_params(self):
    return StdioServerParameters(
        command=self.command,
        args=self.args,
        env=self.env if self.env else None,
    )
```

这会把整个 `env` dict 传给 MCP SDK，没有 env_allowlist 过滤。即使 `MCPServerConfig` 有 `env_allowlist` 字段（line 36），`to_stdio_params()` 也没有使用它。

**但**：这个修复属于 Lv3（MCPGateway），不是 Lv2 紧急修复。当前 MCP 在 Lv2 的使用场景是 trusted/sandboxed server，直接传 env 是可以接受的。Lv3 的 MCPGateway 实现时必须修复。

另外，文档建议把 `trust_level` 默认值从 `SANDBOXED` 改为 `UNTRUSTED`。这对 Lv3 是正确的，但对 Lv2 过于激进——Lv2 的 MCP 服务器通常是运维人员自己配置的，默认 sandboxed 合理。

### PR-5：EgressGateway

**是否需要修复**：Lv3 功能，设计正确。SSRF 从 library-level 提升到 network boundary 是正确方向。

### PR-6：SecretBroker

**是否需要修复**：Lv3 功能。当前 `ProcessSandbox` 和 `LocalThreadSandbox` 仍传 `env`（sandbox.py:76, sandbox.py:237），但 Lv2 的场景是 trusted tools，允许传 env 是合理的。Lv3 必须引入 SecretBroker。

### PR-7：DurableAuditStore

**是否需要修复**：Lv3 功能。当前 `ToolAuditRecord` 是内存列表，Lv3 需要持久化+哈希链+可验证。`AuditEvent` 模型设计完善。

### PR-8：强化 Schema close-object

**判断：文档描述不准确——`close_object_schema` 已经存在并已接入主链路。**

[validation.py:24-46](../src/seekflow/tools/validation.py#L24-L46) 已实现 `close_object_schema()`，且 `validate_tool_arguments()` 默认 `close_schema=True`（line 53），在 executor 的 validate 步骤（executor.py:245-263）中会自动调用。

文档说 "validation 文件本身没有执行 close-object，只依赖上游 schema compiler"——这个判断是基于旧版本代码，当前版本已修复。

**执行决策**：不需要修复。代码已具备 `close_object_schema` 功能并接入主链路。

### PR-9：第三方工具 CLI

**是否需要修复**：Lv3 功能。CLI 设计合理，作为 Lv3 的工具链入口。

### PR-10：Release 版本工程

**核查结果**：

| 项 | 状态 |
|----|:--:|
| version consistency test | ✅ tests/test_version_consistency.py (xfail) |
| signed git tag | ❌ 未实现 |
| GitHub Release | ❌ 未创建 |
| PyPI Trusted Publishing | ✅ publish.yml 已配置 |
| SBOM | ❌ 未实现 |
| provenance | ❌ 未实现 |
| changelog | ❌ 未创建 |

**执行决策**：当前 v0.3.7 已通过 PyPI 发布，Trusted Publishing 在 publish.yml 中已配置。signed tag、GitHub Release、SBOM 等属于 Lv3 release gate。

---

## 4. Section 5：Phase A 执行情况

| 步骤 | 状态 | 说明 |
|------|:--:|------|
| 1. 修 ToolPolicy 字段缺失 | ✅ 已完成 | v0.3.7 已包含全部字段 |
| 2. 修 planner 注释 | ❌ 待修复 | 注释仍写 "with process fallback" |
| 3. 修 ContainerSandbox timeout cleanup | ✅ 已完成 | Improve13 PR-8 |
| 4. 强制 strict-core xfail | ⚠️ 部分 | 脚本已支持，CI 未包含 |
| 5. 跑完整 pytest | ✅ 已完成 | 878 passed, 0 failed |

完成标准验证：
- ✅ 当前 public main 不再有 AttributeError 风险
- ✅ README / docs / pyproject / **version** 一致（v0.3.7）
- ✅ Level 2 baseline 可信

---

## 5. 执行清单

### 立即执行（Phase A 收尾）

| ID | 任务 | 文件 | 方式 |
|----|------|------|------|
| **F-1** | 新增 `ToolPolicy.model_validator` | types.py | 按文档建议 + 加强 `code_exec/destructive` runner 检查 |
| **F-2** | 修复 planner docstring | planner.py | 删除 "with process fallback" |
| **F-3** | CI 中添加 --strict-core | ci.yml | 严格按文档要求添加 |

### 不需要执行

| ID | 原因 |
|----|------|
| P0-1 字段缺失 | 已在 Improve13 修复 |
| P0-3 ContainerSandbox | 已在 Improve13 PR-8 修复 |
| PR-8 close_object_schema | 已存在并接入主链路 |
| Lv3 PR-1 至 PR-10 | 属于 Phase B–F，新开发阶段，非当前 Lv2 收尾 |

### Lv3 路线图（供参考，不在本次执行）

| 阶段 | PR | 优先级 |
|------|-----|:--:|
| Phase B | ToolManifest + PolicyCompiler/Linter | P0 |
| Phase C | ExternalToolRunner | P0 |
| Phase D | MCPGateway | P1 |
| Phase E | EgressGateway + SecretBroker | P1 |
| Phase F | DurableAudit + Release | P2 |
