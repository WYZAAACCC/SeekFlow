# Improve16 审计报告

> 基线: commit `a15d605` (Improve15 完成后) | 1052 passed / 0 failed

---

## 总体判断

improve16.md 的审核结论**基本正确**：
- Section 1 中 5 项已修复内容均确认正确
- Section 2 中 8 项未完成内容均真实存在（其中 P1-C 关于 README 标题的描述有误——标题已改为 Level 3 Candidate，但 Security Status 段落仍未更新）

---

## Section 1：已正确修复部分（无需修复）

| 项 | 核查 | 状态 |
|----|------|:--:|
| 1.1 RunnerKind 扩展 | types.py:14 包含6个值 | ✅ |
| 1.2 PolicyCompiler external_container | policy_compiler.py:40 | ✅ |
| 1.3 PolicyLinter L001 强制 external_container | policy_linter.py:42-48 | ✅ |
| 1.4 Planner source gate | planner.py:58-64, 77-89 | ✅ |
| 1.5 Executor func=None | executor.py:368-376 | ✅ |

---

## Section 2：需修复部分逐项核查

### P0-A：Egress sidecar 未形成真实网络边界

**核查确认**：external_runner.py:120-121 — `"For now, block — sidecar must be explicitly started"`。sidecar 模块存在但 ExternalToolRunner 未调用。`--network none` 被硬编码，无 HTTP_PROXY 注入，无 egress audit 回传。

**修复方式判断**：文档方案正确。ExternalToolRunner 需新增 `egress_sidecar` 参数，存在 network 需求时启动 sidecar、创建 docker network、注入 HTTP_PROXY/HTTPS_PROXY、收集 audit entries 回传 executor。

**调整**：文档要求 `EgressPolicy.from_manifest()` 静态方法 —— 应直接添加在 EgressPolicy 上（而非作为 classmethod），因为 Python 3.10+ 支持 `BaseModel` 上定义普通 static method 做构造器。

---

### P0-B：Manifest 签名验证仍是 placeholder

**核查确认**：trust_store.py 和 verify_ed25519_signature 函数存在，但 `manifest_verify.py:96-103` 的 `verify_signature()` 用 try/except ImportError 包裹——如果 cryptography 未安装且 strict=True，抛 `ManifestVerificationError`（"cryptography package required"），但如果不抛（非 strict），就静默通过。

**问题**：strict 模式下如果 cryptography 已安装，签名验证逻辑会执行；但如果 cryptography 未安装 + strict=False，任何签名都能通过。这是"条件性 placeholder"——严格模式可能有效，非严格模式一定无效。

**修复方式判断**：文档方案正确。需要：
1. pyproject.toml 添加 `cryptography>=42` 为 optional dependency（或 core dependency）
2. `verify_signature()` 在 strict=True 且无 cryptography 时直接 fail
3. 文档中的 `TrustStore` 构造函数改为接受 `dict[str, bytes]` 参数（当前是 `add_key()` 方法逐个添加，两种接口都需要）

**当前 trust_store.py 已有**：`add_key()`, `add_key_from_file()`, `get_public_key()` 方法 + `canonical_manifest_bytes()` + `verify_ed25519_signature()` 函数。文档的简化版 `TrustStore.__init__(keys=...)` 可作为额外便利接口。

---

### P0-C：package_digest 未强制绑定实际包

**核查确认**：manifest_verify.py 的 `verify_digest()` 支持 `actual_package_bytes` 参数，若传入则校验。但 CLI install 未读取实际 package bytes 传入。manifest 缺少 `package_path`/`package_url`/`oci_image` 字段来定位实际包。

**修复方式判断**：文档方案正确。需要在 ToolManifest 新增字段，CLI install 根据 source 类型读取实际字节并传入 `verify_digest()`。

---

### P0-D：MCPGatewayRunner 全局 registry 设计风险

**核查确认**：gateway.py:33 定义 `_gateway_registry: dict[str, MCPGateway] = {}`，runner.py:55-56 直接 `from seekflow.mcp.gateway import _gateway_registry`。

**问题**：全局可变状态使得多 Runtime/多租户场景下 gateway 状态串线。测试时无法注入 mock gateway。

**修复方式判断**：文档方案正确——改为显式依赖注入。ToolExecutor 新增 `mcp_gateway_registry` 参数，传递给 MCPGatewayRunner 构造函数。同时 gateway.py 保留全局 registry 作为默认值（向后兼容），但允许覆盖。

**调整**：gateway.py 的 `connect_and_freeze()` 中 `_gateway_registry[cfg.name] = self` 注册逻辑应移到显式 registry 参数中，或通过 ToolExecutor 注入时自动注册。

---

### P0-E：MCP 输出 schema validation 不完整

**核查确认**：MCPGatewayRunner 只做 `serialize_bounded(result.result, max_output_bytes)`，不做 output schema validation。FrozenTool 未保存 output_schema。

**修复方式判断**：文档方案正确。MCP tool discovery 时若协议返回 outputSchema 则保存到 FrozenTool。Runner 执行后使用 `validate_tool_arguments()` 校验输出。

---

### P1-A：Durable audit 信息不够完整

**核查确认**：
- executor.py:781: `except Exception: pass` — 写入失败被静默吞掉
- `_write_durable_audit` 只在 `_record_audit` 中被调用，但早期失败路径（tool not found、parse failed、input limit failed）也会调 `_record_audit` —— 已覆盖
- egress audit entries 未传入 AuditEvent
- secret_refs 未传入 AuditEvent
- `audit_required` 模式不存在

**修复方式判断**：文档方案正确。需新增 `audit_required` 参数（默认 False），True 时写入失败向上抛异常。egress audit 和 secret_refs 需传入 `_write_durable_audit`。

---

### P1-B：ExternalToolRunner bounded reader 仍需修边界

**核查确认**：external_runner.py:160 — `text=True`。这意味着 chunk 大小按字符计数而非 bytes。对于包含多字节 UTF-8 字符的输出，字符计数与字节计数不一致，可能导致实际内存占用超限。

另外 `_bounded_communicate()` 在 proc 退出后调用 `proc.stdout.read()` 无界读取尾部——line 361。

**修复方式判断**：文档方案正确。改为 `text=False`，所有读取和计数以 bytes 为单位。尾部 drain 阶段也加限制。

---

### P1-C：文档状态不完全准确

**核查确认**：
- README 标题（line 1）已是 "Level 3 Candidate" ✅
- README 状态（line 11）已是 "Level 3 candidate" ✅
- **但** README Security Status 段落（line 248）仍写 "Level 2 semi-production" ❌
- 文档中 "untrusted third-party tools / arbitrary MCP servers 不支持" 的声明需要更新——现在有 ExternalToolRunner 和 MCPGateway 的实验性支持

**修复方式判断**：文档方案整体正确，但关于标题的描述已过时。需要更新 Security Status 段落和 Lv3 能力声明。

---

## 修复优先级汇总

| ID | 问题 | 严重度 | Phase |
|----|------|:--:|:--:|
| P0-A | Egress sidecar 未形成真实网络边界 | P0 | Phase 2 |
| P0-B | Manifest 签名验证仍是 placeholder | P0 | Phase 1 |
| P0-C | package_digest 未强制绑定实际包 | P0 | Phase 1 |
| P0-D | MCPGatewayRunner 全局 registry | P0 | Phase 3 |
| P0-E | MCP 输出 schema validation 缺失 | P0 | Phase 3 |
| P1-A | Durable audit 信息不够完整 | P1 | Phase 4 |
| P1-B | Bounded reader text mode + tail drain | P1 | Phase 5 |
| P1-C | 文档 Security Status 段落未更新 | P1 | Phase 6 |
