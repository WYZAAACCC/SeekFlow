下面是我对**上一轮审计方向**与**当前公开代码状态**的复核结论。重点先说：**上一轮“Lv2→Lv3”的大方向是正确的，但它低估了当前公开 main 的一致性问题；在做 Lv3 前，必须先把 Lv2 代码/文档/测试基线重新钉死。**

我核对的基线包括你上传的上一轮总结 、README、`docs/security/levels.md`、`ToolExecutor`、`planner`、`runners`、`ContainerRunner`、`PolicyEngine`、`MCP`、`sandbox`、`security/http.py`、`validation.py`、`pyproject.toml` 和 xfail 检查脚本。

---

# 0. 最终判断

## 审计报告方向：总体正确

上一轮报告提出的 Level 3 方向基本正确：

1. **第三方工具不能进入宿主 Python 进程。**
2. **MCP 不能仅作为“工具注册器”，必须变成零信任网关。**
3. **需要 tool manifest、签名、digest pinning、egress gateway、secret broker、durable audit log。**
4. **ProcessRunner 不能被包装成安全沙箱。**
5. **ContainerRunner 当前只适合 trusted code-builder，不适合 arbitrary third-party tool。**

这些判断与当前官方文档一致：SeekFlow 文档明确把 Level 3 定义为“不支持”的 untrusted third-party tools / untrusted MCP / plugin market，并写明 Level 3 需要 tool signing、MCP sandboxing、plugin isolation、dynamic policy。([GitHub][1])

## 但当前公开 main 还不能直接进入 Lv3 开发

当前公开 main 的状态不是上一轮总结里提到的 v0.3.7，而是 **v0.3.6 Level 2 Semi-production Candidate**。README 也写明当前 main 是 Level 2 semi-production，且 untrusted third-party tools 和 arbitrary MCP servers 不支持。([GitHub][2])

更关键的是：我发现当前公开代码存在一个**非常严重的版本/类型模型不一致问题**：

`executor.py` 和 `planner.py` 使用了 `policy.idempotent`、`policy.trusted`、`policy.trusted_output`、`policy.allow_in_process_fallback`、`policy.container_codegen_trusted`、`policy.runner` 等字段；但当前 `types.py` 中 `ToolPolicy` 公开字段只包含 capabilities、risk、timeout、limits、parallel_safe、requires_approval、allowed_domains、workspace_root、path_params、url_params，并没有这些字段。([GitHub][3])

这意味着只要执行到相关路径，可能出现：

```text
AttributeError: 'ToolPolicy' object has no attribute 'idempotent'
AttributeError: 'ToolPolicy' object has no attribute 'runner'
AttributeError: 'ToolPolicy' object has no attribute 'trusted'
```

所以，**Claude Code 的第一阶段不是直接做 Lv3，而是先修复 Lv2 public main 的可运行一致性。**

---

# 1. 当前代码的真实安全边界

## 已经做得比较好的部分

### ToolExecutor 已经不是直接裸执行

`ToolExecutor` 的执行链路已经是：解析参数、repair、no-policy gate、PolicyEngine 授权、input limit、类型 coercion、schema validation、cache、runner 执行、untrusted output wrapping、redaction、audit。代码注释也明确写了“NEVER call tool_def.func directly”。([GitHub][3])

### runner 选择方向正确

`planner.py` 维护了 runner isolation order，并且显式 runner override 只能增强不能减弱隔离；`code_exec/destructive` 要求 container，`network/write` 要求 process，trusted read 才可能 in-process。([GitHub][4])

### ProcessRunner 是 hard-timeout isolation，不是 sandbox

`ProcessRunner` 使用 multiprocessing spawn，timeout 后 terminate → kill，并在 child 进程里做 bounded output。这个适合 Lv2 的“可信注册工具 + 防阻塞/防崩溃”，但不能抵御恶意工具访问 host env、filesystem、network。文档也明确承认这一点。([GitHub][5])

### ContainerRunner 的边界写得很清楚

`ContainerRunner` 当前会先在宿主进程调用 tool function，生成 `CodeExecutionRequest` 或 code string，再交给 container sandbox 执行。代码和文档都明确说：它只适合 `trusted=True + container_codegen_trusted=True` 的安全 code-builder，不适合任意工具实现。([GitHub][6])

### PolicyEngine 的 Lv2 gate 基本正确

`PolicyEngine.authorize()` 会拒绝 no-policy tool；检查 dangerous tools、risk ceiling、capability、code sandbox、filesystem workspace_root、network allowed_domains 和 SSRF validation。([GitHub][7])

### SSRF 防护作为 Lv2 足够，作为 Lv3 不够

`security/http.py` 做了 scheme、userinfo、hostname、port、allowed_domains、DNS 解析、private/reserved IP 阻断、redirect 逐跳校验和 response size limit。([GitHub][8])
但这仍然是 library-level HTTP client，不是强制 egress boundary。恶意第三方工具可以不用这个 client，直接 `socket`、`requests`、`curl`、DNS over HTTPS 或自带代理。

---

# 2. 需要先修的 P0：恢复 Lv2 代码一致性

把下面这组任务原样给 Claude Code。

## P0-1：修复 `ToolPolicy` 字段缺失

文件：

```text
src/seekflow/types.py
```

当前 `ToolPolicy` 必须补齐 executor/planner 已经依赖的字段：

```python
RunnerName = Literal["auto", "in_process", "process", "container"]

class ToolPolicy(BaseModel):
    capabilities: set[str] = Field(default_factory=set)
    risk: RiskLevel = "read"

    runner: RunnerName = "auto"
    trusted: bool = False
    trusted_output: bool = False
    idempotent: bool = False
    allow_in_process_fallback: bool = False
    container_codegen_trusted: bool = False

    timeout_s: float = 30.0
    max_input_bytes: int = 1_000_000
    max_output_bytes: int = 100_000

    parallel_safe: bool = False
    requires_approval: bool = False

    allowed_domains: set[str] = Field(default_factory=set)
    workspace_root: Path | None = None
    path_params: frozenset[str] = Field(default_factory=frozenset)
    url_params: frozenset[str] = Field(default_factory=frozenset)
```

并增加 Pydantic 校验：

```python
@model_validator(mode="after")
def validate_security_invariants(self):
    if self.trusted_output and not self.trusted:
        raise ValueError("trusted_output=True requires trusted=True")

    if self.allow_in_process_fallback and not (
        self.trusted and self.risk == "read"
    ):
        raise ValueError("allow_in_process_fallback only allowed for trusted read tools")

    if self.container_codegen_trusted and not self.trusted:
        raise ValueError("container_codegen_trusted=True requires trusted=True")

    if self.risk in {"code_exec", "destructive"} and self.runner in {
        "in_process",
        "process",
    }:
        # 不直接拒绝也可以，但至少 planner 必须升级。
        pass

    return self
```

验收测试：

```text
tests/test_tool_policy_contract.py
- ToolPolicy exposes runner/idempotent/trusted/trusted_output/allow_in_process_fallback/container_codegen_trusted
- trusted_output without trusted fails
- allow_in_process_fallback for non-read fails
- container_codegen_trusted without trusted fails
- old minimal ToolPolicy still works
```

## P0-2：修复 planner 注释与实现冲突

`planner.py` 注释仍写着 `code_exec / destructive → container (with process fallback)`，但实现和 Level 2 文档都应该是 fail-closed，不应 process fallback。([GitHub][4])

修改：

```text
把 “with process fallback” 删除。
明确写：
code_exec/destructive → container only; if ContainerSandbox unavailable, executor denies.
```

验收测试：

```text
tests/tools/test_planner_security.py
- code_exec with runner=process is upgraded to container
- destructive with runner=in_process is upgraded to container
- network with runner=in_process is upgraded to process
- read trusted parallel_safe may use in_process
```

## P0-3：修复 ContainerSandbox timeout 行为与文档不一致

文档称 timeout 后会显式 `docker kill` + `docker rm -f`。([GitHub][1])
但当前 `ContainerSandbox.execute()` 使用 `docker run --rm` + `subprocess.run(timeout=timeout+5)`，超时时只返回 timeout error，没有显式 named container、kill、rm。([GitHub][9])

改法：

```python
container_name = f"seekflow-{uuid.uuid4().hex}"
cmd = [
    "docker", "run",
    "--name", container_name,
    "--network", "none",
    "--read-only",
    ...
]
proc = subprocess.Popen(...)
try:
    stdout, stderr = proc.communicate(timeout=timeout + startup_grace)
except subprocess.TimeoutExpired:
    subprocess.run(["docker", "kill", container_name], ...)
    subprocess.run(["docker", "rm", "-f", container_name], ...)
    proc.kill()
```

验收测试：

```text
tests/security/test_container_sandbox_timeout_cleanup.py
- monkeypatch subprocess.Popen to timeout
- assert docker kill called
- assert docker rm -f called
- assert temp code file removed
```

## P0-4：修复 xfail 策略与 CI 强制

`check_xfail_policy.py` 已支持 `--strict-core`，但默认只是 warning；Release CI 必须强制执行 strict-core。([GitHub][10])

新增 GitHub Actions：

```yaml
- name: Check xfail policy
  run: python scripts/check_xfail_policy.py --strict-core
```

验收：

```text
core path xfail 在 CI 中直接失败。
```

---

# 3. Lv3 的正确目标架构

Lv3 不应该继续扩展当前 `ToolExecutor → Python callable` 模式。
**Lv3 的核心是把“工具”从 Python callable 变成外部隔离对象。**

推荐架构：

```text
Agent / Runtime
   ↓
ToolExecutor
   ↓
PolicyEngine
   ↓
ToolIdentityResolver
   ↓
ExecutionPlanner
   ↓
ExternalToolRunner / MCPGateway / ContainerToolRunner / WasmToolRunner
   ↓
EgressGateway / SecretBroker / FilesystemBroker
   ↓
DurableAuditStore
```

Lv3 的强约束：

```text
- 第三方工具不能 import 到 seekflow 主进程。
- 第三方工具不能被 pickle 进 ProcessRunner。
- 第三方工具不能直接拿宿主 env。
- 第三方工具不能直接访问宿主网络。
- 第三方工具不能直接访问宿主文件系统。
- 第三方工具 schema / manifest / digest / policy 必须 frozen。
- 每次执行必须带 tool identity、tool digest、policy digest、sandbox profile。
```

---

# 4. Lv3 具体落地方案

## PR-1：新增 ToolManifest v1

新增文件：

```text
src/seekflow/tools/manifest.py
```

数据结构：

```python
class ToolManifest(BaseModel):
    schema_version: Literal["seekflow.tool.v1"] = "seekflow.tool.v1"

    name: str
    version: str
    description: str = ""

    publisher: str | None = None
    source: Literal["local", "registry", "mcp", "oci", "wasm"] = "local"

    entrypoint: dict[str, Any]
    package_digest: str
    schema_digest: str | None = None
    signature: str | None = None
    signing_key_id: str | None = None

    capabilities: set[str] = Field(default_factory=set)
    risk: RiskLevel = "read"

    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None = None

    network: NetworkManifest = Field(default_factory=NetworkManifest)
    filesystem: FilesystemManifest = Field(default_factory=FilesystemManifest)
    env: EnvManifest = Field(default_factory=EnvManifest)
    sandbox: SandboxManifest = Field(default_factory=SandboxManifest)

    requires_approval: bool = False
    idempotent: bool = False
```

新增：

```text
src/seekflow/tools/manifest_loader.py
src/seekflow/tools/manifest_verify.py
src/seekflow/tools/policy_compiler.py
```

核心逻辑：

```text
manifest.yaml → validate → verify digest/signature → compile ToolPolicy → register ToolDefinition
```

验收测试：

```text
tests/tools/test_manifest.py
- valid manifest loads
- missing digest rejected for third-party source
- schema digest mismatch rejected
- unsigned external manifest rejected in strict mode
- manifest risk/capabilities compile into ToolPolicy
```

---

## PR-2：新增 PolicyCompiler + PolicyLinter

新增文件：

```text
src/seekflow/tools/policy_linter.py
```

规则：

```text
DENY:
- source in {"registry", "mcp", "oci", "wasm"} and runner in {"in_process", "process"}
- risk=network but allowed_domains empty
- network.public_http but no url_params
- filesystem.* but workspace_root empty
- filesystem.write without requires_approval unless explicitly trusted
- code_exec/destructive without container/wasm/firecracker profile
- trusted_output=True for third-party source
- cache enabled for non-read and non-idempotent network
- env wildcard "*"
- secret env without SecretBroker binding
- allowed_domains contains "*"
- allowed_domains contains public suffix only, e.g. "com"
- path_params empty for filesystem capability
```

输出：

```python
class LintIssue(BaseModel):
    severity: Literal["error", "warning"]
    code: str
    message: str
    path: str
```

验收测试：

```text
tests/tools/test_policy_linter.py
- third-party in_process denied
- network without allowed_domains denied
- wildcard env denied
- trusted_output for third-party denied
- filesystem write without workspace denied
```

---

## PR-3：新增 ExternalToolRunner，彻底替代第三方 Python callable

新增文件：

```text
src/seekflow/tools/external_runner.py
```

接口：

```python
class ExternalToolRunner:
    name = "external_container"

    def run(
        self,
        manifest: ToolManifest,
        arguments: dict,
        timeout_s: float,
        *,
        max_output_bytes: int,
        egress_profile: EgressProfile,
        fs_profile: FSProfile,
        env_profile: EnvProfile,
    ) -> ToolRunResult:
        ...
```

执行方式：

```text
- 工具作为 OCI image 或 zip package 运行；
- 主进程只传 JSON；
- stdout 只允许一条 JSON result；
- stderr 进入 audit，不进入模型；
- no host env；
- no host network，网络必须走 egress proxy；
- workspace mount 默认 read-only；
- write mount 必须 scoped；
- 每次执行 fresh container；
- timeout 后 kill + rm；
- output bounded before parse；
- result schema validation。
```

容器命令示例：

```text
docker run
  --name seekflow-tool-{run_id}
  --network none
  --read-only
  --cap-drop ALL
  --security-opt no-new-privileges
  --pids-limit 64
  --memory 256m
  --cpus 1
  --user 65534:65534
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m
  -v input.json:/seekflow/input.json:ro
  -v output:/seekflow/output:rw
  image@sha256:...
  /seekflow/entrypoint
```

验收测试：

```text
tests/tools/test_external_runner.py
- external tool never calls Python func
- image without digest rejected
- timeout kills container
- stdout over max_output_bytes rejected/truncated
- invalid JSON result rejected
- no host env inherited
- network none by default
```

---

## PR-4：把 MCP 改成 MCPGateway

当前 MCP executor 会启动 MCP subprocess，发现工具后直接注册 wrapper。wrapper 调用 MCP server，然后作为普通工具进 ToolExecutor。([GitHub][11])
这个对 Lv2 trusted/sandboxed server 可以，但 Lv3 不够。

新增：

```text
src/seekflow/mcp/gateway.py
src/seekflow/mcp/policy.py
src/seekflow/mcp/manifest.py
```

MCPGateway 必须做：

```text
- server manifest required；
- command/args digest pinning；
- env allowlist default empty；
- dynamic tool list freeze；
- schema close-object；
- server tool namespace lock；
- tool mutation detection；
- per-server capability ceiling；
- per-tool policy compiler；
- stdout/stderr bounded；
- startup timeout；
- call timeout；
- idle timeout；
- max calls per run；
- approval hook；
- server process kill tree；
- audit every JSON-RPC request/response hash。
```

修改现有 `MCPServerConfig`：

```python
class MCPServerConfig(BaseModel):
    name: str
    command: str
    args: list[str] = []
    command_digest: str | None = None

    trust_level: MCPTrustLevel = MCPTrustLevel.UNTRUSTED

    allowed_capabilities: set[str] = set()
    max_risk: RiskLevel = "read"

    env_allowlist: set[str] = Field(default_factory=set)
    env: dict[str, SecretRef | str] = Field(default_factory=dict)

    allowed_domains: set[str] = Field(default_factory=set)
    workspace_root: Path | None = None

    freeze_tools: bool = True
    require_approval_for_mutation: bool = True
```

严禁：

```text
- trust_level 默认 SANDBOXED。应改为 UNTRUSTED。
- cfg.env 直接传给 StdioServerParameters。
```

当前 `to_stdio_params()` 会把 `cfg.env` 直接传入 MCP SDK 路径，和 manual path 的 env allowlist 行为不一致。([GitHub][12])

验收测试：

```text
tests/mcp/test_mcp_gateway.py
- env default empty
- env_allowlist enforced in SDK and manual path
- tool list mutation detected
- schema mutation detected
- untrusted server cannot register network tool without allowed_domains
- call timeout kills server
- disconnect kills process tree
```

---

## PR-5：新增 EgressGateway，替代 library-level SSRF 作为强边界

当前 `validate_url_strict()` 很适合 Lv2；Lv3 必须把网络出站从工具进程里拿走。([GitHub][8])

新增：

```text
src/seekflow/network/egress.py
src/seekflow/network/proxy.py
src/seekflow/network/policy.py
```

模型：

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

实现方式：

```text
- 外部工具容器 --network none；
- 工具如需联网，只能访问本地 egress sidecar；
- sidecar 根据 tool_id/run_id/policy 放行；
- DNS 在 sidecar 内完成；
- 每次 redirect 重新校验；
- block private/link-local/loopback/metadata；
- 禁止 CONNECT arbitrary tunnel；
- 记录 request hash、response hash、domain、resolved IP、bytes。
```

验收测试：

```text
tests/network/test_egress_gateway.py
- direct network unavailable inside external container
- allowed domain succeeds
- redirect to private IP blocked
- DNS resolves to private IP blocked
- metadata IP blocked
- oversized response blocked
- POST denied unless allowed
```

---

## PR-6：新增 SecretBroker

当前输出侧有 secret redaction，但 Lv3 需要输入侧隔离。`ContainerSandbox` 和 `ProcessSandbox` 都允许传 env；MCP 也有 env。([GitHub][9])

新增：

```text
src/seekflow/secrets/broker.py
src/seekflow/secrets/types.py
```

接口：

```python
class SecretRef(BaseModel):
    name: str
    scope: str
    required: bool = True

class SecretBroker:
    def resolve_for_tool(
        self,
        tool_identity: ToolIdentity,
        refs: list[SecretRef],
        run_id: str,
    ) -> dict[str, str]:
        ...
```

规则：

```text
- 默认不给任何 env；
- 禁止继承 os.environ；
- secret 只通过 SecretRef 注入；
- secret 注入必须 audit；
- secret value 不进入 trace；
- secret 不进入 model output；
- secret 可设置 TTL；
- secret 可绑定 tool digest。
```

验收测试：

```text
tests/secrets/test_secret_broker.py
- ambient env not inherited
- unapproved secret denied
- secret access audited
- secret value never appears in trace
```

---

## PR-7：新增 DurableAuditStore

当前 `ToolAuditRecord` 是内存 list，并且只记录 hash、latency、runner 等基础信息。([GitHub][3])
Lv3 需要 durable、append-only、可验证。

新增：

```text
src/seekflow/audit/store.py
src/seekflow/audit/model.py
```

数据结构：

```python
class AuditEvent(BaseModel):
    event_id: str
    ts: datetime
    run_id: str
    step: int
    event_type: str

    tool_name: str | None = None
    tool_version: str | None = None
    tool_digest: str | None = None
    manifest_digest: str | None = None
    policy_digest: str | None = None

    input_hash: str | None = None
    output_hash: str | None = None

    runner: str | None = None
    sandbox_image_digest: str | None = None

    egress: list[EgressAudit] = []
    secret_refs: list[str] = []

    prev_hash: str | None = None
    event_hash: str
```

后端：

```text
- JSONL append-only backend；
- SQLite WAL backend；
- hash chain；
- verify command。
```

CLI：

```text
seekflow audit verify audit.jsonl
seekflow audit export --run-id ...
```

验收测试：

```text
tests/audit/test_durable_audit.py
- append event hash chain valid
- tamper detection works
- tool digest/policy digest recorded
- secret values absent
```

---

## PR-8：强化 schema：input/output 都要 close object

当前 `validate_tool_arguments()` 只验证已有 schema；docs 说默认 `additionalProperties=false`，但 validation 文件本身没有执行 close-object，只依赖上游 schema compiler。([GitHub][13])

新增：

```text
src/seekflow/tools/schema.py
```

功能：

```python
def close_object_schema(schema: dict) -> dict:
    # recursively set additionalProperties=False
    # preserve explicit additionalProperties if already false
```

执行点：

```text
- tool registration 时 close；
- MCP discovery 时 close；
- manifest load 时 close；
- executor validate 前 assert schema closed。
```

验收测试：

```text
tests/tools/test_schema_close_object.py
- extra root arg rejected
- extra nested arg rejected
- MCP schema closed
- manifest schema closed
```

---

## PR-9：第三方工具 registry / install / verify CLI

新增 CLI：

```text
seekflow tool inspect ./tool.yaml
seekflow tool verify ./tool.yaml
seekflow tool install ./tool.yaml --strict
seekflow tool list
seekflow tool audit <name>
```

存储：

```text
~/.seekflow/tools/
  registry.json
  manifests/
  packages/
```

强制：

```text
- registry source 必须 digest pin；
- strict mode 必须签名；
- 安装时生成 compiled policy；
- compiled policy hash 进入 audit。
```

验收测试：

```text
tests/cli/test_tool_registry_cli.py
- install unsigned external tool denied in strict mode
- digest mismatch denied
- installed tool policy hash stable
```

---

## PR-10：Release 与版本工程修正

当前 README 显示没有 GitHub Releases。([GitHub][2])
`pyproject.toml` 是 0.3.6，描述也是 Level 2 semi-production candidate。([GitHub][14])
这对 Lv3 很关键，因为插件生态必须依赖可验证 release。

必须新增 release gate：

```text
- version consistency test；
- signed git tag；
- GitHub Release；
- PyPI Trusted Publishing；
- SBOM；
- provenance；
- changelog；
- security advisory template。
```

CI 必跑：

```text
pytest
ruff check
mypy src/seekflow/types.py src/seekflow/policy.py src/seekflow/tools src/seekflow/security
python scripts/check_xfail_policy.py --strict-core
container integration tests
mcp gateway tests
audit tamper tests
egress gateway tests
```

---

# 5. Claude Code 执行顺序

建议不要让 Claude 一次性“大改 Lv3”。按下面 6 个阶段做，每个阶段必须测试通过再继续。

## Phase A：先修 Lv2 public main

```text
1. 修 ToolPolicy 字段缺失。
2. 修 planner 注释与测试。
3. 修 ContainerSandbox timeout cleanup。
4. 强制 strict-core xfail。
5. 跑完整 pytest。
```

完成标准：

```text
- 当前 public main 不再有 AttributeError 风险；
- README / docs / pyproject / __version__ 一致；
- Level 2 baseline 可信。
```

## Phase B：引入 Manifest / PolicyCompiler

```text
1. ToolManifest v1。
2. PolicyCompiler。
3. PolicyLinter。
4. manifest digest/signature placeholder。
```

完成标准：

```text
- 第三方工具无法绕过 manifest；
- manifest 可以稳定编译为 ToolPolicy；
- lint error 阻止注册。
```

## Phase C：引入 ExternalToolRunner

```text
1. 外部工具容器化执行。
2. 禁止 Python callable。
3. 禁止 pickle。
4. stdin/stdout JSON protocol。
5. output schema validation。
```

完成标准：

```text
- third-party source 永远不会进入 InProcessRunner/ProcessRunner；
- third-party source 只能 ExternalToolRunner / WasmRunner / ContainerToolRunner。
```

## Phase D：MCPGateway

```text
1. MCP tool discovery freeze。
2. env allowlist 修正。
3. schema mutation detection。
4. call timeout / kill tree。
5. per-server policy ceiling。
```

完成标准：

```text
- arbitrary MCP server 默认不能注册高风险工具；
- MCP server 不能动态扩大 schema/capability。
```

## Phase E：EgressGateway + SecretBroker

```text
1. 外部工具 no network。
2. egress sidecar/proxy。
3. DNS/IP/redirect enforcement。
4. secret broker。
5. no ambient env。
```

完成标准：

```text
- 第三方工具无法访问 metadata/private network；
- 第三方工具无法读取宿主 env。
```

## Phase F：Durable Audit + Release

```text
1. append-only audit。
2. hash chain。
3. audit verify CLI。
4. SBOM/provenance。
5. signed release。
```

完成标准：

```text
- 每次 Lv3 tool call 可追溯；
- tool digest / manifest digest / policy digest / sandbox image digest 可验证。
```

---

# 6. 最重要的设计原则

给 Claude Code 的最高优先级约束：

```text
不要试图把 ProcessRunner 加固成 Lv3 sandbox。
不要让第三方工具成为 Python callable。
不要让 MCP wrapper 直接变成普通 ToolDefinition callable。
不要依赖工具自觉使用 fetch_url_hardened。
不要继承 os.environ。
不要让 metadata.trusted / manifest 声明直接提升 trusted_output。
不要在未验证 digest/signature 前注册外部工具。
```

正确方向是：

```text
Lv2: trusted registered Python tools + policy + runner isolation
Lv3: untrusted external tools + manifest + signature + container/wasm isolation + egress broker + secret broker + durable audit
```

---

# 7. 最终结论

上一轮审计报告给出的 Lv3 方向**是正确的**，但当前公开 main 必须先修复 Lv2 一致性，尤其是 `ToolPolicy` 字段缺失与 ContainerSandbox timeout cleanup 的文档/实现不一致。

真正的 Lv3 不应是“继续增强 ToolExecutor”，而应是：

> **把 SeekFlow 从可信 Python 工具运行时，升级为零信任工具网关。**

最短落地路线：

```text
先修 Lv2 public main → ToolManifest → PolicyCompiler/Linter → ExternalToolRunner → MCPGateway → EgressGateway → SecretBroker → DurableAuditStore → signed release。
```

[1]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/docs/security/levels.md "raw.githubusercontent.com"
[2]: https://github.com/WYZAAACCC/SeekFlow "GitHub - WYZAAACCC/SeekFlow: DeepSeek-native agent framework with production-grade reliability · GitHub"
[3]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/executor.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/planner.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/runners.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/container_runner.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/policy.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/security/http.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/sandbox.py "raw.githubusercontent.com"
[10]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/scripts/check_xfail_policy.py "raw.githubusercontent.com"
[11]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/mcp/executor.py "raw.githubusercontent.com"
[12]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/mcp/config.py "raw.githubusercontent.com"
[13]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/validation.py "raw.githubusercontent.com"
[14]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/pyproject.toml "raw.githubusercontent.com"
