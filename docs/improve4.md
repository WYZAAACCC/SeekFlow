# SeekFlow 生产级修复与改进工程方案

以下内容可以直接交给 **Claude Code** 作为执行任务书。目标不是“再加几个功能”，而是把 SeekFlow 从一个有潜力的 DeepSeek Agent 框架，重构成一个 **DeepSeek-native、policy-enforced、sandbox-first、cache/cost-aware、可审计的生产级 Agent Runtime**。

我先给最终工程目标，然后给分阶段 PR、具体文件修改、接口设计、测试清单、验收标准，以及最后可直接复制给 Claude Code 的执行 Prompt。

---

# 1. 当前代码状态基线

当前 README 宣称 SeekFlow v0.2.0，定位为 DeepSeek-native，并声称具备 production-grade security、Policy Engine、SSRF protection、path sandboxing、secret redaction、preflight cost budgeting、per-tool timeout 等能力。仓库页面同时显示没有 published releases，而 `pyproject.toml` 的项目版本仍是 `0.1.0`，并且 mypy 虽然开启 strict，却对 runtime、agent、mcp、fim、structured、truncation 等核心模块设置了 `ignore_errors=true`。这意味着“文档宣称的生产级”与“工程发布/类型质量现状”不一致。([GitHub][1])

当前 `ToolPolicy` 数据模型已经有 capabilities、risk、timeout、max input/output、parallel_safe、requires_approval、allowed_domains、workspace_root 等字段，这个设计方向是对的；`PolicyEngine` 也已经实现了基础风险、sandbox、workspace、domain、approval 检查。问题在于这些检查还没有形成完整的不可绕过执行内核。([GitHub][2])

当前 `ToolExecutor` 已经加入了一个临时 policy gate，但它在执行时临时 new 一个 `PolicyEngine()`，只在 `tool_def.policy is not None` 时执行策略，没有通过构造器注入 policy engine、run context、approval handler、sandbox manager；而 `execute_batch()` 对无 policy 工具仍然默认视为 safe read 并允许并行执行，这是生产安全模型中非常危险的默认值。([GitHub][3])

当前 `ToolRuntime.chat()` 创建 `ToolExecutor` 时只传 registry、repair、max_result_chars、cache、truncation_strategy，没有传入 policy context、approval handler、sandbox；因此 runtime 层无法表达“本次运行允许哪些 capability、workspace root 是什么、是否允许 dangerous tools、是否强制 sandbox、当前 tenant/user/run 是谁”。([GitHub][4])

当前 dangerous builtins 仍然存在高风险：`fetch_url` 直接使用 `urllib.request.urlopen`，没有调用统一的 hardened URL validator；`run_python` 把代码写入临时文件后直接本机 subprocess 执行；`query_sql` 直接 `sqlite3.connect(db_path)` 并执行传入 query；这些能力一旦被模型触发，就会成为 SSRF、本地代码执行、数据读取/破坏和资源 DoS 风险。([GitHub][5])

DeepSeek 官方当前模型页显示 V4 Flash / V4 Pro 支持 thinking、JSON Output、Tool Calls、Chat Prefix Completion、FIM；pricing 按 cache hit input、cache miss input、output 分开计费，并注明 `deepseek-chat` / `deepseek-reasoner` 将来会废弃、兼容映射到 V4 Flash 的非 thinking / thinking 模式。([DeepSeek API Docs][6])

DeepSeek thinking mode 要求通过 `extra_body={"thinking":{"type":"enabled/disabled"}}` 控制，支持 `reasoning_effort`；thinking mode 下 `temperature`、`top_p`、presence/frequency penalty 不生效；如果 thinking mode 中发生 tool call，`reasoning_content` 必须在后续请求中完整回传，否则会 400。当前 SeekFlow runtime 保留 tool_call 场景的 `reasoning_content`，这个方向是正确的，但需要 golden tests 固化协议。([DeepSeek API Docs][7])

---

# 2. 总体修复目标

最终要达到的架构是：

```text
Agent API
  -> ToolRuntime
     -> DeepSeekClient
     -> UsageNormalizer
     -> CostBudgetGuard
     -> ToolExecutor
        -> ArgumentParser
        -> SchemaValidator
        -> PolicyEngine
        -> ApprovalHandler
        -> SandboxManager
        -> ToolRunner
        -> OutputSanitizer
        -> AuditLogger
     -> TraceRecorder / Telemetry
```

核心原则：

```text
1. ToolExecutor 是唯一工具执行入口。
2. PolicyEngine 必须是不可绕过的强制网关。
3. 没有 policy 的工具默认 high risk / requires approval，不允许默认 safe read。
4. dangerous_tools=True 必须废弃，改成 capability profile。
5. 文件、网络、SQL、Python、MCP 都必须有各自的安全 profile。
6. Python code execution 没有 sandbox 时必须拒绝执行。
7. 所有外部工具输出默认 untrusted。
8. DeepSeek cache/cost/thinking/tool-call 协议必须通过统一适配层处理。
9. README、pyproject、docs、tests、CI 需要与真实能力一致。
```

---

# 3. 分阶段 PR 计划

## PR-0：建立生产级修复基线

### 目标

先修正工程事实，避免后续开发在错误版本和错误宣称上继续堆代码。

### 修改文件

```text
pyproject.toml
README.md
docs/SECURITY.md
docs/ROADMAP.md
src/seekflow/__init__.py
tests/test_version_consistency.py
```

### 具体要求

1. 统一版本号。
   当前 README 是 v0.2.0，但 `pyproject.toml` 是 0.1.0。选择一个真实版本，例如：

```toml
[project]
version = "0.2.1"
```

2. README 中把 “production-grade security” 改成更准确的：

```text
Security-hardened beta. Dangerous capabilities are disabled by default.
Production use requires policy profiles and sandbox configuration.
```

3. 增加 `docs/SECURITY.md`，明确：

```text
- 默认只允许 safe calculate。
- 文件/网络/SQL/代码执行/MCP 都是 dangerous capability。
- 代码执行必须配置 sandbox。
- MCP server 是本地可执行插件，默认不建议启用。
- Tool output 默认 untrusted。
```

4. 增加版本一致性测试：

```python
def test_version_consistency():
    import tomllib
    import seekflow

    with open("pyproject.toml", "rb") as f:
        project_version = tomllib.load(f)["project"]["version"]

    assert seekflow.__version__ == project_version
```

### 验收标准

```text
pytest tests/test_version_consistency.py 通过
README 不再夸大当前安全能力
docs/SECURITY.md 能让用户明确知道 dangerous capability 的风险
```

---

# 4. PR-1：将 PolicyEngine 内核化

这是整个项目的最高优先级。当前 `ToolExecutor` 的 policy gate 是临时补丁，必须重构成正式执行内核。

## 4.1 新增执行上下文

### 新增文件

```text
src/seekflow/execution/context.py
```

### 实现

```python
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Literal, Any

RiskLevel = Literal["read", "network", "write", "code_exec", "destructive"]


@dataclass(frozen=True)
class ToolExecutionContext:
    run_id: str
    user_id: str | None = None
    tenant_id: str | None = None

    dangerous_tools_enabled: bool = False
    allowed_capabilities: set[str] = field(default_factory=set)
    max_risk: RiskLevel = "read"

    workspace_root: Path | None = None
    allowed_domains: set[str] = field(default_factory=set)

    sandbox_required: bool = True
    sandbox: Any | None = None

    cost_budget_remaining: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

## 4.2 新增审批协议

### 新增文件

```text
src/seekflow/execution/approval.py
```

### 实现

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Any

from seekflow.types import ToolDefinition


@dataclass(frozen=True)
class ApprovalRequest:
    tool: ToolDefinition
    arguments: dict[str, Any]
    reason: str
    risk: str
    capability: set[str]
    run_id: str | None = None


@dataclass(frozen=True)
class ApprovalResult:
    approved: bool
    reason: str = ""


class ApprovalHandler(Protocol):
    def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        ...
```

默认没有 approval handler 时，凡是 `requires_approval=True` 都必须拒绝执行，而不是静默允许。

---

## 4.3 重构 PolicyEngine

### 修改文件

```text
src/seekflow/policy.py
```

### 设计要求

`PolicyEngine.authorize()` 必须只做决策，不做实际执行。它应该返回：

```python
@dataclass
class PolicyDecision:
    allowed: bool
    reason: str = ""
    requires_approval: bool = False
    sanitized_args: dict[str, Any] | None = None
    effective_policy: ToolPolicy | None = None
```

### 默认策略

当前 `_DEFAULT_RESTRICTIVE_POLICY = ToolPolicy()` 实际上 risk 默认是 `read`，这不够 restrictive。必须改成：

```python
DEFAULT_UNTRUSTED_POLICY = ToolPolicy(
    capabilities=set(),
    risk="destructive",
    parallel_safe=False,
    requires_approval=True,
)
```

或者新增 `ToolPolicy.default_untrusted()`：

```python
class ToolPolicy(BaseModel):
    ...

    @classmethod
    def default_untrusted(cls) -> "ToolPolicy":
        return cls(
            capabilities=set(),
            risk="destructive",
            parallel_safe=False,
            requires_approval=True,
        )
```

### `authorize()` 必须检查

```text
1. policy 缺失：使用 default_untrusted。
2. risk > context.max_risk：deny。
3. 非 read risk 且 context.dangerous_tools_enabled=False：deny。
4. capability 不在 context.allowed_capabilities：deny。
5. filesystem.read/write 必须有 workspace_root。
6. filesystem path 参数必须 safe_join 后仍在 workspace_root。
7. network.public_http 必须有 allowed_domains，且 URL 必须通过 hardened validator。
8. code.exec 必须有 sandbox，且不能是 NoSandbox。
9. destructive 永远 requires approval。
10. policy.requires_approval=True 时返回 requires_approval。
```

### 注意

不要再只检查 `hostname in allowed_domains`。必须把 URL 校验交给 hardened URL validator，见 PR-3。

---

## 4.4 重构 ToolExecutor 构造器

### 修改文件

```text
src/seekflow/tools/executor.py
```

### 新构造器

```python
class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        policy_engine: PolicyEngine | None = None,
        context: ToolExecutionContext | None = None,
        approval_handler: ApprovalHandler | None = None,
        sandbox_manager: SandboxManager | None = None,
        repair: bool = True,
        max_result_chars: int = 12000,
        cache: ToolCallCache | None = None,
        truncation_strategy: TruncationStrategy = TruncationStrategy.JSON_AWARE,
        max_parallel: int = 4,
    ) -> None:
        ...
```

如果 `context is None`，必须创建最保守 context：

```python
ToolExecutionContext(
    run_id="unknown",
    dangerous_tools_enabled=False,
    allowed_capabilities=set(),
    max_risk="read",
    sandbox_required=True,
)
```

### 执行顺序必须固定

```text
parse arguments
repair JSON if allowed
lookup tool
coerce arguments
schema validation
policy authorization
approval if required
sandbox selection
execute
output sanitize
truncate
audit
cache
return
```

### repair 的危险工具策略

当前代码里 repaired dangerous args 低置信度会被拒绝，这是好方向，但阈值和错误信息不一致：代码注释/错误文案里同时出现 0.95 和 0.85。应统一：

```python
DANGEROUS_REPAIR_CONFIDENCE_THRESHOLD = 0.95
```

策略：

```text
read 工具：repair_confidence >= 0.60 可执行
network/write/code_exec/destructive：repair_confidence >= 0.95 才能自动执行
低于阈值：requires approval 或 deny
```

### 无 policy 工具

当前 `execute_batch()` 的逻辑是 `policy else True`，也就是无 policy 默认 parallel safe。必须改成：

```python
if policy is None:
    is_parallel_safe = False
```

并且无 policy 工具要走 default_untrusted policy。

### 验收测试

新增：

```text
tests/security/test_policy_enforced_executor.py
tests/security/test_no_policy_default_denied.py
tests/security/test_repair_dangerous_gate.py
tests/security/test_parallel_execution_policy.py
```

测试用例：

```python
def test_no_policy_tool_requires_approval_or_denied():
    ...

def test_network_tool_denied_without_capability():
    ...

def test_write_tool_denied_without_workspace_root():
    ...

def test_code_exec_denied_without_sandbox():
    ...

def test_requires_approval_denied_without_handler():
    ...

def test_requires_approval_executes_with_positive_handler():
    ...

def test_execute_batch_no_policy_not_parallel_safe():
    ...
```

---

# 5. PR-2：Runtime 全链路传递安全上下文

当前 runtime 创建 executor 时没有传入 context，导致 policy 无法知道本次运行的安全配置。必须从 Agent API 到 Runtime 到 Executor 全链路传递。

## 修改文件

```text
src/seekflow/runtime.py
src/seekflow/agent/agent.py
src/seekflow/types.py
src/seekflow/execution/context.py
tests/test_runtime_policy_context.py
```

## ToolRuntime.**init** 新参数

```python
def __init__(
    ...,
    policy_context: ToolExecutionContext | None = None,
    policy_engine: PolicyEngine | None = None,
    approval_handler: ApprovalHandler | None = None,
    sandbox: ToolSandbox | None = None,
):
    self._policy_context = policy_context
    self._policy_engine = policy_engine or PolicyEngine()
    self._approval_handler = approval_handler
    self._sandbox = sandbox or NoSandbox()
```

## ToolRuntime.chat() 创建 executor

```python
context = self._policy_context or ToolExecutionContext(
    run_id=recorder.run_id if hasattr(recorder, "run_id") else "unknown",
    dangerous_tools_enabled=False,
    max_risk="read",
    sandbox=self._sandbox,
)

executor = ToolExecutor(
    self._registry,
    repair=self._repair,
    max_result_chars=self._max_result_chars,
    cache=self._active_cache,
    truncation_strategy=self._truncation_strategy,
    policy_engine=self._policy_engine,
    context=context,
    approval_handler=self._approval_handler,
)
```

## DeepSeekAgent 新 API

废弃：

```python
dangerous_tools=True
```

保留兼容但警告：

```python
warnings.warn(
    "dangerous_tools=True is deprecated. Use capability profiles instead.",
    DeprecationWarning,
)
```

新增：

```python
def allow_filesystem(
    self,
    *,
    root: str | Path,
    read: bool = True,
    write: bool = False,
    allowed_extensions: set[str] | None = None,
    max_file_bytes: int = 5_000_000,
) -> "DeepSeekAgent":
    ...

def allow_network(
    self,
    *,
    domains: set[str],
    https_only: bool = True,
    max_response_bytes: int = 1_000_000,
) -> "DeepSeekAgent":
    ...

def allow_python(
    self,
    *,
    sandbox: ToolSandbox,
    timeout_s: float = 10.0,
) -> "DeepSeekAgent":
    ...

def allow_sqlite(
    self,
    *,
    root: str | Path,
    readonly: bool = True,
    max_rows: int = 1000,
    timeout_s: float = 2.0,
) -> "DeepSeekAgent":
    ...
```

Agent 内部维护：

```python
self._allowed_capabilities: set[str]
self._allowed_domains: set[str]
self._workspace_root: Path | None
self._max_risk: RiskLevel
self._sandbox: ToolSandbox
```

## 验收标准

```text
Agent 默认只允许 calculate。
Agent.allow_network(domains={"example.com"}) 后，仅 example.com 网络工具可执行。
Agent.allow_filesystem(root=tmp_path) 后，文件工具只能访问 tmp_path 内文件。
dangerous_tools=True 仍可用但发 DeprecationWarning，并映射为显式 profiles。
```

---

# 6. PR-3：重写 dangerous builtins 为安全工具包

当前 dangerous builtins 放在 `agent/agent.py` 内部和 `agent/builtins.py` 中，职责混乱，且高危。应拆成独立工具模块。

## 新目录结构

```text
src/seekflow/tools/builtins/
  __init__.py
  calculate.py
  filesystem.py
  network.py
  python_exec.py
  sqlite.py
  text.py
```

保留旧 `src/seekflow/agent/builtins.py`，但改成兼容 re-export，并标记 deprecated。

---

## 6.1 文件工具

### 新文件

```text
src/seekflow/tools/builtins/filesystem.py
```

### 实现

```python
from pathlib import Path
from seekflow.security import validate_file_access, safe_join
from seekflow.types import ToolPolicy
from seekflow.tools.decorator import tool


def make_read_file_tool(
    *,
    workspace_root: str | Path,
    allowed_extensions: set[str] | None = None,
    max_file_bytes: int = 5_000_000,
):
    root = Path(workspace_root).resolve()

    @tool(trusted=False)
    def read_file(path: str) -> str:
        """Read a text file inside the configured workspace."""
        resolved = validate_file_access(
            path,
            workspace_root=root,
            allow_ext=allowed_extensions,
            max_bytes=max_file_bytes,
        )
        try:
            return resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return resolved.read_bytes().decode("utf-8", errors="replace")

    return read_file.with_policy(ToolPolicy(
        capabilities={"filesystem.read"},
        risk="read",
        workspace_root=root,
        timeout_s=2.0,
        max_output_bytes=max_file_bytes,
        parallel_safe=True,
    ))
```

### 写文件工具

只允许写到 workspace 内，并且默认关闭：

```python
def make_write_file_tool(...):
    ...
    policy = ToolPolicy(
        capabilities={"filesystem.write"},
        risk="write",
        workspace_root=root,
        requires_approval=True,
        parallel_safe=False,
    )
```

### 测试

```text
tests/security/test_filesystem_tools.py
```

必须覆盖：

```text
读取 workspace 内文件成功
读取 ../secret 失败
读取 /etc/passwd 失败
读取 .env 失败
读取 .sqlite/.db 失败
超过 max_file_bytes 失败
写文件无审批失败
写文件 path traversal 失败
```

---

## 6.2 网络工具：Hardened HTTP Client

当前 `security.validate_url()` 只检查 scheme、hostname、单次 DNS 解析私网，且 DNS 解析失败时 `_is_private_ip` 返回 False，相当于无法解析时放行；生产 SSRF 防护必须重写。([GitHub][8])

### 新文件

```text
src/seekflow/security/http.py
```

### 设计

```python
@dataclass(frozen=True)
class NetworkPolicy:
    allowed_domains: set[str]
    allowed_schemes: set[str] = field(default_factory=lambda: {"https"})
    allowed_ports: set[int] = field(default_factory=lambda: {443})
    block_private_ips: bool = True
    max_redirects: int = 3
    max_response_bytes: int = 1_000_000
    timeout_s: float = 10.0
```

### 必须实现

```python
def canonicalize_host(host: str) -> str:
    # IDNA normalize, lowercase, strip trailing dot
    ...

def domain_allowed(host: str, allowed_domains: set[str]) -> bool:
    # 支持 exact 和安全 suffix:
    # host == example.com or host.endswith(".example.com")
    # 不能让 evilexample.com 匹配 example.com
    ...

def resolve_all(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    # getaddrinfo 所有 A/AAAA
    # DNS 解析失败必须 fail closed
    ...

def is_forbidden_ip(ip) -> bool:
    # private, loopback, link-local, multicast, reserved, unspecified
    ...

def validate_url_strict(url: str, policy: NetworkPolicy) -> ValidatedURL:
    # parse
    # scheme
    # username/password forbidden
    # hostname required
    # port allowed
    # domain allowlist
    # resolve all IPs
    # forbid private/reserved
    ...
```

### Hardened fetch

```python
def fetch_url_hardened(url: str, policy: NetworkPolicy) -> str:
    current = url
    for redirect_count in range(policy.max_redirects + 1):
        validated = validate_url_strict(current, policy)

        # 使用 httpx.Client(follow_redirects=False)
        # 每跳手动处理 Location，并重新 validate
        # stream read，超过 max_response_bytes 立即停止
        ...

    raise PermissionError("too many redirects")
```

### 新工具

```text
src/seekflow/tools/builtins/network.py
```

```python
def make_fetch_url_tool(policy: NetworkPolicy):
    @tool(trusted=False)
    def fetch_url(url: str) -> str:
        """Fetch a public HTTPS URL from the allowlisted domains."""
        return fetch_url_hardened(url, policy)

    return fetch_url.with_policy(ToolPolicy(
        capabilities={"network.public_http"},
        risk="network",
        allowed_domains=policy.allowed_domains,
        timeout_s=policy.timeout_s,
        parallel_safe=True,
    ))
```

### 测试

```text
tests/security/test_hardened_http.py
tests/security/test_ssrf_redirects.py
```

覆盖：

```text
http://169.254.169.254/latest/meta-data 拒绝
http://127.0.0.1 拒绝
http://localhost 拒绝
http://[::1] 拒绝
DNS 解析失败拒绝
allow_domains 未配置拒绝
evil-example.com 不匹配 example.com
sub.example.com 匹配 example.com
redirect 到 127.0.0.1 拒绝
redirect 到非 allowlist 域名拒绝
响应体超过 max_response_bytes 截断或拒绝
URL 中 user:pass@host 拒绝
默认只允许 https
```

---

## 6.3 Python 执行工具必须走 sandbox

当前 `run_python` 是本机 subprocess 执行，必须废弃。([GitHub][5])

### 新文件

```text
src/seekflow/tools/builtins/python_exec.py
```

### 实现

```python
from seekflow.sandbox import ToolSandbox, NoSandbox
from seekflow.types import ToolPolicy
from seekflow.tools.decorator import tool


def make_python_exec_tool(
    *,
    sandbox: ToolSandbox,
    timeout_s: float = 10.0,
):
    @tool(trusted=False)
    def run_python(code: str) -> str:
        """Execute Python code inside the configured sandbox."""
        result = sandbox.execute(code, timeout=timeout_s)
        if not result.ok:
            return f"[sandbox error] {result.error or result.stderr}"
        return result.stdout

    return run_python.with_policy(ToolPolicy(
        capabilities={"code.exec"},
        risk="code_exec",
        timeout_s=timeout_s,
        parallel_safe=False,
        requires_approval=True,
    ))
```

### Policy 要求

如果 sandbox 是 `NoSandbox`，直接 deny。

当前项目已有 `NoSandbox`、`LocalThreadSandbox`、`ContainerSandbox`、`ProcessSandbox`。`ContainerSandbox` 用 Docker、`--network none`、memory、CPU、read-only、tmpfs、非 root 用户，这个方向可以保留，但还要加强 timeout kill 和错误处理。([GitHub][9])

### 加强 ContainerSandbox

修改：

```text
src/seekflow/sandbox.py
```

要求：

```text
1. 支持 network_mode="none" 默认。
2. 支持 memory、cpus、pids_limit。
3. 支持 docker timeout 后强制 stop container。
4. 不挂载宿主目录，只挂载临时代码文件 ro。
5. 默认 env 为空。
6. stdout/stderr 总大小限制。
```

### 测试

```text
tests/security/test_python_sandbox.py
```

覆盖：

```text
NoSandbox 拒绝
ContainerSandbox 缺 Docker 时返回明确错误
timeout 后进程被终止
代码不能访问网络
代码不能读取宿主 /etc/passwd
stdout 超长被截断
requires_approval 无 handler 时拒绝
```

---

## 6.4 SQLite 工具安全化

当前 `query_sql` 直接连接 db_path 并执行 query，必须替换为只读、安全 authorizer 版本。([GitHub][5])

### 新文件

```text
src/seekflow/tools/builtins/sqlite.py
```

### 实现要求

```python
def make_sqlite_query_tool(
    *,
    workspace_root: str | Path,
    max_rows: int = 1000,
    timeout_s: float = 2.0,
):
    ...
```

### 必须使用只读 URI

```python
uri = f"file:{resolved.as_posix()}?mode=ro"
conn = sqlite3.connect(uri, uri=True, timeout=timeout_s)
```

### 必须设置 authorizer

```python
ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
}

def authorizer(action, arg1, arg2, dbname, source):
    if action in ALLOWED_ACTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY

conn.set_authorizer(authorizer)
```

### 必须设置 progress handler

```python
deadline = time.monotonic() + timeout_s

def progress():
    if time.monotonic() > deadline:
        return 1
    return 0

conn.set_progress_handler(progress, 1000)
```

### SQL 限制

```text
只允许单条 SELECT。
禁止 PRAGMA，除非实现 allowlist。
禁止 ATTACH。
禁止 load_extension。
禁止分号多语句。
强制 LIMIT，如果用户没写 LIMIT 自动包装：
SELECT * FROM (<user_query>) LIMIT max_rows
```

### 测试

```text
tests/security/test_sqlite_tool.py
```

覆盖：

```text
SELECT 成功
DELETE 拒绝
INSERT 拒绝
DROP 拒绝
ATTACH 拒绝
PRAGMA 拒绝
load_extension 拒绝
多语句拒绝
workspace 外 db 拒绝
超时查询中断
返回行数不超过 max_rows
```

---

# 7. PR-4：MCP 安全化

MCP 是本地可执行插件系统，不是普通工具注册。当前 runtime 会连接 MCP server 并注册其 tools；manual fallback 会 subprocess 启动 MCP server。必须给 MCP server 加 sandbox profile、env allowlist、capability profile 和 policy derive。([GitHub][4])

## 修改文件

```text
src/seekflow/mcp/config.py
src/seekflow/mcp/executor.py
src/seekflow/mcp/adapter.py
src/seekflow/runtime.py
tests/security/test_mcp_policy.py
tests/security/test_mcp_sandbox.py
```

## MCPServerConfig 新字段

```python
@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str]
    transport: str = "stdio"

    sandbox: ToolSandbox | None = None
    env_allowlist: set[str] = field(default_factory=set)
    cwd: Path | None = None

    capabilities: set[str] = field(default_factory=set)
    max_risk: RiskLevel = "read"
    allowed_domains: set[str] = field(default_factory=set)
    workspace_root: Path | None = None
    requires_approval: bool = False
```

## MCP tool 注册策略

每个 MCP tool 注册时必须生成 policy：

```python
policy = ToolPolicy(
    capabilities=server_config.capabilities,
    risk=server_config.max_risk,
    allowed_domains=server_config.allowed_domains,
    workspace_root=server_config.workspace_root,
    requires_approval=server_config.requires_approval,
    parallel_safe=(server_config.max_risk == "read"),
)
```

## subprocess 启动要求

```text
1. env 默认空，仅允许 env_allowlist。
2. cwd 必须是 workspace root 或临时目录。
3. stderr 必须持续消费，避免阻塞。
4. 关闭时必须 terminate -> wait -> kill。
5. 生产 profile 中 MCP server 必须 sandbox。
```

## 验收测试

```text
MCP tool 无 policy 时不能注册或默认 requires approval
MCP server 不能继承 DEEPSEEK_API_KEY
MCP tool 访问 filesystem.write 时无 workspace_root 拒绝
MCP network capability 无 allowed_domains 拒绝
MCP subprocess disconnect 后无僵尸进程
```

---

# 8. PR-5：DeepSeek V4 协议与成本适配层

SeekFlow 的核心竞争力应该是 DeepSeek-native，而不是通用 Agent wrapper。

## 8.1 新增模型注册表

### 新文件

```text
src/seekflow/models.py
```

### 实现

```python
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ModelSpec:
    name: str
    supports_thinking: bool
    supports_tools: bool
    supports_json: bool
    supports_fim: bool
    max_context_tokens: int
    max_output_tokens: int
    input_cache_hit_price_cny: Decimal
    input_cache_miss_price_cny: Decimal
    output_price_cny: Decimal
    deprecated_alias_for: str | None = None


DEEPSEEK_MODELS = {
    "deepseek-v4-flash": ModelSpec(
        name="deepseek-v4-flash",
        supports_thinking=True,
        supports_tools=True,
        supports_json=True,
        supports_fim=True,
        max_context_tokens=1_000_000,
        max_output_tokens=384_000,
        input_cache_hit_price_cny=Decimal("0.0028"),
        input_cache_miss_price_cny=Decimal("0.14"),
        output_price_cny=Decimal("0.28"),
    ),
    "deepseek-v4-pro": ModelSpec(
        name="deepseek-v4-pro",
        supports_thinking=True,
        supports_tools=True,
        supports_json=True,
        supports_fim=True,
        max_context_tokens=1_000_000,
        max_output_tokens=384_000,
        input_cache_hit_price_cny=Decimal("0.003625"),
        input_cache_miss_price_cny=Decimal("0.435"),
        output_price_cny=Decimal("0.87"),
    ),
    "deepseek-chat": ModelSpec(
        name="deepseek-chat",
        supports_thinking=False,
        supports_tools=True,
        supports_json=True,
        supports_fim=False,
        max_context_tokens=1_000_000,
        max_output_tokens=384_000,
        input_cache_hit_price_cny=Decimal("0.0028"),
        input_cache_miss_price_cny=Decimal("0.14"),
        output_price_cny=Decimal("0.28"),
        deprecated_alias_for="deepseek-v4-flash",
    ),
    "deepseek-reasoner": ModelSpec(
        name="deepseek-reasoner",
        supports_thinking=True,
        supports_tools=True,
        supports_json=True,
        supports_fim=False,
        max_context_tokens=1_000_000,
        max_output_tokens=384_000,
        input_cache_hit_price_cny=Decimal("0.0028"),
        input_cache_miss_price_cny=Decimal("0.14"),
        output_price_cny=Decimal("0.28"),
        deprecated_alias_for="deepseek-v4-flash",
    ),
}
```

注意：DeepSeek 官方 pricing 可能变化，所以价格表必须允许 runtime update，并在文档中说明需要定期确认官方页面。DeepSeek 官方也明确提醒价格可能变化，应定期检查。([DeepSeek API Docs][6])

---

## 8.2 UsageNormalizer

### 新文件

```text
src/seekflow/usage.py
```

### 实现

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    reasoning_tokens: int = 0


def normalize_usage(usage: dict | None) -> NormalizedUsage:
    if not usage:
        return NormalizedUsage()

    prompt = int(usage.get("prompt_tokens", 0) or 0)
    completion = int(usage.get("completion_tokens", 0) or 0)
    total = int(usage.get("total_tokens", prompt + completion) or 0)

    details = usage.get("prompt_tokens_details", {}) or {}

    hit = int(
        details.get("prompt_cache_hit_tokens")
        or details.get("cached_tokens")
        or 0
    )

    miss = int(
        details.get("prompt_cache_miss_tokens")
        if details.get("prompt_cache_miss_tokens") is not None
        else max(prompt - hit, 0)
    )

    reasoning = int(details.get("reasoning_tokens", 0) or 0)

    return NormalizedUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cache_hit_tokens=hit,
        cache_miss_tokens=miss,
        reasoning_tokens=reasoning,
    )
```

当前 `DeepSeekClient` 已经能读取 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`，但 `_usage_to_dict()` streaming fallback 只看 `cached_tokens`，runtime 聚合也只累计 `cached_tokens`。这要统一成 `NormalizedUsage`。([GitHub][10])

## 8.3 CostEstimator

### 新增或修改

```text
src/seekflow/cost.py
src/seekflow/budget.py
```

### 实现

```python
from decimal import Decimal
from seekflow.models import get_model_spec
from seekflow.usage import NormalizedUsage


def estimate_actual_cost_cny(model: str, usage: NormalizedUsage) -> Decimal:
    spec = get_model_spec(model)
    return (
        Decimal(usage.cache_hit_tokens) * spec.input_cache_hit_price_cny
        + Decimal(usage.cache_miss_tokens) * spec.input_cache_miss_price_cny
        + Decimal(usage.completion_tokens) * spec.output_price_cny
    ) / Decimal(1_000_000)
```

### Runtime 聚合

`cumulative_usage` 不要再手写 dict 累加，改成：

```python
usage_accumulator.add(normalize_usage(response.usage))
```

输出：

```python
result.usage = usage_accumulator.to_dict()
result.cost = estimate_actual_cost_cny(model, usage_accumulator.snapshot())
```

### 测试

```text
tests/test_usage_normalizer.py
tests/test_cost_estimator.py
```

覆盖：

```text
prompt_cache_hit_tokens / prompt_cache_miss_tokens 正确归一
legacy cached_tokens 正确归一
miss 缺失时 prompt - hit
成本按 hit/miss/output 分别计算
```

---

# 9. PR-6：DeepSeek thinking/tool-call 协议固化

当前 runtime 已经在 tool call 场景保留 `reasoning_content`，这个必须保留并用测试锁死。DeepSeek 官方明确规定 thinking mode 中发生 tool call 后，`reasoning_content` 必须在后续请求中完整回传。([DeepSeek API Docs][7])

## 修改文件

```text
src/seekflow/runtime.py
src/seekflow/reasoning.py
tests/test_deepseek_thinking_protocol.py
```

## 要求

1. thinking mode 启用时自动删除或 warning 以下参数：

```text
temperature
top_p
presence_penalty
frequency_penalty
```

DeepSeek 官方说明这些参数在 thinking mode 下不生效。([DeepSeek API Docs][7])

2. 新增 thinking router：

```python
@dataclass(frozen=True)
class ThinkingDecision:
    enabled: bool
    effort: Literal["high", "max"] = "high"
    reason: str = ""


class ThinkingRouter:
    def route(
        self,
        *,
        task: str,
        tools_count: int,
        max_risk: str,
        response_format: str | None,
        model: str,
    ) -> ThinkingDecision:
        ...
```

推荐规则：

```text
JSON extraction -> disabled 或 high? 默认 disabled，除非复杂推理
tool_count > 0 且任务复杂 -> enabled high
代码审计/架构分析 -> enabled max
FIM -> disabled
最终 synthesis -> disabled/high 由 mode 决定
```

3. reasoning_content 默认不进入普通日志；trace 只保存：

```text
has_reasoning_content
reasoning_content_hash
reasoning_content_chars
```

4. golden tests：

```python
def test_tool_call_reasoning_content_preserved_exactly():
    ...

def test_non_tool_reasoning_content_can_be_compressed_or_omitted():
    ...

def test_thinking_mode_drops_ignored_sampling_params():
    ...

def test_missing_tool_call_reasoning_would_fail_protocol():
    ...
```

---

# 10. PR-7：Prompt Cache 真实稳定化

当前 `CacheStabilizer` 方向正确，但 `append_only_compress()` 仍会把压缩摘要拼回第一条 system message，这会改变 system message 内容，破坏 cache prefix。代码注释说“preserves cache”，但实现里创建了 `enhanced_system["content"] = original_content + compressed summary`，这与 DeepSeek prefix caching 的目标冲突。([GitHub][11])

## 修改文件

```text
src/seekflow/cache.py
src/seekflow/runtime.py
tests/test_cache_stability.py
```

## 新原则

```text
messages[0] = frozen system prompt，永不改变
messages[1] = optional frozen policy/tool summary，尽量不改变
messages[2] = dynamic compressed context，允许变化
messages[3:] = recent conversation
```

## 修改 append_only_compress()

把：

```python
enhanced_system["content"] = f"{original_content}\n\n[Compressed Context...]\n{summary}"
```

改成：

```python
result = []
if system_msg:
    result.append(system_msg)
    result.append({
        "role": "user",
        "content": f"[Compressed Context — {len(older)} older messages summarized]\n{summary}",
    })
else:
    result.append({
        "role": "system",
        "content": "You are a helpful assistant."
    })
    result.append({
        "role": "user",
        "content": f"[Compressed Context]\n{summary}",
    })

result.extend(recent)
return result
```

## 增加 prefix fingerprint

```python
@dataclass(frozen=True)
class PrefixFingerprint:
    hash: str
    byte_len: int
    message_count: int
```

测试：

```python
def test_append_only_compress_does_not_change_first_system_message():
    ...

def test_cache_stabilizer_repairs_drift_into_separate_context_message():
    ...

def test_tool_schema_serialization_deterministic():
    ...
```

---

# 11. PR-8：严格 JSON Schema 与 tool schema 生产化

DeepSeek strict mode 要求 beta base URL、function 设置 `strict: true`，并且 object schema 的所有 properties 都 required，`additionalProperties` 必须为 false。([DeepSeek API Docs][12])

## 修改文件

```text
src/seekflow/tools/schema.py
src/seekflow/tools/registry.py
src/seekflow/tools/strict.py
tests/test_strict_schema.py
```

## 要求

1. strict=True 时所有 object：

```json
{
  "type": "object",
  "properties": {...},
  "required": ["all", "properties"],
  "additionalProperties": false
}
```

2. 支持类型：

```text
object
string
number
integer
boolean
array
enum
anyOf
```

与 DeepSeek strict 支持范围一致。([DeepSeek API Docs][12])

3. tool argument validation：

```text
JSON parse
repair
jsonschema validate
Pydantic/coercion
policy authorize
execute
```

4. repair 后必须重新 validate。

5. dangerous tool 的 repair confidence 低于阈值必须 deny 或 approval。

---

# 12. PR-9：FIM 保持现状但补测试和模型约束

当前 FIM 已经通过 DeepSeek beta endpoint，且已加入 `max_tokens <= 4096` guard，这比之前审计时的目标状态更好。需要做的是补测试、模型能力约束、thinking 参数拒绝。([GitHub][13])

## 修改文件

```text
src/seekflow/fim.py
src/seekflow/models.py
tests/test_fim.py
```

## 要求

```text
1. max_tokens > 4096 抛 ValueError。
2. thinking 参数传入 FIM 时抛 ValueError。
3. model 必须 supports_fim=True。
4. streaming/non-streaming 都有测试。
5. prefix/suffix 非空校验。
```

---

# 13. PR-10：审计日志与可观测性

## 修改文件

```text
src/seekflow/tools/executor.py
src/seekflow/trace/recorder.py
src/seekflow/telemetry.py
tests/test_audit_trail.py
```

## ToolAuditRecord 增强

字段：

```python
@dataclass
class ToolAuditRecord:
    timestamp: float
    run_id: str
    tenant_id: str | None
    user_id: str | None

    tool_name: str
    tool_call_id: str | None

    args_hash: str
    result_hash: str | None

    latency_ms: int
    ok: bool
    error: str | None

    policy_decision: str
    policy_reason: str
    risk_level: str
    capabilities: list[str]

    repair_attempted: bool
    repair_confidence: float

    sandbox_name: str | None
    output_truncated: bool
```

## 日志红线

```text
不得记录原始 API key。
不得默认记录 reasoning_content 原文。
不得默认记录完整工具输出。
不得默认记录完整工具参数。
只记录 hash、长度、摘要、policy decision。
```

## Metrics

最少提供：

```text
seekflow_tool_calls_total
seekflow_tool_errors_total
seekflow_policy_denies_total
seekflow_approval_required_total
seekflow_sandbox_errors_total
seekflow_cache_hit_tokens_total
seekflow_cache_miss_tokens_total
seekflow_cost_cny_total
seekflow_reasoning_content_chars_total
```

---

# 14. PR-11：CI、类型、质量门禁

当前 mypy strict 被大量核心模块 ignore_errors 抵消。应逐步移除，但不能一次性大爆炸。([GitHub][14])

## 修改文件

```text
pyproject.toml
.github/workflows/ci.yml
.github/workflows/security.yml
```

## CI

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev,mcp]"
      - run: ruff check .
      - run: mypy src/seekflow/policy.py src/seekflow/tools src/seekflow/security.py src/seekflow/usage.py src/seekflow/models.py
      - run: pytest -q
```

## Security scan

```yaml
- run: pip install pip-audit bandit
- run: pip-audit
- run: bandit -r src/seekflow -x tests
```

## mypy 迁移策略

第一阶段从 ignore list 中移除：

```text
seekflow.policy
seekflow.security
seekflow.tools.*
seekflow.sandbox
seekflow.models
seekflow.usage
seekflow.cost
```

第二阶段再移除：

```text
seekflow.runtime
seekflow.agent.*
seekflow.mcp.*
```

---

# 15. Claude Code 可直接执行 Prompt

下面这段可以直接复制给 Claude Code。

```text
你现在是 SeekFlow 项目的主工程师。请在当前仓库中执行一次 production-hardening 重构。目标不是加新功能，而是把 SeekFlow 变成 DeepSeek-native、policy-enforced、sandbox-first、cache/cost-aware 的生产级 Agent Runtime。

请按以下 PR 顺序实施。每个 PR 都要包含代码、测试、文档，且保持向后兼容，除非明确标记 deprecated。

PR-0：修复版本与文档事实
1. 统一 pyproject.toml、src/seekflow/__init__.py、README.md 的版本号。
2. README 不要夸大 production-grade security。改成 security-hardened beta，并说明危险能力必须显式配置。
3. 新增 docs/SECURITY.md，说明 filesystem/network/sql/python/mcp 都是 dangerous capabilities。
4. 增加 tests/test_version_consistency.py。

PR-1：PolicyEngine 内核化
1. 新增 src/seekflow/execution/context.py，定义 ToolExecutionContext。
2. 新增 src/seekflow/execution/approval.py，定义 ApprovalRequest、ApprovalResult、ApprovalHandler Protocol。
3. 修改 src/seekflow/policy.py：
   - 缺失 policy 时使用 default_untrusted policy，risk=destructive，requires_approval=True。
   - authorize(tool_def,args,context) 必须检查 risk、dangerous_tools_enabled、capabilities、workspace_root、allowed_domains、sandbox、approval。
   - code.exec 没有 sandbox 或 sandbox.name == "no_sandbox" 时 deny。
   - filesystem.read/write 必须 safe_join workspace。
   - network.public_http 必须使用 hardened validate_url_strict。
4. 修改 src/seekflow/tools/executor.py：
   - 构造器注入 policy_engine、context、approval_handler、sandbox_manager。
   - execute() 的顺序必须是 parse -> repair -> lookup -> validate/coerce -> policy -> approval -> execute -> sanitize -> audit。
   - 无 policy 工具不能默认 safe read。
   - execute_batch() 中无 policy 工具不得并行。
   - dangerous tool 的 repaired arguments confidence 必须 >= 0.95，否则 deny 或 approval。
5. 增加 tests/security/test_policy_enforced_executor.py、test_no_policy_default_denied.py、test_repair_dangerous_gate.py、test_parallel_execution_policy.py。

PR-2：Runtime/Agent 全链路传递安全上下文
1. 修改 src/seekflow/runtime.py，让 ToolRuntime 接受 policy_context、policy_engine、approval_handler、sandbox。
2. Runtime 创建 ToolExecutor 时必须传入这些参数。
3. 修改 src/seekflow/agent/agent.py：
   - 保留 dangerous_tools=True 但发 DeprecationWarning。
   - 新增 allow_filesystem、allow_network、allow_python、allow_sqlite profile API。
   - Agent 根据 profile 构建 ToolExecutionContext。
4. 添加 tests/test_runtime_policy_context.py。

PR-3：重写 dangerous builtins
1. 新建 src/seekflow/tools/builtins/ 包：
   - calculate.py
   - filesystem.py
   - network.py
   - python_exec.py
   - sqlite.py
   - text.py
2. read_file 必须使用 validate_file_access，限制 workspace_root。
3. fetch_url 必须使用 hardened HTTP client。
4. run_python 必须使用 ToolSandbox；NoSandbox 拒绝。
5. query_sql 必须只读 SQLite URI、SELECT-only、set_authorizer、progress_handler、max_rows、workspace root。
6. 旧 src/seekflow/agent/builtins.py 改成 deprecated re-export。
7. 添加 tests/security/test_filesystem_tools.py、test_hardened_http.py、test_python_sandbox.py、test_sqlite_tool.py。

PR-4：实现 hardened HTTP / SSRF 防护
1. 新增 src/seekflow/security/http.py。
2. 实现 NetworkPolicy、validate_url_strict、fetch_url_hardened。
3. 要求：
   - 默认只允许 https。
   - DNS 解析失败 fail closed。
   - 检查所有 A/AAAA。
   - 禁止 private、loopback、link-local、reserved、multicast、unspecified。
   - 每次 redirect 都重新校验。
   - URL 中 user:pass@host 拒绝。
   - allowed_domains 支持 exact 和安全 subdomain suffix。
   - max_response_bytes 强制限制。
4. 添加 tests/security/test_ssrf_redirects.py。

PR-5：MCP 安全化
1. 修改 src/seekflow/mcp/config.py，让 MCPServerConfig 支持 sandbox、env_allowlist、cwd、capabilities、max_risk、allowed_domains、workspace_root、requires_approval。
2. 修改 src/seekflow/mcp/executor.py：
   - MCP subprocess 默认不继承 env。
   - stderr 必须被消费。
   - disconnect 必须 terminate -> wait -> kill。
   - 注册 MCP tools 时必须绑定从 server config 派生出的 ToolPolicy。
3. 添加 tests/security/test_mcp_policy.py、test_mcp_sandbox.py。

PR-6：DeepSeek V4 model / usage / cost 统一层
1. 新增 src/seekflow/models.py，定义 ModelSpec、DEEPSEEK_MODELS、get_model_spec。
2. 新增 src/seekflow/usage.py，定义 NormalizedUsage、normalize_usage。
3. 修改 src/seekflow/client.py、runtime.py、cost.py、budget.py：
   - 统一 prompt_cache_hit_tokens、prompt_cache_miss_tokens、cached_tokens。
   - 成本按 cache_hit_input、cache_miss_input、output 分开算。
   - deepseek-chat/deepseek-reasoner 发 FutureWarning，并映射到 V4 Flash 兼容语义。
4. 添加 tests/test_usage_normalizer.py、test_cost_estimator.py。

PR-7：DeepSeek thinking/tool-call 协议测试
1. 修改 runtime/reasoning：
   - thinking enabled 时移除或 warning temperature、top_p、presence_penalty、frequency_penalty。
   - tool_call 场景 reasoning_content 必须完整保留并回传。
   - 非 tool_call 场景 reasoning_content 不默认写入日志。
2. 添加 tests/test_deepseek_thinking_protocol.py。
3. 测试必须覆盖 tool_call + reasoning_content 的多轮回传。

PR-8：Prompt cache 稳定化
1. 修改 src/seekflow/cache.py：
   - append_only_compress 不得修改 messages[0] system content。
   - 压缩摘要放到独立 user/context message。
   - 添加 PrefixFingerprint。
2. Runtime 中使用 cache stabilizer 时不得把动态内容拼进 frozen system prompt。
3. 添加 tests/test_cache_stability.py。

PR-9：Strict JSON schema / tool schema
1. 修改 tools/schema.py、tools/registry.py、tools/strict.py：
   - strict=True 时 object 必须 additionalProperties=false。
   - strict=True 时所有 properties 必须 required。
   - repair 后必须重新 validate。
2. 添加 tests/test_strict_schema.py。

PR-10：FIM 测试和模型约束
1. fim.py 已有 max_tokens <= 4096 guard，保留。
2. 增加：
   - thinking 参数传入 FIM 时 ValueError。
   - model 必须 supports_fim=True。
   - prefix/suffix 校验。
3. 添加 tests/test_fim.py。

PR-11：审计日志、telemetry、CI
1. 增强 ToolAuditRecord，包含 run_id、tenant_id、user_id、policy_decision、capabilities、sandbox_name、output_truncated。
2. 默认不记录原始 reasoning_content、原始 secret、完整工具输出、完整高危参数。
3. 新增基础 metrics。
4. 增加 GitHub Actions CI：
   - ruff
   - mypy subset
   - pytest
   - pip-audit
   - bandit
5. 从 pyproject.toml 的 mypy ignore_errors 中优先移除 policy/security/tools/sandbox/models/usage/cost。

所有改动必须满足：
- 默认只启用 calculate。
- 没有 policy 的工具默认拒绝或 requires approval。
- dangerous_tools=True 只能兼容旧用户，必须 warning。
- 文件、网络、SQL、Python、MCP 都必须受 policy enforcement。
- Python code execution 没有 sandbox 必须拒绝。
- DeepSeek reasoning_content tool-call 协议不能破坏。
- cache compression 不能改变第一条 system message。
- pytest 全部通过。
```

---

# 16. 最终落地优先级

最推荐的执行顺序：

```text
第 1 周：
PR-0、PR-1、PR-2
把 policy enforcement 打穿。

第 2 周：
PR-3、PR-4、PR-5
把 dangerous builtins、SSRF、MCP 这几个最大攻击面处理掉。

第 3 周：
PR-6、PR-7、PR-8、PR-9
把 DeepSeek-native 的模型、usage、thinking、cache、strict schema 做成真正优势。

第 4 周：
PR-10、PR-11
补审计、telemetry、CI、typing、发布纪律。
```

最重要的不是一次性做完所有功能，而是先保证这条安全不变量成立：

```text
任何模型生成的 tool call，都必须经过：
schema validation -> policy authorization -> approval/sandbox -> audited execution -> untrusted output wrapping
```

只要这条链路打穿，SeekFlow 才有资格继续往“极致 DeepSeek Agent Runtime”发展。当前它已经有不错的模块雏形，但必须从“安全组件存在”升级为“安全策略不可绕过”。

[1]: https://github.com/WYZAAACCC/SeekFlow "GitHub - WYZAAACCC/SeekFlow: DeepSeek-native agent framework with production-grade reliability · GitHub"
[2]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/types.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/executor.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/runtime.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/agent/builtins.py "raw.githubusercontent.com"
[6]: https://api-docs.deepseek.com/quick_start/pricing "Models & Pricing | DeepSeek API Docs"
[7]: https://api-docs.deepseek.com/guides/thinking_mode "Thinking Mode | DeepSeek API Docs"
[8]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/security.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/sandbox.py "raw.githubusercontent.com"
[10]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/client.py "raw.githubusercontent.com"
[11]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/cache.py "raw.githubusercontent.com"
[12]: https://api-docs.deepseek.com/guides/tool_calls "Tool Calls | DeepSeek API Docs"
[13]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/fim.py "raw.githubusercontent.com"
[14]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/pyproject.toml "raw.githubusercontent.com"
