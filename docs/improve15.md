一、二次审核结论

作者报告的总体方向是正确的：SeekFlow 确实在尝试从 Lv2：可信注册工具 + runner 隔离，升级到 Lv3：非可信第三方工具 / MCP / 插件式工具的零信任运行时。报告中新增的 ToolManifest、PolicyCompiler、ExternalToolRunner、MCPGateway、EgressGateway、SecretBroker、DurableAuditStore 等模块，也确实对应 Lv3 所需的关键组件 。

但结合当前实际代码复核后，我的最终判断是：

当前状态：Lv2+ / Lv3 skeleton / Lv3 candidate early
不能认定：完整 Lv3 production-ready
主要问题：Lv3 模块已经出现，但全链路没有形成强制、不可绕过、可审计的闭环。

也就是说，框架已经有了 Lv3 的骨架，但还不是 Lv3 的真实安全语义。
三、当前最核心问题
P0-1：外部 manifest 工具无法真正执行
现状

register_from_manifest() 注册的是：

ToolDefinition(
    func=None,
    source=manifest.source,
    metadata={"_manifest_data": ...},
)

这是正确的，因为第三方工具不能是宿主 Python callable。

但 ToolExecutor.execute() 在 planning 前直接拒绝：

if tool_def.func is None:
    return ToolExecutionResult(error="Tool has no callable function")

然后后面才出现 external_container 执行分支。

影响
Manifest → Registry → Planner → ExternalToolRunner 链路实际断裂。
外部工具可以注册，但不能执行。
Lv3 主路径不可用。
修复方案

把 func is None 检查移动到 planning 之后：

plan = plan_execution(tool_def, effective_timeout)
runner = self._runner_for(plan, tool_def)

if plan.runner != "external_container" and tool_def.func is None:
    return ToolExecutionResult(
        tool_call_id=tool_call.id,
        name=tool_call.name,
        arguments=arguments,
        ok=False,
        error=f"Tool '{tool_call.name}' has no callable function",
        elapsed_ms=elapsed,
    )

并确保 external path：

if plan.runner == "external_container":
    manifest_data = (tool_def.metadata or {}).get("_manifest_data")
    if not manifest_data:
        raise RunnerUnavailableError("External tool requires _manifest_data")

    manifest = ToolManifest.model_validate(manifest_data)
    run_result = runner.run(
        manifest,
        arguments,
        plan.timeout_s,
        max_output_bytes=policy.max_output_bytes if policy else 100_000,
        egress_profile=...,
        fs_profile=...,
        env_profile=...,
    )
else:
    run_result = runner.run(tool_def.func, arguments, ...)
必须新增测试
tests/tools/test_external_tool_executor_integration.py

- test_manifest_tool_with_func_none_executes_via_external_runner
- test_external_tool_missing_manifest_data_fails_closed
- test_external_tool_never_calls_python_callable
- test_local_tool_with_func_none_still_fails
P0-2：RunnerKind 类型缺 external_container
现状

types.py 里：

RunnerKind = Literal["auto", "in_process", "process", "container"]

没有 external_container。

但 planner 已经返回 external_container，executor 也有 external 分支。

影响
类型模型与运行时不一致。
PolicyCompiler 不能合法返回 external_container。
mypy / Pydantic / 文档语义都不一致。
修复
RunnerKind = Literal[
    "auto",
    "in_process",
    "process",
    "container",
    "external_container",
]

并更新所有注释：

# "container" = trusted codegen tool + ContainerRunner
# "external_container" = untrusted external manifest tool + ExternalToolRunner
P0-3：PolicyCompiler 仍把非 local 编译为 container
现状

policy_compiler.py 注释说非本地工具必须走 ExternalToolRunner，但实际：

runner = "container"

影响

这会把两种完全不同的语义混在一起：

container:
  当前代表 ContainerRunner
  需要 trusted=True + container_codegen_trusted=True
  会调用宿主 Python func 生成 code

external_container:
  应代表 ExternalToolRunner
  不允许宿主 Python callable
  只接收 manifest + JSON input

非 local 工具绝不能进入普通 container runner。

修复
if is_local:
    runner: RunnerKind = "auto"
else:
    runner: RunnerKind = "external_container"

同时修改 docstring：

source != local → runner="external_container"
必须新增测试
test_compile_policy_external_source_runner_external_container
test_compile_policy_external_source_never_trusted
test_compile_policy_external_source_trusted_output_false
P0-4：PolicyLinter 规则 L001 不够强
现状

L001 只禁止外部工具使用：

{"in_process", "process"}

但允许 container。

问题

对 Lv3 来说，外部工具必须是：

external_container

不能是普通 container。因为普通 container 在 SeekFlow 当前语义里是 trusted codegen container runner，不是第三方工具运行器。

修复
def _rule_no_local_runner_for_external(policy, source):
    if source in {"registry", "mcp", "oci", "wasm"}:
        if policy.runner != "external_container":
            return [LintIssue(
                severity="error",
                code="L001",
                message=(
                    f"source={source} requires runner=external_container; "
                    f"got runner={policy.runner}"
                ),
                path="$.runner",
            )]
测试
test_l001_external_container_required
test_l001_external_container_passes
test_l001_external_container_rejects_plain_container
四、MCPGateway 仍未达到 Lv3
P0-5：MCPGateway 仍注册 Python wrapper
现状

MCPGateway.connect_and_freeze() 注册工具时：

wrapper = self._make_wrapper(ft.name)

ToolDefinition(
    func=wrapper,
    source=cfg.name,
    policy=policy,
)

问题

这仍然是 Lv2 模式：

MCP tool → Python wrapper → ToolExecutor → ProcessRunner/InProcessRunner

而 Lv3 应该是：

MCP tool → MCPGatewayRunner / External MCP channel → no local callable

MCP server 是非可信外部实体时，不应伪装成本地 Python callable。

修复方案 A：新增 MCPGatewayRunner

新增文件：

src/seekflow/mcp/runner.py
class MCPGatewayRunner:
    name = "mcp_gateway"

    def __init__(self, gateway_registry: MCPGatewayRegistry):
        self.gateway_registry = gateway_registry

    def run(
        self,
        tool_def: ToolDefinition,
        arguments: dict,
        timeout_s: float,
        *,
        max_output_bytes: int = 100_000,
    ) -> ToolRunResult:
        gateway_id = tool_def.metadata["_mcp_gateway_id"]
        mcp_tool_name = tool_def.metadata["_mcp_tool_name"]
        gateway = self.gateway_registry.get(gateway_id)

        result = gateway.execute(
            ToolCall(
                id=str(uuid.uuid4()),
                name=mcp_tool_name,
                arguments=arguments,
            )
        )

        return ToolRunResult(
            ok=result.ok,
            result=result.result,
            error=result.error,
            runner_name=self.name,
            elapsed_ms=result.elapsed_ms,
        )

然后 MCPGateway.connect_and_freeze() 改为：

td = ToolDefinition(
    name=full_name,
    description=ft.description,
    parameters=ft.schema,
    func=None,
    source="mcp",
    metadata={
        "_mcp_gateway_id": cfg.name,
        "_mcp_tool_name": ft.name,
        "_mcp_schema_hash": ft.schema_hash,
    },
    policy=policy,
)

并让 planner：

if tool_def.source == "mcp":
    return ExecutionPlan(runner="mcp_gateway", ...)

或者也可以复用 external_container，但建议单独 mcp_gateway，因为 MCP 是长期 server session，不是每次 fresh container。

修复方案 B：短期最小修复

如果不想新增 runner，至少必须：

1. MCP wrapper 不进入 InProcessRunner。
2. MCP policy.runner 强制 process 或 external_container。
3. wrapper 内部执行前必须 verify_frozen。
4. wrapper 输出必须 bounded + schema validate + wrap_untrusted。

但这只能算 Lv2.5，不是完整 Lv3。

P0-6：MCP env_allowlist 仍不是 fail-closed
现状

如果 env_allowlist 为空但 env 不为空，代码 warning 后仍传 env。

修复
elif self.env:
    raise ValueError(
        f"MCP server '{self.name}' provided env without env_allowlist. "
        "Lv3 requires explicit env_allowlist or SecretBroker refs."
    )
测试
test_mcp_env_without_allowlist_denied
test_mcp_env_with_allowlist_passes_only_allowed_keys
test_mcp_os_environ_not_inherited_by_default
五、ExternalToolRunner 还不是完整 Lv3 sandbox
P0-7：ExternalToolRunner 没有强制 image digest pin
现状

代码允许：

image = sandbox.image or "python:3.11-slim"

只有 sandbox.image_digest 存在时才拼 digest。

问题

第三方工具不能使用 tag-only image：

python:3.11-slim
my-tool:latest
vendor/tool:v1

这些都可能被替换。

修复
if manifest.source != "local":
    if not sandbox.image_digest:
        return ToolRunResult(
            ok=False,
            error="External tools require sandbox.image_digest pinned by sha256",
            runner_name=self.name,
        )

并校验格式：

if not sandbox.image_digest.startswith("sha256:"):
    raise ValueError("image_digest must start with sha256:")
测试
test_external_tool_rejects_unpinned_image
test_external_tool_accepts_sha256_digest_image
P0-8：stdout/stderr 读取是 unbounded，存在 DoS 风险
现状

ExternalToolRunner 使用：

stdout, stderr = proc.communicate(timeout=...)

然后才：

serialize_bounded(stdout_str, max_output_bytes)

问题

这不是 bounded output。因为 stdout/stderr 已经完整进入父进程内存后才裁剪。恶意工具输出 1GB 会先打爆宿主内存。

修复

实现 bounded stream reader：

def communicate_bounded(proc, timeout_s, max_stdout, max_stderr):
    stdout_buf = bytearray()
    stderr_buf = bytearray()

    deadline = time.monotonic() + timeout_s

    while proc.poll() is None:
        if time.monotonic() > deadline:
            raise TimeoutExpired(...)

        read available stdout/stderr chunks

        if len(stdout_buf) > max_stdout:
            raise OutputLimitExceeded("stdout exceeded max_output_bytes")

        if len(stderr_buf) > max_stderr:
            raise OutputLimitExceeded("stderr exceeded max_stderr_bytes")

短期可用 selectors 实现，长期可以改 asyncio subprocess。

测试
test_external_runner_kills_on_stdout_over_limit
test_external_runner_kills_on_stderr_over_limit
test_external_runner_does_not_hold_unbounded_output_in_memory
P0-9：ExternalToolRunner 没有接入 SecretBroker
现状

ExternalToolRunner.run() 有 env_profile 参数，但没有真正注入 env；SecretBroker 是孤立模块。

修复

给 ToolExecutor.__init__ 增加：

secret_broker: SecretBroker | None = None

执行 external tool 前：

secret_env = {}
if self.secret_broker:
    refs = [
        SecretRef(name=s, scope="tool")
        for s in manifest.env.secrets
    ]
    secret_env = self.secret_broker.resolve_for_tool(
        manifest.name,
        refs,
        run_id=context.run_id if context else "",
    )

传入 runner：

EnvProfile(allowlist=secret_env)

ExternalToolRunner 加：

if env_profile:
    for key, value in env_profile.allowlist.items():
        cmd.extend(["-e", f"{key}={value}"])

同时禁止任何默认 env 继承。

测试
test_external_runner_does_not_inherit_host_env
test_external_runner_injects_only_secretbroker_resolved_refs
test_secret_value_not_in_audit
P0-10：SecretBroker 的 EnvProvider 不是 allowlist-based
现状

_EnvProvider.resolve() 直接：

return os.environ.get(ref.name)

问题

这意味着只要 manifest 猜到环境变量名，就可能拿到 host secret。

修复
class EnvProvider:
    def __init__(self, allowed_names: set[str]):
        self.allowed_names = allowed_names

    def resolve(self, ref: SecretRef) -> str | None:
        if ref.name not in self.allowed_names:
            return None
        return os.environ.get(ref.name)

默认：

SecretBroker()

不应注册 env provider，或者注册空 allowlist env provider。

self._providers = {
    "memory": _MemoryProvider(),
}

如果用户需要 env：

broker.register_provider("env", EnvProvider({"GITHUB_TOKEN"}))
六、EgressGateway 仍是 validator/mock，不是强边界
P0-11：EgressGateway 没有 sidecar
现状

EgressGateway docstring 明确写着：

In Phase E, this is a validation/mock layer.
Full sidecar implementation ... runs as a separate process.

问题

Lv3 不能依赖工具自愿调用 check_request()。必须强制网络只能经过 gateway。

ExternalToolRunner 目前直接：

--network sandbox.network

默认是否为 none 取决于 manifest sandbox，而不是强制策略。

修复目标
外部工具容器默认 --network none。
如果 manifest 声明需要 network：
  启动 egress sidecar；
  工具容器只能访问 sidecar；
  sidecar 执行 DNS/IP/domain/method/body/response 校验；
  egress audit 写入 DurableAuditStore。
最小可落地实现

新增：

src/seekflow/network/sidecar.py

接口：

class EgressSidecar:
    def start(
        self,
        policy: EgressPolicy,
        tool_name: str,
        run_id: str,
    ) -> EgressSidecarHandle:
        ...

    def stop(self, handle: EgressSidecarHandle) -> None:
        ...

EgressSidecarHandle：

@dataclass
class EgressSidecarHandle:
    proxy_url: str
    docker_network: str
    audit_entries: list[EgressAuditEntry]

ExternalToolRunner：

if manifest.network.allowed_domains:
    sidecar = self.egress_sidecar.start(policy, manifest.name, run_id)
    cmd.extend(["--network", sidecar.docker_network])
    cmd.extend(["-e", f"HTTP_PROXY={sidecar.proxy_url}"])
    cmd.extend(["-e", f"HTTPS_PROXY={sidecar.proxy_url}"])
else:
    cmd.extend(["--network", "none"])

短期可以实现为本地 HTTP proxy，只支持 HTTP/HTTPS request，不支持 CONNECT 任意隧道。

测试
test_external_network_none_by_default
test_external_tool_cannot_direct_connect
test_external_tool_network_requires_egress_sidecar
test_egress_blocks_private_ip
test_egress_blocks_metadata_ip
test_egress_blocks_redirect_to_private_ip
test_egress_records_audit
七、DurableAuditStore 没接入主执行链路
P0-12：ToolExecutor 仍只写内存 audit_trail
现状

DurableAuditStore 存在，支持 JSONL/SQLite/hash chain。
但 ToolExecutor 没有 audit_store 参数，也没有写入 durable audit；只写内存 ToolAuditRecord。

修复

ToolExecutor.__init__ 增加：

audit_store: JSONLAuditStore | SQLiteAuditStore | None = None

统一新增：

def _record_durable_audit(...):
    if self.audit_store is None:
        return

    event = AuditEvent(
        event_id=str(uuid.uuid4()),
        ts=datetime.now(timezone.utc),
        run_id=getattr(self.context, "run_id", "") if self.context else "",
        step=getattr(self.context, "step", 0) if self.context else 0,
        event_type="tool_execution",
        tool_name=tool_def.name,
        tool_version=metadata.get("manifest_version"),
        manifest_digest=metadata.get("manifest_digest"),
        policy_digest=compute_policy_digest(tool_def.policy),
        input_hash=hash_json(arguments),
        output_hash=hash_json(result) if result is not None else None,
        runner=runner_name,
        sandbox_image_digest=...,
        ok=ok,
        error=error,
        elapsed_ms=latency_ms,
        egress=...,
        secret_refs=...,
    )

    self.audit_store.append(event)

必须在这些路径写 audit：

- tool not found
- no policy denied
- policy denied
- approval denied
- schema validation failed
- runner unavailable
- runner timeout/killed
- successful execution
- external output schema invalid
测试
test_durable_audit_written_on_success
test_durable_audit_written_on_policy_denial
test_durable_audit_written_on_runner_unavailable
test_durable_audit_contains_policy_digest
test_durable_audit_contains_manifest_digest_for_external_tool
test_durable_audit_chain_verifies
test_durable_audit_tamper_detected
test_durable_audit_does_not_contain_secret_value
八、Manifest verify 仍是 supply-chain placeholder
P1-1：签名验证未真正实现
现状

manifest_verify.py 明确写了：

signature verification is a placeholder

签名存在时严格模式也只是检查 signing_key_id，没有真实 cryptographic verification。

修复

引入 Ed25519：

dependency:
cryptography>=42

新增：

src/seekflow/tools/trust_store.py
class TrustStore:
    def get_public_key(self, key_id: str) -> bytes:
        ...

签名验证：

def verify_signature(manifest, trust_store, strict):
    if strict and manifest.source != "local":
        if not manifest.signature:
            raise ManifestVerificationError("signature required")
        if not manifest.signing_key_id:
            raise ManifestVerificationError("signing_key_id required")

    public_key = trust_store.get_public_key(manifest.signing_key_id)

    payload = canonical_manifest_without_signature(manifest)
    signature = base64.b64decode(manifest.signature)

    Ed25519PublicKey.from_public_bytes(public_key).verify(
        signature,
        payload,
    )
测试
test_strict_external_manifest_requires_signature
test_valid_ed25519_signature_passes
test_invalid_signature_fails
test_unknown_signing_key_fails
test_manifest_tamper_after_signing_fails
P1-2：package_digest 没有在 CLI install 时强制校验实际包

verify_digest() 支持 actual_package_bytes，但 CLI install 如果没有读取实际 package/image，就只能校验 hash 格式。

修复

Manifest 必须提供以下之一：

package_path
package_url
oci_image + image_digest
wasm_path

CLI install：

package_bytes = load_package_bytes(manifest)
verify_manifest(
    manifest,
    package_bytes=package_bytes,
    strict=strict,
    trust_store=trust_store,
)

OCI image 的 digest 校验不要下载整个镜像，直接检查：

image reference 必须是 name@sha256:...
九、文档与 release gate 必须修
P1-3：README 严重陈旧

README 仍写 v0.2.5-dev、PyPI stable 0.1.0、production not recommended until v0.2.5。

应改成：

SeekFlow v0.3.7
Status: Level 2+ / Level 3 candidate
Not yet full Level 3 production-ready

必须明确：

Supported:
- trusted local tools under ToolPolicy
- manifest-based external tool registration
- experimental ExternalToolRunner
- MCPGateway experimental

Not yet full:
- Egress sidecar not production-complete
- manifest signature verification pending if not implemented
- DurableAudit must be configured

不要宣传“Full Lv3”，除非上面 P0 都修完。

P1-4：pyproject 描述仍是 Lv2

pyproject.toml 版本是 0.3.7，但 description 仍是 Level 2 semi-production candidate。

建议：

description = "DeepSeek-native secure tool runtime — Level 2+ / Level 3 candidate with manifest-based external tools."
P1-5：CI strict-core 不能 continue-on-error

报告称 CI 加了 --strict-core，但如果仍是 continue-on-error，不能算 release gate 。

修复：

- name: Check xfail policy (strict-core)
  run: python scripts/check_xfail_policy.py --strict-core

禁止：

continue-on-error: true
十、Claude Code 执行计划

下面这部分可以直接给 Claude Code。

Phase 1：打通 ExternalToolRunner 主链路
修改文件
src/seekflow/types.py
src/seekflow/tools/policy_compiler.py
src/seekflow/tools/policy_linter.py
src/seekflow/tools/executor.py
tests/tools/test_external_tool_executor_integration.py
任务
1. RunnerKind 增加 external_container。
2. policy_compiler 非 local manifest 编译为 runner="external_container"。
3. policy_linter L001 强制非 local source 只能 external_container。
4. executor 把 func=None 检查移到 planning 之后。
5. executor 允许 external_container + func=None。
6. external_container 必须从 metadata["_manifest_data"] 构造 ToolManifest。
7. external_container 禁止 retry，除非 manifest.idempotent=True。
验收
pytest tests/tools/test_external_tool_executor_integration.py
pytest tests/tools/test_policy_linter.py
pytest tests/tools/test_manifest.py
Phase 2：修 MCPGateway 为真实隔离执行路径
修改文件
src/seekflow/mcp/config.py
src/seekflow/mcp/gateway.py
src/seekflow/mcp/runner.py
src/seekflow/tools/planner.py
src/seekflow/tools/executor.py
tests/mcp/test_mcp_gateway_runner.py
任务
1. MCP config env without env_allowlist 改为 raise，不是 warning。
2. MCPGateway 注册 ToolDefinition 时 func=None。
3. metadata 写入：
   - _mcp_gateway_id
   - _mcp_tool_name
   - _mcp_schema_hash
4. 新增 MCPGatewayRunner。
5. planner 对 source="mcp" 返回 runner="mcp_gateway"。
6. executor _runner_for 支持 mcp_gateway。
7. MCPGatewayRunner 每次执行前调用 verify_frozen 或按配置周期校验。
8. MCP 输出做 max_output_bytes bound + output schema validation + untrusted wrapping。
验收
test_mcp_tool_registered_without_callable
test_mcp_tool_executes_through_gateway_runner
test_mcp_env_without_allowlist_denied
test_mcp_mutation_detected_before_execution
test_mcp_output_bounded
Phase 3：ExternalToolRunner 沙箱硬化
修改文件
src/seekflow/tools/external_runner.py
tests/tools/test_external_runner_hardening.py
任务
1. external source 强制 image_digest。
2. 禁止 tag-only image。
3. 默认 --network none。
4. 不允许 manifest.sandbox.network 直接控制 Docker network。
5. stdout/stderr 改为 bounded stream read。
6. stdout/stderr 超限立即 kill + rm。
7. 每次执行必须 fresh container。
8. finally 中确保 docker rm -f。
验收
test_external_rejects_unpinned_image
test_external_network_none_default
test_external_stdout_limit_kills_container
test_external_stderr_limit_kills_container
test_external_container_cleanup_on_timeout
Phase 4：SecretBroker 接入
修改文件
src/seekflow/secrets/broker.py
src/seekflow/tools/executor.py
src/seekflow/tools/external_runner.py
tests/secrets/test_secret_broker_integration.py
任务
1. SecretBroker 默认不注册 os.environ provider。
2. EnvProvider 必须显式 allowlist。
3. ToolExecutor 增加 secret_broker 参数。
4. external tool 执行前从 manifest.env.secrets 解析 SecretRef。
5. 只把解析出的 secret 注入 docker -e。
6. secret audit 不能包含 value。
7. secret_refs 写入 durable audit。
验收
test_no_ambient_env
test_env_provider_requires_allowlist
test_secret_injected_only_when_declared
test_secret_value_not_in_result_or_audit
Phase 5：真实 Egress sidecar
修改文件
src/seekflow/network/egress.py
src/seekflow/network/sidecar.py
src/seekflow/tools/external_runner.py
tests/network/test_egress_sidecar.py
任务
1. ExternalToolRunner 默认 --network none。
2. 如果 manifest.network.allowed_domains 非空，启动 sidecar。
3. 工具容器只能通过 HTTP_PROXY/HTTPS_PROXY 访问 sidecar。
4. sidecar 执行：
   - scheme check
   - method check
   - port check
   - allowed domain check
   - DNS resolve
   - private/reserved IP block
   - redirect recheck
   - request/response size limit
5. sidecar audit_entries 返回给 executor。
6. egress audit 写入 DurableAuditStore。
验收
test_direct_network_unavailable
test_allowed_domain_via_sidecar
test_block_private_ip
test_block_metadata_ip
test_block_redirect_to_private_ip
test_egress_audit_recorded
Phase 6：DurableAuditStore 接入 executor
修改文件
src/seekflow/tools/executor.py
src/seekflow/audit/model.py
src/seekflow/audit/store.py
tests/audit/test_executor_durable_audit.py
任务
1. ToolExecutor 增加 audit_store 参数。
2. 所有执行结果都写 durable audit。
3. AuditEvent 包含：
   - tool_name
   - tool_version
   - manifest_digest
   - policy_digest
   - runner
   - input_hash
   - output_hash
   - sandbox_image_digest
   - egress audit summary
   - secret refs
   - ok/error/elapsed_ms
4. hash chain verify 必须通过。
5. secret value 不得出现在 payload_json。
验收
test_audit_written_on_success
test_audit_written_on_denial
test_audit_written_on_external_tool
test_audit_contains_manifest_policy_digest
test_audit_chain_detects_tamper
Phase 7：Supply-chain 安全补齐
修改文件
src/seekflow/tools/manifest.py
src/seekflow/tools/manifest_verify.py
src/seekflow/tools/trust_store.py
src/seekflow/cli.py
tests/tools/test_manifest_signature.py
tests/cli/test_tool_install_security.py
任务
1. manifest 增加 package_path / package_url / oci_image。
2. strict external manifest 必须签名。
3. Ed25519 signature verification。
4. signing_key_id 必须来自 trust store。
5. package_digest 必须校验实际 package bytes。
6. OCI image 必须 name@sha256。
7. CLI install strict 默认开启。
验收
test_unsigned_external_manifest_rejected
test_invalid_signature_rejected
test_valid_signature_accepted
test_package_digest_mismatch_rejected
test_oci_tag_only_rejected
Phase 8：文档与 release gate
修改文件
README.md
pyproject.toml
docs/security/levels.md
docs/production-readiness.md
.github/workflows/ci.yml
tests/test_version_consistency.py
任务
1. README 改为 v0.3.7。
2. 明确状态：Level 3 candidate，不是 full Lv3 production-ready。
3. pyproject description 与 README 一致。
4. ci strict-core 去掉 continue-on-error。
5. release checklist 增加：
   - pytest
   - ruff
   - mypy core
   - check_xfail_policy --strict-core
   - external runner integration
   - MCP gateway runner
   - egress sidecar
   - durable audit
   - manifest signature
6. 增加 version consistency test。
十一、修复后评级标准

Claude Code 完成后，按下面矩阵验收。

可以称为 Lv3 candidate 的最低标准
- 外部 manifest 工具可执行，且 func=None。
- 非 local 工具永远不进入 InProcessRunner / ProcessRunner / ContainerRunner。
- PolicyCompiler 输出 external_container。
- PolicyLinter 阻止外部工具使用非 external_container。
- MCP 工具不注册 Python wrapper。
- MCP env 无 allowlist 直接拒绝。
- ExternalToolRunner 强制 image digest。
- ExternalToolRunner bounded stdout/stderr。
- SecretBroker 接入 external runner。
- Egress sidecar 真实生效。
- DurableAuditStore 接入 executor。
- manifest strict 模式真实验签。
- CI strict-core 为硬 gate。
仍不能称 full Lv3 production 的情况
- EgressGateway 只是 check_request mock。
- SecretBroker 不接入 runner。
- AuditStore 只是 CLI 可用但 executor 不写。
- MCP 仍注册 wrapper func。
- ExternalToolRunner 允许 tag-only image。
- stdout/stderr 仍 communicate 后再裁剪。
- manifest signature 是 placeholder。
十二、最终判断

我二次审核后的最终结论是：

SeekFlow 当前已经具备 Lv3 架构雏形；
但不是完整 Lv3。
最大缺陷不是模块缺失，而是“模块未形成强制闭环”。

最重要的修复优先级是：

1. 修 ExternalToolRunner 主链路；
2. 修 PolicyCompiler / RunnerKind / Linter 语义；
3. MCPGateway 去 wrapper callable；
4. ExternalToolRunner 做真实 sandbox hardening；
5. SecretBroker / EgressGateway / DurableAuditStore 接入 executor；
6. manifest 真实签名与 digest 校验；
7. 文档与 CI release gate 同步。

完成这些后，可以比较稳妥地称为：

Level 3 candidate / early production-grade untrusted tool runtime

但要称为：

Full Level 3 production-ready

还需要真实 egress sidecar、真实签名验证、durable audit 默认开启、MCP 无 wrapper 执行路径，以及完整 release gate 全部落地。