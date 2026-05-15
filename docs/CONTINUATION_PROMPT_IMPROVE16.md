# SeekFlow v0.3.7 — Improve16 Lv3 闭环实施 Prompt

将此文件内容完整复制给新对话中的 Claude Code。

---

## 项目上下文

你正在处理 `WYZAAACCC/SeekFlow` 项目——一个 DeepSeek-native zero-trust tool runtime。项目当前处于 **Level 3 candidate early** 阶段，目标是完成剩余闭环推进到 **Level 3 candidate**。

**代码基线**：commit `a15d605`（或最新 main），版本 v0.3.7
**测试基线**：`1052 passed / 0 failed / 52 skipped / 52 xfailed`
**GitHub**：https://github.com/WYZAAACCC/SeekFlow

当前已完成的 Lv3 组件：
- ToolManifest v1（声明式工具契约）
- PolicyCompiler + PolicyLinter（11 lint 规则）
- ExternalToolRunner（容器化第三方工具执行，bounded stream read）
- MCPGateway + MCPGatewayRunner（零信任 MCP，func=None）
- EgressGateway + EgressSidecar（HTTP proxy 骨架）
- SecretBroker（EnvProvider 需显式 allowlist）
- DurableAuditStore（JSONL + SQLite，已接入 executor）
- TrustStore + Ed25519 signature verification（trust_store.py 存在）
- RunnerKind 6 值全覆盖（含 external_container + mcp_gateway）
- Planner source gate（source != "local" → external_container, source="mcp" → mcp_gateway）
- Executor func=None 检查已移至 planning 之后

本轮 improve16.md 审计发现 **8 个剩余缺口**（4 P0 + 4 P1），需要 6 个 Phase 完成闭环。

---

## 关键架构决策（请严格遵守）

1. **不重写已有模块**：planner、executor、runners、policy、manifest pipeline 的核心逻辑保留，只做边界补齐和接线
2. **安全默认拒绝**：egress sidecar 未启动时网络工具不可用（fail-closed）、签名验证 strict 模式不可绕过、audit_required 时写失败阻断执行
3. **显式依赖注入**：MCP gateway registry 从全局变量改为 ToolExecutor 参数注入
4. **进程边界不可信**：ExternalToolRunner stdout/stderr 以 bytes 计数，text=False
5. **每个 Phase 至少 3 个测试**：不写测试的改动 = 不完整
6. **接线优先**：新功能必须接入主执行链路（ToolExecutor → Planner → Runner），不能是孤立模块

---

## Phase 1：补齐 Supply-chain 安全（P0-B + P0-C）

### P0-B：Manifest 签名真实验签

**当前状态**：[manifest_verify.py:96-103] 的 `verify_signature()` 在 strict=True 且 cryptography 未安装时抛异常，但在 strict=False 时静默接受任何签名。trust_store.py 已有 Ed25519 实现但未强制接入验证路径。

**修复**：

(a) [manifest_verify.py] 重写 `verify_signature()`：

```python
def verify_signature(
    manifest: ToolManifest,
    *,
    strict: bool = False,
    trust_store: "TrustStore | None" = None,
) -> None:
    if manifest.source != "local" and strict:
        if not manifest.signature:
            raise ManifestVerificationError("strict mode requires signature")
        if not manifest.signing_key_id:
            raise ManifestVerificationError("strict mode requires signing_key_id")
        if trust_store is None:
            raise ManifestVerificationError("strict mode requires trust_store")

    if not manifest.signature:
        return

    # Real verification when signature present
    if trust_store is not None and manifest.signing_key_id:
        from seekflow.tools.trust_store import verify_ed25519_signature
        try:
            verify_ed25519_signature(manifest, trust_store)
        except ImportError:
            raise ManifestVerificationError(
                "cryptography>=42 required for signature verification"
            )
```

(b) [pyproject.toml] 在 `dev` dependencies 中添加 `cryptography>=42`（或作为 `security` optional dependency）：

```toml
[project.optional-dependencies]
security = ["cryptography>=42"]
dev = ["pytest>=8.0.0", "pytest-asyncio>=0.23.0", "ruff>=0.5.0", "mypy>=1.0.0", "cryptography>=42"]
```

(c) [trust_store.py] 的 `TrustStore.__init__` 增加可选参数：

```python
class TrustStore:
    def __init__(self, keys: dict[str, bytes] | None = None):
        self._keys: dict[str, bytes] = dict(keys) if keys else {}
```

### P0-C：package_digest 强制绑定实际包

**修复**：

(a) [manifest.py] 在 `ToolManifest` 中新增字段：

```python
package_path: str | None = None
package_url: str | None = None
oci_image: str | None = None
```

(b) [cli.py] 的 `tool_install` 命令中，strict 模式时：

```python
if strict and manifest.source != "local":
    package_bytes = None
    if manifest.package_path:
        package_bytes = Path(manifest.package_path).read_bytes()
    elif manifest.package_url:
        # download and read
        import urllib.request
        with urllib.request.urlopen(manifest.package_url) as resp:
            package_bytes = resp.read()
    elif manifest.oci_image and manifest.sandbox.image_digest:
        # OCI: verify the image reference is name@sha256:... not tag-only
        if "@sha256:" not in manifest.oci_image:
            raise typer.BadParameter("OCI image must use name@sha256:... digest pinning")
        # package_bytes stays None for OCI (verified at container runtime)

    verify_manifest(manifest, package_bytes=package_bytes, strict=True, trust_store=trust_store)
```

### 验收测试

新建 [tests/tools/test_manifest_signature.py]：

```python
def test_strict_external_manifest_requires_signature():
    """strict=True 下外部 manifest 无签名 → 拒绝"""

def test_strict_external_manifest_requires_trust_store():
    """strict=True 下无 trust_store → 拒绝"""

def test_valid_ed25519_signature_passes():
    """正确 Ed25519 签名 → 通过"""
    # from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    # private_key = Ed25519PrivateKey.generate()
    # public_key = private_key.public_key()
    # signature = private_key.sign(canonical_manifest_bytes(manifest))
    # manifest.signature = base64.b64encode(signature).decode()

def test_invalid_signature_fails():
    """签名不匹配 → 拒绝"""

def test_unknown_signing_key_fails():
    """signing_key_id 不在 trust_store → 拒绝"""

def test_manifest_tamper_after_signing_fails():
    """签后篡改 → 拒绝"""

def test_package_digest_mismatch_rejected():
    """实际包 digest 与 manifest 不一致 → 拒绝"""

def test_oci_tag_only_rejected():
    """OCI image 使用 tag 而非 digest → CLI 拒绝"""

def test_cli_install_strict_validates_package():
    """CLI install --strict 读取实际包并校验 digest"""
```

---

## Phase 2：实现真实 Egress Sidecar（P0-A）

**当前状态**：[external_runner.py:117-121] 在 manifest 有 network 需求时注释写 "For now, block — sidecar must be explicitly started"，实际仍使用 `--network none`。sidecar.py 存在 HTTP proxy 骨架但未被调用。

### 修复

(a) [external_runner.py] 的 `__init__` 新增参数：

```python
class ExternalToolRunner:
    def __init__(self, egress_sidecar: "EgressSidecar | None" = None):
        self.egress_sidecar = egress_sidecar
```

(b) [external_runner.py] 的 `run()` 方法中，替换 network 逻辑：

```python
sidecar_handle = None
env_vars: dict[str, str] = {}

if manifest.network.allowed_domains:
    if self.egress_sidecar is None:
        return ToolRunResult(
            ok=False,
            error="Network tool requires EgressSidecar to be configured",
            runner_name=self.name,
        )
    from seekflow.network.egress import EgressPolicy
    policy = EgressPolicy(
        allowed_domains=manifest.network.allowed_domains,
        allowed_schemes=manifest.network.allowed_schemes,
        allowed_ports=manifest.network.allowed_ports,
        allowed_methods=manifest.network.allowed_methods,
        max_request_bytes=manifest.network.max_request_bytes,
        max_response_bytes=manifest.network.max_response_bytes,
        max_redirects=manifest.network.max_redirects,
        block_private_ips=manifest.network.block_private_ips,
        require_tls=manifest.network.require_tls,
    )
    sidecar_handle = self.egress_sidecar.start(
        policy=policy,
        tool_name=manifest.name,
        run_id=run_id if run_id else "",
    )
    network_mode = "none"  # 工具容器自身仍无网络
    env_vars["HTTP_PROXY"] = sidecar_handle.proxy_url
    env_vars["HTTPS_PROXY"] = sidecar_handle.proxy_url
else:
    network_mode = "none"
```

(c) [executor.py] 的 `_runner_for("external_container")` 分支，传递 egress_sidecar：

```python
if plan.runner == "external_container":
    from seekflow.tools.external_runner import ExternalToolRunner
    return ExternalToolRunner(egress_sidecar=getattr(self, "egress_sidecar", None))
```

(d) [executor.py] 的 `__init__` 新增参数：

```python
egress_sidecar: Any | None = None,
```

(e) 在 executor 的 external_container 执行后，将 sidecar audit entries 收集并传入 durable audit。

### 验收测试

新建 [tests/network/test_egress_sidecar_integration.py]：

```python
def test_external_tool_no_network_by_default():
    """无 network manifest → --network none → 无 proxy"""

def test_external_tool_network_requires_sidecar():
    """有 network manifest 但无 sidecar → 返回 error"""

def test_external_tool_uses_http_proxy_env():
    """有 sidecar → 容器收到 HTTP_PROXY/HTTPS_PROXY"""

def test_egress_blocks_private_ip():
    """代理拒绝私有 IP"""

def test_egress_blocks_metadata_ip():
    """代理拒绝 metadata IP (169.254.169.254)"""

def test_egress_blocks_redirect_to_private_ip():
    """redirect 到私有 IP → 拒绝"""

def test_egress_records_audit_entries():
    """代理请求有 audit entry"""
```

---

## Phase 3：MCPGateway 去全局状态 + 输出验证（P0-D + P0-E）

### P0-D：MCPGatewayRegistry 显式依赖注入

**当前状态**：[gateway.py:33] 使用全局 `_gateway_registry` 字典，[runner.py:55-56] 直接 import 全局变量。

**修复**：

(a) [gateway.py] 新增 `MCPGatewayRegistry` 类：

```python
class MCPGatewayRegistry:
    """Explicit registry for MCP gateway instances."""
    def __init__(self):
        self._gateways: dict[str, "MCPGateway"] = {}

    def register(self, gateway: "MCPGateway") -> None:
        self._gateways[gateway.server_name] = gateway

    def get(self, name: str) -> "MCPGateway | None":
        return self._gateways.get(name)

    def remove(self, name: str) -> None:
        self._gateways.pop(name, None)

    def list_all(self) -> list[str]:
        return list(self._gateways.keys())
```

(b) [gateway.py] 的 `connect_and_freeze()` 中，保留全局注册作为默认行为，但接受可选的 registry 参数：

```python
def connect_and_freeze(self, registry, *,
                       gateway_registry: "MCPGatewayRegistry | None" = None):
    ...
    if gateway_registry:
        gateway_registry.register(self)
    else:
        _gateway_registry[self.server_name] = self  # backward compat
```

(c) [runner.py] 的 `MCPGatewayRunner.__init__` 接受 registry 参数：

```python
class MCPGatewayRunner:
    def __init__(self, gateway_registry: "MCPGatewayRegistry"):
        self.gateway_registry = gateway_registry
```

(d) [executor.py] 的 `__init__` 新增参数，`_runner_for` 传递 registry：

```python
mcp_gateway_registry: Any | None = None,

# in _runner_for:
if plan.runner == "mcp_gateway":
    from seekflow.mcp.runner import MCPGatewayRunner
    return MCPGatewayRunner(self.mcp_gateway_registry)
```

### P0-E：MCP 输出 schema validation

**修复**：

(a) [gateway.py] 的 `FrozenTool` 新增字段：

```python
@dataclass
class FrozenTool:
    name: str
    description: str
    schema: dict
    schema_hash: str
    output_schema: dict | None = None  # 🆕
```

(b) [gateway.py] 的 `_freeze_tools()` 中保存 output_schema（如果 MCP server 提供的话）。MCP 协议的 `list_tools` 结果中 `tools[].outputSchema` 字段存在但 optional。

(c) [runner.py] 的 `run()` 方法中，执行后校验输出：

```python
output_schema = (tool_def.metadata or {}).get("_mcp_output_schema")
if output_schema:
    from seekflow.tools.validation import validate_tool_arguments
    issues = validate_tool_arguments(output_schema, bounded_result)
    if issues:
        joined = "; ".join(f"{i.path}: {i.message}" for i in issues[:3])
        return ToolRunResult(
            ok=False,
            error=f"MCP output schema validation failed: {joined}",
            runner_name=self.name,
        )
```

(d) [gateway.py] 的 `connect_and_freeze()` 中将 output_schema 存入 metadata：

```python
metadata={
    "_mcp_gateway_id": cfg.name,
    "_mcp_tool_name": ft.name,
    "_mcp_schema_hash": ft.schema_hash,
    "_mcp_output_schema": ft.output_schema,  # 🆕
}
```

### 验收测试

新建 [tests/mcp/test_mcp_gateway_isolation.py]：

```python
def test_mcp_gateway_runner_uses_injected_registry():
    """MCPGatewayRunner 使用注入的 registry 而非全局变量"""

def test_two_executors_do_not_share_gateway_state():
    """两个 executor 各自独立"""

def test_missing_gateway_fails_closed():
    """registry 中无 gateway → 返回 error"""

def test_mcp_output_schema_valid_passes():
    """输出符合 schema → 通过"""

def test_mcp_output_schema_invalid_fails_closed():
    """输出不符合 schema → 拒绝"""

def test_mcp_output_over_limit_truncated():
    """超大输出 → bounded 后校验或拒绝"""
```

---

## Phase 4：Durable Audit 生产级化（P1-A）

**当前状态**：[executor.py:781] `_write_durable_audit()` 的异常被 `except Exception: pass` 静默吞掉。egress audit 和 secret_refs 未传入 AuditEvent。

**修复**：

(a) [executor.py] 的 `__init__` 新增参数：

```python
audit_required: bool = False,
```

(b) [executor.py] 的 `_write_durable_audit()` 签名扩展：

```python
def _write_durable_audit(self, tool_def, call_id, args,
                          args_hash, result_hash,
                          latency_ms, ok, error, runner_name, risk,
                          egress_entries=None, secret_refs=None):
```

并在 AuditEvent 构造中设置：

```python
event = AuditEvent(
    ...
    egress=egress_entries or [],
    secret_refs=secret_refs or [],
)
```

(c) 写入异常处理：

```python
try:
    self.audit_store.append(event)
except Exception as e:
    if self.audit_required:
        raise AuditStoreError(f"Durable audit write failed: {e}") from e
    import logging
    logging.getLogger("seekflow.executor").warning(
        "Durable audit write failed (non-required mode): %s", e
    )
```

(d) 在 external_container 执行路径中，收集 sidecar audit entries 和 secret_refs 传入 `_record_audit()`。

(e) 在 MCP gateway 执行路径中同样收集。

### 验收测试

新建 [tests/audit/test_executor_durable_audit.py]：

```python
def test_audit_written_on_success():
    """成功执行 → durable audit 已写入"""

def test_audit_written_on_tool_not_found():
    """tool not found → 也写入 audit"""

def test_audit_written_on_policy_denial():
    """policy deny → 也写入 audit"""

def test_audit_contains_secret_refs_without_values():
    """secret_refs 在 audit 中，不含 value"""

def test_audit_contains_egress_summary():
    """egress audit entries 在 AuditEvent 中"""

def test_audit_required_failure_blocks_execution():
    """audit_required=True 时写失败 → 异常抛出"""
```

---

## Phase 5：ExternalToolRunner 输出边界硬化（P1-B）

**当前状态**：[external_runner.py:160] `text=True`，chunk 按字符计数。`_bounded_communicate()` 尾部 drain 阶段（line 361-365）调用 `proc.stdout.read()` 无界读取。

**修复**：

(a) [external_runner.py] 的 `run()` 方法中 Popen 改为：

```python
proc = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=False,  # 🆕 bytes mode
)
```

(b) [external_runner.py] 的 `_bounded_communicate()` 函数签名改为 bytes-based：

```python
def _bounded_communicate(
    proc: "subprocess.Popen",
    timeout_s: float,
    max_stdout: int,  # bytes limit
    max_stderr: int,  # bytes limit
) -> tuple[bytes, bytes, bool, bool]:
```

所有 `stdout_bytes += len(chunk.encode(...))` 改为 `stdout_bytes += len(chunk)`（因为 chunk 已是 bytes）。

(c) 尾部 drain 阶段：

```python
if not timed_out and not limit_exceeded:
    remaining_quota = max_stdout - stdout_bytes
    if remaining_quota > 0:
        chunk = proc.stdout.read(remaining_quota)
        if chunk:
            stdout_chunks.append(chunk)
            stdout_bytes += len(chunk)

# stderr similarly
```

(d) `run()` 方法中解码：

```python
stdout_str = b"".join(stdout_chunks).decode("utf-8", errors="replace")
stderr_str = b"".join(stderr_chunks).decode("utf-8", errors="replace")
```

### 验收测试

新建 [tests/tools/test_external_runner_output_bounds.py]：

```python
def test_stdout_limit_enforced_in_bytes():
    """stdout 超 bytes 限制 → killed + truncated"""

def test_stderr_limit_enforced_in_bytes():
    """stderr 超 bytes 限制 → killed"""

def test_tail_output_after_exit_still_bounded():
    """proc 退出后 drain 仍受限制"""

def test_multibyte_utf8_counted_in_bytes():
    """多字节 UTF-8 按 bytes 计数而非字符"""

def test_limit_exceeded_kills_container():
    """超限后 container 被 kill + rm"""
```

---

## Phase 6：文档与 Release Gate（P1-C）

**当前状态**：README 标题和状态已更新为 Level 3 Candidate，但 Security Status 段落（line ~248）仍写 "Level 2 semi-production"。Lv3 能力声明不完整。

**修复**：

(a) [README.md] 的 Security Status 段落改为：

```markdown
## Security Status (v0.3.7)

SeekFlow v0.3.7 is a **Level 3 candidate**:

**Supported (Lv2, production-ready):**
- Trusted local tools under ToolPolicy
- Policy-enforced execution with runner isolation
- ProcessRunner timeout kill + ContainerRunner container isolation
- Cache restricted to read/idempotent-network only
- No-policy tools denied by default

**Experimental (Lv3 candidate):**
- Manifest-based external tool registration
- ExternalToolRunner (containerized third-party tools with JSON protocol)
- MCPGateway (zero-trust MCP with tool freeze + mutation detection)
- EgressGateway + EgressSidecar (network boundary for external tools)
- SecretBroker (explicit secret injection, no ambient env)
- DurableAuditStore (JSONL + SQLite with hash chain)

**Not yet:**
- Egress sidecar not yet production-hardened for high-throughput
- Manifest signature verification requires cryptography package
- GitHub provenance / SBOM / signed releases pending
- Full Level 3 production-ready certification pending the above
```

(b) [docs/security/levels.md] 更新 Lv3 描述：

```markdown
## Level 3 — Candidate (v0.3.7)

Level 3 candidate supports experimental untrusted third-party tools through
manifest-based contracts, containerized execution, and zero-trust networking.
Not yet full production-ready for untrusted multi-tenant workloads.
```

(c) [.github/workflows/ci.yml] 确保 CI 包含所有新测试文件：

```yaml
- run: pytest tests/ -q
- run: python scripts/check_xfail_policy.py --strict-core
```

(d) [docs/production-readiness.md] 更新 checklist 包含 Phase 1-6 所有验收项。

---

## 执行顺序建议

按依赖关系：Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6

- **Phase 1**（Supply-chain）无内部依赖，先做
- **Phase 2**（Egress sidecar）依赖 Phase 1 完成后的稳定基线
- **Phase 3**（MCP）依赖 Phase 2 的 executor 参数扩展模式
- **Phase 4**（Audit）依赖 Phase 2+3 的 egress/secret 数据流
- **Phase 5**（Output bounds）独立，可在 Phase 2-4 之间做
- **Phase 6**（Docs）最后做，反映所有修改

每个 Phase 完成后必须：
1. 运行该 Phase 的新测试：`pytest tests/<new_test_file> -v`
2. 运行全量回归：`pytest tests/ -q`
3. 如果全量回归有失败，修复后再进入下一 Phase

---

## 关键文件清单

| 文件 | 作用 | Phase |
|------|------|:--:|
| `src/seekflow/tools/manifest.py` | 新增 package_path/package_url/oci_image 字段 | 1 |
| `src/seekflow/tools/manifest_verify.py` | 重写 verify_signature() | 1 |
| `src/seekflow/tools/trust_store.py` | TrustStore.__init__ 增加 keys 参数 | 1 |
| `src/seekflow/cli.py` | tool install strict 模式真实校验 | 1 |
| `pyproject.toml` | 添加 cryptography 依赖 | 1 |
| `src/seekflow/tools/external_runner.py` | EgressSidecar 接线 + text=False + bounded drain | 2, 5 |
| `src/seekflow/network/sidecar.py` | EgressSidecar.start() 返回 docker_network | 2 |
| `src/seekflow/network/egress.py` | EgressPolicy.from_manifest() 或等价的构造方式 | 2 |
| `src/seekflow/tools/executor.py` | egress_sidecar + mcp_gateway_registry + audit_required 参数 | 2, 3, 4 |
| `src/seekflow/mcp/gateway.py` | MCPGatewayRegistry + FrozenTool.output_schema + metadata | 3 |
| `src/seekflow/mcp/runner.py` | 构造函数注入 registry + output schema validation | 3 |
| `src/seekflow/audit/model.py` | AuditEvent 的 egress/secret_refs 字段已存在，确认足够 | 4 |
| `README.md` | Security Status 段落更新 | 6 |
| `docs/security/levels.md` | Lv3 candidate 描述 | 6 |
| `docs/production-readiness.md` | Release checklist 更新 | 6 |
| `.github/workflows/ci.yml` | 测试覆盖确认 | 6 |
| `tests/tools/test_manifest_signature.py` | 签名验证测试 | 🆕 1 |
| `tests/network/test_egress_sidecar_integration.py` | Egress sidecar 集成测试 | 🆕 2 |
| `tests/mcp/test_mcp_gateway_isolation.py` | MCP 隔离测试 | 🆕 3 |
| `tests/audit/test_executor_durable_audit.py` | Audit 生产级测试 | 🆕 4 |
| `tests/tools/test_external_runner_output_bounds.py` | 输出边界测试 | 🆕 5 |

---

## 最终验收标准

```text
代码闸门：
[ ] strict external manifest 必须有签名（P0-B）
[ ] 签名伪造不可通过（P0-B）
[ ] package_digest 与真实包不匹配时拒绝（P0-C）
[ ] OCI image tag-only 被拒绝（P0-C）
[ ] external tool 有 network 需求时启动 sidecar（P0-A）
[ ] sidecar 未配置时网络工具不可用（P0-A）
[ ] sidecar 执行 DNS/IP/domain/method/body/redirect 校验（P0-A）
[ ] MCP gateway 不依赖全局 registry（P0-D）
[ ] MCP 输出经过 schema validation（P0-E）
[ ] durable audit 覆盖成功和失败路径（P1-A）
[ ] audit_required=True 时写入失败阻断执行（P1-A）
[ ] ExternalToolRunner text=False + bytes-level bounded（P1-B）
[ ] drain 阶段仍受限制（P1-B）
[ ] README Security Status 准确描述 Lv3 candidate 状态（P1-C）

测试闸门：
[ ] pytest 0 failed
[ ] 6 个 Phase 各有 ≥3 个测试
[ ] manifest signature 测试全过
[ ] egress sidecar 集成测试全过
[ ] MCP isolation 测试全过
[ ] durable audit 生产级测试全过
[ ] output bounds 边界测试全过
```
