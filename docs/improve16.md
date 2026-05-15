下面是二次校准后的最终方案，可直接给 Claude Code。结论先说：

**审计报告方向总体正确，但当前代码并未达到完整 Lv3。它已经从“Lv3 skeleton”推进到“Lv3 candidate 早期”，主链路有一部分已经接通；但仍存在 egress、MCP、manifest supply-chain、audit 完整性、文档发布一致性等关键缺口。**

作者报告声称 Improve15 已修复 12 个 P0 与 5 个 P1，并达到 `1052 passed / 0 failed` 。我核对当前公开代码后认为：**P0-1 到 P0-4 的类型、编译、linter、planner、executor 主链路已有明显修复；但 P0-11 egress sidecar、P1-1 真实签名验证、P1-3 文档状态仍没有完全闭环。**

---

# 1. 当前代码已正确修复的部分

## 1.1 RunnerKind 已扩展

当前 `types.py` 已包含：

```python
RunnerKind = Literal[
    "auto",
    "in_process",
    "process",
    "container",
    "external_container",
    "mcp_gateway",
]
```

这说明类型层已经与 Lv3 runner 语义对齐。([GitHub][1])

## 1.2 PolicyCompiler 已把非 local 工具编译为 external_container

`policy_compiler.py` 当前逻辑已经是：

```python
if is_local:
    runner = "auto"
else:
    runner = "external_container"
```

并明确注释非本地工具必须经过 ExternalToolRunner，而不是普通 ContainerRunner。([GitHub][2])

## 1.3 PolicyLinter L001 已强制非 local 只能 external_container

当前 L001 已经变成：

```python
if source in {"registry", "mcp", "oci", "wasm"}:
    if policy.runner != "external_container":
        error
```

这修复了之前“外部工具仍可走普通 container”的问题。([GitHub][3])

## 1.4 Planner 已接入 external_container / mcp_gateway

`planner.py` 当前已有：

```python
RUNNER_ORDER = {
    "in_process": 0,
    "process": 1,
    "container": 2,
    "external_container": 3,
    "mcp_gateway": 3,
}
```

并且：

```python
source == "mcp" → mcp_gateway
source != "local" → external_container
```

这说明 planner 的 source gate 已经基本正确。([GitHub][4])

## 1.5 Executor 已允许 external_container / mcp_gateway 的 func=None

`executor.py` 当前已经把 `func=None` 检查移动到 planning 之后，并允许：

```python
if plan.runner not in {"external_container", "mcp_gateway"} and tool_def.func is None:
```

同时 external path 会从 `_manifest_data` 构造 `ToolManifest`，MCP path 会传 `tool_def` 给 `MCPGatewayRunner`。([GitHub][5])

**结论：这一段主链路已经明显比上一轮强，不能再说完全没接通。**

---

# 2. 当前仍未达到完整 Lv3 的关键问题

## P0-A：Egress sidecar 仍未形成真实网络边界

`ExternalToolRunner` 当前仍然写着：如果 `manifest.network.allowed_domains` 存在，“For now, block — sidecar must be explicitly started”，随后仍使用 `--network none`，没有启动 sidecar、没有注入 `HTTP_PROXY/HTTPS_PROXY`、没有把 egress audit 传回 executor。([GitHub][6])

这意味着：

```text
外部工具默认无网络是安全的；
但“受控联网工具”路径没有真正可用；
EgressGateway/sidecar 仍不是完整 Lv3 出站边界。
```

### Claude Code 修复任务

新增或补全：

```text
src/seekflow/network/sidecar.py
src/seekflow/network/proxy.py
src/seekflow/tools/external_runner.py
src/seekflow/tools/executor.py
tests/network/test_egress_sidecar_integration.py
```

### 目标行为

```text
1. external tool 默认 --network none。
2. manifest.network.allowed_domains 非空时：
   - 启动 EgressSidecar；
   - 创建受控 docker network；
   - 工具容器只能访问 sidecar；
   - 注入 HTTP_PROXY / HTTPS_PROXY；
   - sidecar 执行 DNS/IP/domain/method/body/response 校验；
   - 每次 redirect 重新校验；
   - egress audit 返回 executor；
   - DurableAuditStore 写入 egress summary。
```

### ExternalToolRunner 伪代码

```python
sidecar_handle = None

if manifest.network.allowed_domains:
    if self.egress_sidecar is None:
        return ToolRunResult(
            ok=False,
            error="Network tool requires EgressSidecar",
            runner_name=self.name,
        )

    sidecar_handle = self.egress_sidecar.start(
        policy=EgressPolicy.from_manifest(manifest.network),
        tool_name=manifest.name,
        run_id=run_id,
    )

    network_mode = sidecar_handle.docker_network
    env_vars["HTTP_PROXY"] = sidecar_handle.proxy_url
    env_vars["HTTPS_PROXY"] = sidecar_handle.proxy_url
else:
    network_mode = "none"
```

### 必须测试

```text
test_external_tool_no_network_by_default
test_external_tool_network_requires_sidecar
test_external_tool_uses_http_proxy_env
test_egress_blocks_private_ip
test_egress_blocks_metadata_ip
test_egress_blocks_redirect_to_private_ip
test_egress_records_audit_entries
```

---

## P0-B：Manifest 签名验证仍是 placeholder

`manifest_verify.py` 当前 docstring 仍明确写着：signature verification 是 placeholder；如果签名存在，只检查 strict 模式下 `signing_key_id` 是否存在，并未做真实 Ed25519/ECDSA 验签。([GitHub][7])

这与作者报告“Ed25519 已修复”的描述不一致。

### 风险

```text
strict=True 只能防止“无签名”，不能防止“伪签名”。
攻击者可以伪造 signature 字段与 signing_key_id。
CLI install 也无法提供真实供应链安全。
```

### Claude Code 修复任务

新增：

```text
src/seekflow/tools/trust_store.py
tests/tools/test_manifest_signature.py
```

依赖：

```toml
cryptography>=42
```

### 实现

```python
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import base64

class TrustStore:
    def __init__(self, keys: dict[str, bytes]):
        self.keys = keys

    def get_public_key(self, key_id: str) -> bytes:
        if key_id not in self.keys:
            raise ManifestVerificationError(f"Unknown signing key: {key_id}")
        return self.keys[key_id]
```

```python
def canonical_manifest_for_signature(manifest: ToolManifest) -> bytes:
    data = manifest.model_dump(
        mode="json",
        exclude={"signature"},
        exclude_none=True,
    )
    return json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
```

```python
def verify_signature(
    manifest: ToolManifest,
    *,
    strict: bool = False,
    trust_store: TrustStore | None = None,
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

    public_key_bytes = trust_store.get_public_key(manifest.signing_key_id)
    public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    signature = base64.b64decode(manifest.signature)

    public_key.verify(
        signature,
        canonical_manifest_for_signature(manifest),
    )
```

### 必须测试

```text
test_strict_external_manifest_requires_signature
test_strict_external_manifest_requires_trust_store
test_valid_ed25519_signature_passes
test_invalid_signature_fails
test_unknown_signing_key_fails
test_manifest_tamper_after_signing_fails
```

---

## P0-C：package_digest 仍没有强制绑定实际包/镜像

`verify_digest()` 支持 `actual_package_bytes`，但如果调用方不传，它只验证 `package_digest` 是 64 位 hex。([GitHub][7])

### 修复目标

```text
1. CLI install strict 模式必须读取实际 package bytes。
2. OCI image 必须使用 name@sha256:...。
3. 禁止 tag-only image。
4. manifest.package_digest 必须与实际 package 匹配。
```

### Manifest 建议字段

```python
package_path: str | None = None
package_url: str | None = None
oci_image: str | None = None
```

### CLI install 逻辑

```python
if manifest.source in {"registry", "oci", "wasm"} and strict:
    package_bytes = load_package_bytes_or_verify_oci_digest(manifest)
    verify_manifest(
        manifest,
        package_bytes=package_bytes,
        strict=True,
        trust_store=trust_store,
    )
```

### 必须测试

```text
test_cli_install_strict_reads_package_bytes
test_package_digest_mismatch_rejected
test_oci_tag_only_rejected
test_oci_digest_reference_accepted
```

---

## P0-D：MCPGatewayRunner 存在全局 registry 设计风险

`MCPGatewayRunner` 当前通过：

```python
from seekflow.mcp.gateway import _gateway_registry
gateway = _gateway_registry.get(gateway_id)
```

查找 gateway。([GitHub][8])

这能跑，但对生产级不够好：

```text
- 全局可变状态难测试；
- 多 Runtime / 多租户下容易串线；
- gateway 生命周期与 ToolExecutor 生命周期不明确；
- 无法显式注入权限上下文。
```

### 修复方案

把 gateway registry 从全局改为显式依赖注入。

```python
class ToolExecutor:
    def __init__(
        ...,
        mcp_gateway_registry: MCPGatewayRegistry | None = None,
    ):
        self.mcp_gateway_registry = mcp_gateway_registry
```

```python
if plan.runner == "mcp_gateway":
    return MCPGatewayRunner(self.mcp_gateway_registry)
```

```python
class MCPGatewayRunner:
    def __init__(self, gateway_registry: MCPGatewayRegistry):
        self.gateway_registry = gateway_registry
```

### 必须测试

```text
test_mcp_gateway_runner_uses_injected_registry
test_two_executors_do_not_share_gateway_state
test_missing_gateway_fails_closed
test_gateway_disconnect_removes_registry_entry
```

---

## P0-E：MCP 输出 schema validation 不完整

`MCPGatewayRunner` 当前只做：

```python
serialize_bounded(result.result, max_output_bytes)
```

但没有按 MCP tool 的 output_schema 或 frozen schema 进行输出验证。([GitHub][8])

### 修复

在 MCPGateway freeze 阶段保存：

```python
_frozen_tools[name].output_schema
```

或 metadata 保存：

```python
"_mcp_output_schema": ...
```

Runner 中：

```python
if output_schema:
    issues = validate_tool_arguments(output_schema, bounded_result)
    if issues:
        return ToolRunResult(
            ok=False,
            error=f"MCP output schema validation failed: {joined}",
            runner_name=self.name,
        )
```

### 必须测试

```text
test_mcp_output_schema_valid_passes
test_mcp_output_schema_invalid_fails_closed
test_mcp_output_over_limit_truncated_or_denied
```

---

## P1-A：Durable audit 已接入，但信息不够完整

`executor.py` 已增加 `audit_store`，并在 `_record_audit()` 中写 `AuditEvent`。这是进步。([GitHub][5])

但当前 durable audit 仍不足：

```text
- tool not found / parse failed / input limit failed 等早期失败路径没有全部写 audit；
- egress audit 未进入 AuditEvent；
- secret_refs 未进入 AuditEvent；
- audit 写入异常被静默吞掉；
- result 只取 str(result)[:500] 后 hash，不能代表完整输出；
- run_id / step 依赖 context，缺省时为空，不利于生产追踪。
```

### 修复

```python
def _record_audit(..., egress=None, secret_refs=None, audit_required=False):
    ...
    try:
        self.audit_store.append(event)
    except Exception as e:
        if audit_required:
            raise
        logger.warning("durable audit write failed", exc_info=e)
```

生产模式建议：

```python
audit_required=True
```

### 必须测试

```text
test_audit_written_on_tool_not_found
test_audit_written_on_parse_failure
test_audit_written_on_input_limit_failure
test_audit_contains_secret_refs_without_values
test_audit_contains_egress_summary
test_audit_required_failure_blocks_execution
```

---

## P1-B：ExternalToolRunner 的 bounded reader 仍需修边界

当前 `_bounded_communicate()` 使用 selectors 分块读取，比 `communicate()` 安全很多。([GitHub][6])

但有两个问题：

```text
1. text=True 下 chunk 大小是字符，不是原始 bytes；
2. proc 退出后又调用 proc.stdout.read() / stderr.read()，这里可能再次无界读取尾部。
```

### 修复

```text
- subprocess.Popen 使用 text=False；
- 所有 stdout/stderr 均以 bytes 计数；
- 退出后 drain 也必须按剩余额度读取；
- 超限立即 kill container。
```

伪代码：

```python
proc = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=False,
)

stdout = read_stream_bounded(proc.stdout, max_stdout)
stderr = read_stream_bounded(proc.stderr, max_stderr)
```

### 必须测试

```text
test_stdout_limit_enforced_in_bytes
test_stderr_limit_enforced_in_bytes
test_tail_output_after_exit_still_bounded
```

---

## P1-C：文档状态仍不准确

README 当前标题仍是：

```text
SeekFlow v0.3.7 — Level 2 Semi-production
```

并且 Security Status 仍写 untrusted third-party tools / arbitrary MCP servers 不支持。([GitHub][9])

这与当前代码尝试实现 Lv3 candidate 的状态不一致。

### 修复建议

README 必须改成：

```text
SeekFlow v0.3.7 — Level 3 Candidate
```

但不要夸大：

```text
Status:
- Level 2 semi-production baseline: complete.
- Level 3 candidate: experimental.
- Full Level 3 production-ready: not yet unless egress sidecar, real signature verification, durable audit required mode, MCP gateway registry injection are enabled.
```

---

# 3. Claude Code 最小落地方案

## Phase 1：补齐 supply-chain 安全

```text
修改：
- src/seekflow/tools/manifest.py
- src/seekflow/tools/manifest_verify.py
- src/seekflow/tools/trust_store.py
- src/seekflow/cli.py
- pyproject.toml

目标：
- Ed25519 真实验签；
- strict external manifest 必须签名；
- package_digest 校验实际 bytes；
- OCI image 必须 digest pin；
- CLI install strict 默认开启。
```

验收：

```bash
pytest tests/tools/test_manifest_signature.py
pytest tests/cli/test_tool_install_security.py
```

---

## Phase 2：实现真实 egress sidecar

```text
修改：
- src/seekflow/network/egress.py
- src/seekflow/network/sidecar.py
- src/seekflow/tools/external_runner.py
- src/seekflow/tools/executor.py

目标：
- manifest.network.allowed_domains 非空时启动 sidecar；
- 工具容器通过 proxy 访问网络；
- block private / metadata / redirect-to-private；
- egress audit 写 durable audit。
```

验收：

```bash
pytest tests/network/test_egress_sidecar_integration.py
pytest tests/tools/test_external_runner_network.py
```

---

## Phase 3：MCPGateway 去全局状态

```text
修改：
- src/seekflow/mcp/runner.py
- src/seekflow/mcp/gateway.py
- src/seekflow/tools/executor.py

目标：
- MCPGatewayRegistry 显式注入；
- 不依赖 _gateway_registry 全局变量；
- 多 executor 隔离；
- MCP output schema validation；
- 每次执行前 verify_frozen。
```

验收：

```bash
pytest tests/mcp/test_mcp_gateway_runner.py
pytest tests/mcp/test_mcp_gateway_isolation.py
```

---

## Phase 4：Durable audit 生产级化

```text
修改：
- src/seekflow/tools/executor.py
- src/seekflow/audit/model.py
- src/seekflow/audit/store.py

目标：
- 所有失败路径写 audit；
- secret_refs / egress summary 写入；
- audit_required=True 时写失败阻断执行；
- 不吞异常，只在非 required 模式 warning。
```

验收：

```bash
pytest tests/audit/test_executor_durable_audit.py
pytest tests/audit/test_audit_failure_modes.py
```

---

## Phase 5：ExternalToolRunner 输出边界硬化

```text
修改：
- src/seekflow/tools/external_runner.py

目标：
- text=False；
- bytes-level bounded read；
- drain 阶段仍 bounded；
- stdout/stderr 分别限额；
- 超限 kill + rm。
```

验收：

```bash
pytest tests/tools/test_external_runner_output_bounds.py
```

---

## Phase 6：文档与 release gate

```text
修改：
- README.md
- docs/security/levels.md
- docs/production-readiness.md
- .github/workflows/ci.yml
- tests/test_version_consistency.py

目标：
- README 改为 Level 3 Candidate；
- 明确不是 Full Lv3；
- CI 必跑：
  - pytest
  - ruff
  - mypy core
  - check_xfail_policy.py --strict-core
  - manifest signature tests
  - external runner tests
  - MCP gateway tests
  - egress sidecar tests
  - durable audit tests
```

---

# 4. 修复后评级标准

## 达到 Lv3 candidate 的最低要求

```text
- external manifest 工具 func=None 可执行；
- 非 local 工具只能 external_container；
- MCP 工具只能 mcp_gateway；
- MCP 不依赖 wrapper callable；
- MCP gateway registry 显式注入；
- egress sidecar 真正代理 HTTP/HTTPS；
- external tool 默认无网络；
- secret broker 默认无 env provider；
- manifest strict 模式真实验签；
- package_digest 校验实际内容；
- durable audit 覆盖成功和失败路径；
- README / pyproject / docs / CI 状态一致。
```

## 仍不能称 Full Lv3 的情况

```text
- sidecar 只是 mock 或返回 501；
- signature verification 仍是 placeholder；
- audit 写入失败被静默吞掉；
- MCP 使用全局 registry；
- tag-only image 可执行；
- stdout/stderr 仍存在无界读取；
- README 仍写 Level 2；
- GitHub release / SBOM / provenance 缺失。
```

---

# 5. 最终判断

当前审计报告的方向是正确的：**Lv3 的关键不是继续加固 ProcessRunner，而是建立 manifest + external runner + MCP gateway + egress broker + secret broker + durable audit + supply-chain verification 的零信任工具运行时。**

但当前代码还不能叫完整 Lv3。更准确评级是：

```text
当前：Level 3 candidate early / Lv2+ with partial Lv3 wiring
修完上述 Phase 1–6：Level 3 candidate
再补 release provenance、默认强 audit、完整 sidecar hardening：接近 Full Level 3
```

[1]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/types.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/policy_compiler.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/policy_linter.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/planner.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/executor.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/external_runner.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/manifest_verify.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/mcp/runner.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/README.md "raw.githubusercontent.com"
