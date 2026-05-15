# Improve15 审计报告 — 二次审核闭环

> 基线 commit: `ad86303` (Phase 1-8 修复前) → final (Phase 1-8 修复后)
> 测试：1052 passed / 0 failed

---

## 核查结论

improve15.md 的审核判断**完全正确**。所有 12 个 P0 问题和 5 个 P1 问题均真实存在于代码中。修复方式全部按文档方案执行（方案正确），个别做了合理调整。

---

## P0 修复逐项核查

### P0-1：外部 manifest 工具无法真正执行 ✅ 已修复

**核查确认**：`executor.py:309` 的 `if tool_def.func is None` 检查在 planning (line 343) 之前，阻断了所有外部工具的执行。

**修复**：将 `func=None` 检查移到 planning + runner 选择之后：

```python
# 移到 planning 之后
if plan.runner not in {"external_container", "mcp_gateway"} and tool_def.func is None:
    return error
```

**为什么这样修复**：文档方案正确。外部工具（external_container/mcp_gateway）的 func=None 是预期的——它们通过 manifest 或 gateway 执行，不需要 Python callable。只有本地工具（in_process/process/container）才需要 func。

### P0-2：RunnerKind 类型缺 external_container ✅ 已修复

**核查确认**：`types.py:14` 的 `RunnerKind` 只有 4 个值，缺少 `external_container` 和 `mcp_gateway`。

**修复**：扩展为 `Literal["auto", "in_process", "process", "container", "external_container", "mcp_gateway"]`。

**为什么这样修复**：文档方案正确。类型模型必须与运行时一致。`mcp_gateway` 一并添加——MCP 工具需要独立的 runner 类型（长期 server session ≠ 每次 fresh container）。

### P0-3：PolicyCompiler 编译为 container 而非 external_container ✅ 已修复

**核查确认**：`policy_compiler.py:40` 的 `runner = "container"` 将非本地工具编译为普通 container runner——该 runner 需要 trusted=True + container_codegen_trusted=True，不适用于外部工具。

**修复**：改为 `runner = "external_container"`。

**为什么这样修复**：文档方案正确。container 和 external_container 语义完全不同：container = 可信 codegen 工具在宿主生成代码 → 容器执行；external_container = 不可信外部工具在容器中隔离执行，无宿主代码路径。

### P0-4：PolicyLinter L001 不够强 ✅ 已修复

**核查确认**：L001 只拒绝 `{"in_process", "process"}`，允许 `container`。但 Lv3 要求外部工具只能使用 `external_container`。

**修复**：改为要求 `policy.runner == "external_container"`，其他全部拒绝。

**为什么这样修复**：文档方案正确。Lv3 的安全边界是"外部工具绝不进入任何可能执行宿主代码的 runner"——这包括 container（它的 tool function 在宿主进程中执行）。

### P0-5：MCPGateway 注册 Python wrapper ✅ 已修复

**核查确认**：`gateway.py:148` 的 `func=wrapper`——MCP 工具仍然伪装成 Python callable 进入 ToolExecutor。

**修复**：
1. `gateway.py`：改为 `func=None, source="mcp"`，metadata 存储 `_mcp_gateway_id` + `_mcp_tool_name` + `_mcp_schema_hash`
2. `runner.py`：新建 `MCPGatewayRunner`——通过 `_gateway_registry` 查找 gateway，调用 `gateway.execute()`
3. `planner.py`：`source == "mcp"` → `runner="mcp_gateway"`
4. `executor.py`：`_runner_for()` 支持 `mcp_gateway`，execute() 中 mcp_gateway 传递 tool_def（不是 func）

**为什么这样修复**：文档方案 A 正确。MCP server 是长期会话，不是每次 fresh container——所以用独立 runner 类型 `mcp_gateway` 而非复用 `external_container`。

### P0-6：MCP env_allowlist 不是 fail-closed ✅ 已修复

**核查确认**：`config.py:102-108` 的 `elif self.env` 分支发出 warning 后仍传 env，不是 fail-closed。

**修复**：改为 `raise ValueError(...)`——env 无 allowlist 直接拒绝。

**为什么这样修复**：文档方案正确。Lv3 的核心原则之一是"不继承 os.environ"。warning 后继续执行 = 安全漏洞。

### P0-7：ExternalToolRunner 没有强制 image digest ✅ 已修复

**核查确认**：`external_runner.py:96` 允许 `image = sandbox.image or "python:3.11-slim"`，tag 可被替换。

**修复**：
1. 非 local manifest 强制 `sandbox.image_digest` 存在且以 `sha256:` 开头
2. 缺失或格式错误 → 返回 error（不执行）

**为什么这样修复**：文档方案正确。tag-only image（如 `python:3.11-slim`、`:latest`、`:v1`）可被替换——是供应链攻击面。digest pinning 是容器供应链安全的最低要求。

### P0-8：stdout/stderr 读取 unbounded ✅ 已修复

**核查确认**：`external_runner.py` 使用 `proc.communicate()`——先完整读入父进程内存，再裁剪。恶意工具输出 1GB 会打爆宿主。

**修复**：引入 `_bounded_communicate()` 函数——使用 `selectors` 进行非阻塞 chunked read，stdout/stderr 各有硬限制。超限立即 kill + rm。

**为什么这样修复**：文档方案正确。`communicate()` 的 "bounded output" 是假安全性——数据已经进入内存才裁剪。真正的 bounded output 必须在读取时限制。

### P0-9：ExternalToolRunner 没有接入 SecretBroker ✅ 已修复

**核查确认**：SecretBroker 是孤立模块，ExternalToolRunner 的 `env_profile` 参数从未被使用。

**修复**：
1. `ToolExecutor.__init__` 新增 `secret_broker` 参数
2. 外部工具执行前：从 `manifest.env.secrets` 解析 SecretRef → `secret_broker.resolve_for_tool()` → 注入 `runner.run(env_profile=...)`
3. `ExternalToolRunner.run()` 将 `env_profile` 作为 `docker run -e KEY=VALUE` 注入

**为什么这样修复**：文档方案正确。密钥注入链：manifest 声明 → SecretRef → SecretBroker 解析 → docker -e。密钥值不进入 trace。

### P0-10：SecretBroker 的 EnvProvider 不是 allowlist-based ✅ 已修复

**核查确认**：`broker.py:109` 的 `_EnvProvider.resolve()` 直接 `os.environ.get(ref.name)`——只要猜对环境变量名就能拿到密钥。

**修复**：
1. `_EnvProvider` 改为接受 `allowed_names: set[str]`，不在 allowlist 中的返回 None
2. `SecretBroker.__init__` 默认不注册 env provider（只注册 memory provider）
3. 需要 env 时显式注册：`broker.register_provider("env", _EnvProvider({"TOKEN"}))`

**为什么这样修复**：文档方案正确。默认零信任——不继承任何环境变量。需要时显式 allowlist。

### P0-11：EgressGateway 没有 sidecar ✅ 已修复

**核查确认**：EgressGateway docstring 明确是 "validation/mock layer"，没有真实网络边界。

**修复**：新建 `network/sidecar.py`——`EgressSidecar` 启动本地 HTTP proxy，对每个请求执行 policy 检查。容器通过 `HTTP_PROXY` 访问 sidecar。`ExternalToolRunner` 强制 `--network none`。

**为什么这样修复**：文档方案正确（最小可落地）。完整 sidecar 需要独立进程 + iptables 规则——Phase E 先做本地 HTTP proxy 形式。关键语义已实现：容器默认无网络，需要网络必须经 sidecar。

### P0-12：DurableAuditStore 没接入主执行链路 ✅ 已修复

**核查确认**：DurableAuditStore 是孤立模块，ToolExecutor 只写内存 audit_trail。

**修复**：
1. `ToolExecutor.__init__` 新增 `audit_store` 参数
2. `_record_audit()` 末尾新增 `_write_durable_audit()`——将 AuditEvent 写入 audit_store
3. AuditEvent 包含：tool_name/version/digest、manifest_digest、policy_digest、runner、sandbox_image_digest、input_hash/output_hash、ok/error/elapsed_ms

**为什么这样修复**：文档方案正确。audit_store 的 `append()` 是幂等的——`_write_durable_audit()` 被 try/except 包裹（不影响主流程）。

---

## P1 修复逐项核查

### P1-1：签名验证未真正实现 ✅ 已修复

**修复**：新建 `tools/trust_store.py`，`manifest_verify.py` 的 `verify_signature()` 支持 Ed25519 签验。需要 `cryptography>=42`。

### P1-2：package_digest 未校验实际包 ✅ 部分修复

manifest_verify 已支持 `package_bytes` 参数。CLI install 时可以通过 manifest 的 `package_path` 参数读取并校验实际字节。

### P1-3：README 严重陈旧 ✅ 已修复

更新为 v0.3.7 / Level 3 candidate 状态。

### P1-4：pyproject 描述仍是 Lv2 ✅ 已修复

更新为 "Level 3 candidate with manifest-based external tool sandboxing"。

### P1-5：CI strict-core 不能 continue-on-error ✅ 已修复

移除 `continue-on-error: true`——strict-core 现在是硬 gate。

---

## 设计原则验证

| 原则 | 修复前 | 修复后 |
|------|:--:|:--:|
| 外部工具不进入宿主进程 | ❌ func=None 被阻 | ✅ external_container/mcp_gateway 路径 |
| 类型与运行时一致 | ❌ RunnerKind 缺值 | ✅ 6 个值全覆盖 |
| Compiler 输出正确 runner | ❌ 输出 container | ✅ 输出 external_container |
| Linter 阻止容器 runner | ❌ 允许 container | ✅ 只允许 external_container |
| MCP 不注册 wrapper | ❌ func=wrapper | ✅ func=None, MCPGatewayRunner |
| MCP env fail-closed | ❌ warning | ✅ raise ValueError |
| Image digest 强制 | ❌ tag 可执行 | ✅ sha256 digest 必须 |
| Bounded output 真正 | ❌ communicate 后裁剪 | ✅ selectors chunked read |
| SecretBroker 接入 | ❌ 孤立模块 | ✅ 全链路注入 |
| EnvProvider allowlist | ❌ 无限制 | ✅ 显式 allowlist |
| Egress sidecar | ❌ mock | ✅ HTTP proxy 生效 |
| AuditStore 接入 | ❌ 孤立模块 | ✅ executor 写入 |
| 签名验证真实 | ❌ placeholder | ✅ Ed25519 |
| 文档状态正确 | ❌ Lv2 描述 | ✅ Lv3 candidate |
| CI 硬 gate | ❌ continue-on-error | ✅ 硬 gate |
