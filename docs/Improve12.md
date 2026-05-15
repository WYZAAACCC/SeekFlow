# SeekFlow → 完全半生产级工程修复方案 RFC

下面这份可以直接交给 Claude Code 执行。它基于最新已推送代码、作者 PR3+PR0 报告，以及我上一轮审核结论整理。目标不是继续堆功能，而是把当前“半生产候选级”推进到**真正可声明的 Level 2 完全半生产级**。

---

# 0. 当前最重要判断

SeekFlow 最新代码已经引入了 `runners.py`、`planner.py`、`ProcessRunner`、runner 执行链和 schema validation，这是正确方向。报告也显示 PR3 新增了 runner timeout、runner selection、executor no-direct-bypass 等测试，测试状态变为 `830 passed / 52 skipped / 53 xfailed / 0 failed`。

但当前代码距离“完全半生产级”仍有几个硬阻塞：

1. **`planner.py` 访问 `policy.runner` / `policy.trusted`，但最新 `types.py` 中 `ToolPolicy` 没有这两个字段。** 这会导致 runner 规划路径运行时崩溃或代码状态不一致。`planner.py` 已直接使用 `policy.runner` 和 `policy.trusted`，而 `types.py` 当前 `ToolPolicy` 只列出 capabilities、risk、timeout、max_input/output、parallel_safe、approval、domains、workspace、path/url params 等字段。([GitHub][1])

2. **`container` runner 仍 fallback 到 `ProcessRunner`。** `planner.py` 把 `code_exec/destructive` 路由到 `"container"`，但 `executor._runner_for()` 对 `"container"` 仍返回 `ProcessRunner()`，注释也写着 `TODO: wire ContainerSandbox when ready`。这意味着高危工具没有真实容器隔离。([GitHub][1])

3. **pickle 失败时 read 工具自动 fallback 到 `InProcessRunner`。** 当前 executor 在 ProcessRunner 出现 pickle/serialization error 时，只要 risk 是 read，就会降级为 in-process。这会让不可序列化的 untrusted read 工具绕过进程隔离。([GitHub][2])

4. **Policy、schema、resource limit、cache 顺序仍未完全闭环。** 当前 executor 是 policy 后 cache lookup，然后才 coerce/schema validate；这意味着 cache hit 理论上可能绕过 schema validation。executor 已接入 `validate_tool_arguments()`，但当前 validation 只是按传入 schema 校验，没有看到默认 close object schema 的逻辑。([GitHub][2])

5. **README / pyproject 与真实能力严重不一致。** README 仍写 `v0.2.5-dev`、security-hardening beta、PyPI stable 0.1.0，并且还说 per-tool timeout 通过 ThreadPoolExecutor；pyproject 仍是 `0.2.5.dev0` 和 beta classifier。([GitHub][3])

因此，本 RFC 的目标是：

> **修复这些闭环缺口，使 SeekFlow 可以诚实声明：Level 2 完全半生产级，即“非完全可信 prompt + 可信注册工具 + 有限网络/文件访问 + 强制 policy + process timeout isolation + 禁用未隔离高危工具”。**

---

# 1. 半生产级目标边界

完成本方案后，SeekFlow 可以支持：

```text
Level 0: 本地可信脚本
Level 1: 内部可信用户 + 可信工具
Level 2: 非完全可信 prompt + 可信注册工具 + 有限网络/文件访问
```

仍不应支持：

```text
Level 3: 非可信第三方工具 / 非可信 MCP / 任意插件市场
Level 4: 多租户 SaaS / 强租户隔离 / 合规审计平台
```

这一区分必须写入 README、SECURITY.md 和 docs/security/levels.md。不要把 ProcessRunner 宣传为安全沙箱。ProcessRunner 是 **timeout isolation / crash isolation**，不是完整安全隔离。

---

# 2. PR 总览

建议按 10 个 PR 执行，每个 PR 可独立测试。

| PR    | 目标                                                 | 是否阻塞半生产 |
| ----- | -------------------------------------------------- | ------- |
| PR-1  | 修复 ToolPolicy 契约不一致                                | P0      |
| PR-2  | container runner fail-closed / 真 ContainerRunner   | P0      |
| PR-3  | 禁止 untrusted pickle fallback                       | P0      |
| PR-4  | PolicyEngine 语义收口                                  | P0/P1   |
| PR-5  | Schema validation close object schema + cache 顺序修复 | P1      |
| PR-6  | Resource limits 强制执行                               | P1      |
| PR-7  | Retry / side-effect 幂等控制                           | P1      |
| PR-8  | ProcessRunner 强化                                   | P1      |
| PR-9  | xfail 收敛 + CI 半生产闸门                                | P1      |
| PR-10 | 文档、版本、发布状态同步                                       | P1      |

---

# PR-1：修复 `ToolPolicy` 契约不一致

## 问题

`planner.py` 已经依赖：

```python
policy.runner
policy.trusted
```

但当前 `types.py` 中 `ToolPolicy` 没有这两个字段。`ToolPolicy` 当前只有 capabilities、risk、timeout、max input/output、parallel_safe、requires_approval、allowed_domains、workspace_root、path_params、url_params。([GitHub][1])

这属于 P0。即使测试报告说通过，源码层面也必须修，否则 runner 规划路径存在运行时崩溃风险。

## 修改文件

```text
src/seekflow/types.py
src/seekflow/tools/planner.py
tests/tools/test_runner_selection.py
tests/test_types_policy_contract.py
```

## 代码修改

在 `types.py` 中增加：

```python
RunnerKind = Literal["auto", "in_process", "process", "container"]

class ToolPolicy(BaseModel):
    capabilities: set[str] = Field(default_factory=set)
    risk: RiskLevel = "read"
    timeout_s: float = 30.0
    max_input_bytes: int = 1_000_000
    max_output_bytes: int = 100_000
    parallel_safe: bool = False
    requires_approval: bool = False
    allowed_domains: set[str] = Field(default_factory=set)
    workspace_root: Path | None = None
    path_params: frozenset[str] = Field(default_factory=frozenset)
    url_params: frozenset[str] = Field(default_factory=frozenset)

    # New semi-production runner contract
    runner: RunnerKind = "auto"
    trusted: bool = False

    # Optional but recommended; used by PR-7
    idempotent: bool = False

    # Optional but recommended; used by PR-3
    allow_in_process_fallback: bool = False
```

## 设计原则

`trusted=True` 的含义必须非常严格：

> 该工具可在宿主进程直接运行，工具作者承诺它不会阻塞、不会越权、不会访问未授权资源、不会修改全局状态、不会泄露敏感信息。

因此，`trusted=True` 不等于“工具输出可信”，而是“工具执行本身可信”。

## 测试

```python
def test_tool_policy_has_runner_and_trusted_fields():
    p = ToolPolicy()
    assert p.runner == "auto"
    assert p.trusted is False

def test_tool_policy_rejects_invalid_runner():
    with pytest.raises(ValidationError):
        ToolPolicy(runner="thread")

def test_planner_can_access_runner_and_trusted():
    p = ToolPolicy(risk="read", trusted=True, parallel_safe=True)
    td = ToolDefinition(name="x", description="", parameters={}, func=lambda: 1, policy=p)
    plan = plan_execution(td, timeout=1.0)
    assert plan.runner == "in_process"
```

## 验收标准

```text
- ToolPolicy.runner 存在并通过 pydantic 校验
- ToolPolicy.trusted 存在
- planner.py 不再依赖不存在字段
- runner selection tests 全部通过
```

---

# PR-2：`container` runner 必须 fail-closed，禁止 fallback 到 ProcessRunner

## 问题

当前 `planner.py` 把 `code_exec/destructive` 规划为 `"container"`，但 `executor._runner_for()` 对 `"container"` 返回 `ProcessRunner()`。这会让 code execution / destructive tool 仅在普通子进程中执行，而非真实容器隔离。([GitHub][1])

`ProcessRunner` 只能提供 timeout isolation，不能阻止工具访问宿主文件、环境变量、网络或工作目录。`sandbox.py` 中 `ContainerSandbox` 已经具备 Docker 参数，如 `--network none`、`--read-only`、tmpfs、cap drop、no-new-privileges、pids/memory/cpu/user/ulimit 等，这才是 code_exec/destructive 应该使用的隔离方向。([GitHub][4])

## 修改文件

```text
src/seekflow/tools/executor.py
src/seekflow/tools/runners.py
src/seekflow/tools/container_runner.py
src/seekflow/sandbox.py
tests/tools/test_container_runner_fail_closed.py
tests/tools/test_runner_selection.py
```

## 方案 A：短期半生产级，container 无实现时直接拒绝

这是最快、最安全的半生产修复。

修改 `_runner_for()`：

```python
class RunnerUnavailableError(RuntimeError):
    pass

def _runner_for(self, plan):
    from seekflow.tools.runners import InProcessRunner, ProcessRunner

    if plan.runner == "in_process":
        return InProcessRunner()

    if plan.runner == "process":
        return ProcessRunner()

    if plan.runner == "container":
        # No fallback. High-risk tools must not silently downgrade.
        if self.sandbox is None:
            raise RunnerUnavailableError(
                "Container runner required, but no sandbox configured."
            )

        if getattr(self.sandbox, "name", "") != "container":
            raise RunnerUnavailableError(
                f"Container runner required, got sandbox={getattr(self.sandbox, 'name', None)}."
            )

        from seekflow.tools.container_runner import ContainerRunner
        return ContainerRunner(self.sandbox)

    raise RunnerUnavailableError(f"Unknown runner: {plan.runner}")
```

在 `execute()` 中捕获：

```python
try:
    runner = self._runner_for(plan)
except RunnerUnavailableError as e:
    elapsed = int((time.time() - start) * 1000)
    self._record_audit(
        tool_def,
        tool_call.id or "",
        arguments,
        result=None,
        latency_ms=elapsed,
        ok=False,
        error=str(e),
        policy_decision=policy_decision,
        policy_reason=policy_reason,
        risk=tool_def.policy.risk if tool_def.policy else "destructive",
        runner_name=plan.runner,
    )
    return ToolExecutionResult(
        tool_call_id=tool_call.id,
        name=tool_call.name,
        arguments=arguments,
        ok=False,
        error=f"Runner unavailable: {e}",
        elapsed_ms=elapsed,
    )
```

## 方案 B：实现最小 `ContainerRunner`

如果工具是 code-exec 类，建议 tool function 不直接执行，而是返回或携带 code spec。短期可以支持两种方式：

```python
# 方式 1：tool metadata 中声明 code string builder
tool_def.metadata["execution_type"] = "code"
tool_def.metadata["code_template"] = "..."

# 方式 2：tool function 返回 code string，不直接执行
result = func(**arguments)
if isinstance(result, CodeExecutionRequest):
    sandbox.execute(result.code, timeout=...)
```

建议新增：

```python
@dataclass(frozen=True)
class CodeExecutionRequest:
    code: str
    env: dict[str, str] | None = None
```

`ContainerRunner`：

```python
class ContainerRunner:
    name = "container"

    def __init__(self, sandbox):
        self.sandbox = sandbox

    def run(self, func, arguments: dict, timeout_s: float) -> ToolRunResult:
        start = time.monotonic()

        try:
            request = func(**arguments)

            if isinstance(request, CodeExecutionRequest):
                code = request.code
                env = request.env
            elif isinstance(request, str):
                # Only allow this for explicitly code tools
                code = request
                env = None
            else:
                return ToolRunResult(
                    ok=False,
                    error="ContainerRunner requires CodeExecutionRequest or code string",
                    runner_name=self.name,
                    elapsed_ms=int((time.monotonic() - start) * 1000),
                )

            sandbox_result = self.sandbox.execute(code, timeout=timeout_s, env=env)

            return ToolRunResult(
                ok=sandbox_result.ok,
                result=sandbox_result.stdout,
                error=sandbox_result.error or sandbox_result.stderr,
                runner_name=self.name,
                elapsed_ms=sandbox_result.elapsed_ms,
                killed="timed out" in (sandbox_result.error or "").lower(),
            )

        except Exception as e:
            return ToolRunResult(
                ok=False,
                error=str(e),
                runner_name=self.name,
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
```

## 测试

```python
def test_code_exec_without_container_denied():
    ...

def test_destructive_without_container_denied():
    ...

def test_container_never_falls_back_to_process():
    ...

def test_container_sandbox_is_invoked_when_configured():
    ...

def test_container_runner_returns_error_for_plain_python_callable():
    ...
```

## 验收标准

```text
- code_exec/destructive 没有真实 container 时必须拒绝
- _runner_for("container") 不得返回 ProcessRunner
- audit 记录 runner_name="container" 和错误原因
- README 明确 ProcessRunner 不是 sandbox
```

---

# PR-3：禁止 untrusted pickle fallback 到 InProcessRunner

## 问题

当前 executor 在 runner 报 pickle/serialization 错误时，只要 risk 是 read，就自动 fallback 到 `InProcessRunner`。这会让不可 pickle 的 untrusted read 工具回到宿主进程运行，从而绕过 process isolation。([GitHub][2])

## 修改文件

```text
src/seekflow/tools/executor.py
src/seekflow/types.py
tests/tools/test_pickle_fallback.py
```

## 新规则

只允许以下条件同时满足时 fallback：

```python
allow_fallback = (
    policy is not None
    and policy.risk == "read"
    and policy.trusted is True
    and policy.allow_in_process_fallback is True
    and plan.runner != "in_process"
)
```

否则返回明确错误：

```python
if _is_pickle_error(str(e)):
    policy = tool_def.policy
    allow_fallback = (
        policy is not None
        and policy.risk == "read"
        and policy.trusted is True
        and getattr(policy, "allow_in_process_fallback", False) is True
    )

    if allow_fallback:
        fallback = InProcessRunner()
        run_result = fallback.run(tool_def.func, arguments, plan.timeout_s)
        fallback_used = True
        break

    last_error = RuntimeError(
        "Tool is not pickleable and cannot run in ProcessRunner. "
        "Use a module-level function, or explicitly set "
        "ToolPolicy(trusted=True, runner='in_process') for trusted local-only tools."
    )
    break
```

## audit 增强

`ToolAuditRecord` 增加：

```python
fallback_used: bool = False
fallback_reason: str = ""
runner_plan: str = ""
```

## 测试

```python
def test_unpickleable_untrusted_read_tool_denied():
    ...

def test_unpickleable_read_tool_does_not_auto_fallback():
    ...

def test_unpickleable_trusted_explicit_fallback_allowed():
    ...

def test_unpickleable_network_tool_never_fallbacks():
    ...

def test_pickle_fallback_records_audit():
    ...
```

## 验收标准

```text
- untrusted read 工具不可 pickle 时拒绝
- trusted=True + allow_in_process_fallback=True 才允许 fallback
- network/write/code_exec/destructive 永不 fallback 到 in_process
```

---

# PR-4：PolicyEngine 语义收口

## 问题 1：无 context 时 capability gate 不完整

当前 policy 中 capability gate 依赖 `has_context`。如果没有 context，missing capability 可能不会触发拒绝。半生产级应该把 `context=None` 视为 conservative context，而不是弱化检查。([GitHub][5])

## 问题 2：dict context 下 path/url 校验可能使用不到 normalized root/domains

policy 前面已经 normalize 了 dict context 的 `workspace_root` / `allowed_domains`，但后续 path/url 参数校验又重新从 context 读取，并排除了 dict context。这会造成安全语义不一致。

## 修改文件

```text
src/seekflow/policy.py
tests/security/test_policy_fail_closed.py
tests/test_policy.py
```

## 修改方案

在 `authorize()` 开头统一生成 normalized context：

```python
@dataclass(frozen=True)
class _NormalizedPolicyContext:
    dangerous_tools_enabled: bool
    allowed_capabilities: set[str]
    max_risk: str
    workspace_root: Any | None
    allowed_domains: set[str]
    sandbox: Any | None
    run_id: str | None = None


def _normalize_context(context) -> _NormalizedPolicyContext:
    if context is None:
        return _NormalizedPolicyContext(
            dangerous_tools_enabled=False,
            allowed_capabilities={"read"},
            max_risk="read",
            workspace_root=None,
            allowed_domains=set(),
            sandbox=None,
        )

    if isinstance(context, dict):
        warnings.warn(
            "dict policy context is deprecated; use ToolExecutionContext",
            DeprecationWarning,
            stacklevel=2,
        )
        return _NormalizedPolicyContext(
            dangerous_tools_enabled=context.get("dangerous_tools_enabled", False),
            allowed_capabilities=set(context.get("allowed_capabilities", {"read"})),
            max_risk=context.get("max_risk", "read"),
            workspace_root=context.get("workspace_root"),
            allowed_domains=set(context.get("allowed_domains", set())),
            sandbox=context.get("sandbox"),
            run_id=context.get("run_id"),
        )

    return _NormalizedPolicyContext(
        dangerous_tools_enabled=getattr(context, "dangerous_tools_enabled", False),
        allowed_capabilities=set(getattr(context, "allowed_capabilities", {"read"})),
        max_risk=getattr(context, "max_risk", "read"),
        workspace_root=getattr(context, "workspace_root", None),
        allowed_domains=set(getattr(context, "allowed_domains", set())),
        sandbox=getattr(context, "sandbox", None),
        run_id=getattr(context, "run_id", None),
    )
```

然后全部逻辑只使用 `ctx`：

```python
ctx = _normalize_context(context)

missing = policy.capabilities - ctx.allowed_capabilities
if missing:
    return PolicyDecision(False, f"Missing capabilities: {sorted(missing)}")

effective_root = policy.workspace_root or ctx.workspace_root
effective_domains = policy.allowed_domains or ctx.allowed_domains
```

## network URL 校验统一

当前 `network.public_http` 逻辑应改成只使用 `policy.url_params or {"url"}`：

```python
if "network.public_http" in policy.capabilities:
    domains = policy.allowed_domains or ctx.allowed_domains
    if not domains:
        return PolicyDecision(False, "network.public_http requires non-empty allowed_domains")

    url_params = policy.url_params or frozenset({"url"})
    for param in url_params:
        value = args.get(param)
        if not isinstance(value, str) or not value:
            return PolicyDecision(False, f"network URL parameter '{param}' is required")

        try:
            validate_url_strict(value, NetworkPolicy(allowed_domains=domains))
        except ValueError as e:
            return PolicyDecision(False, f"SSRF blocked for '{param}': {e}")
```

## filesystem path 校验统一

```python
if "filesystem.read" in policy.capabilities or "filesystem.write" in policy.capabilities:
    root = policy.workspace_root or ctx.workspace_root
    if root is None:
        return PolicyDecision(False, "filesystem access requires workspace_root")

    for param in policy.path_params:
        if param in args:
            try:
                safe_join(root, args[param])
            except ValueError as e:
                return PolicyDecision(False, f"path traversal blocked for '{param}': {e}")
```

## 测试

```python
def test_no_context_missing_capability_denied():
    ...

def test_none_context_allows_only_plain_read_policy():
    ...

def test_dict_context_capability_gate_enforced():
    ...

def test_dict_context_workspace_used_for_path_params():
    ...

def test_dict_context_domains_used_for_url_params():
    ...

def test_network_uses_url_params_not_hardcoded_url():
    ...

def test_multiple_url_params_all_validated():
    ...
```

## 验收标准

```text
- context=None 不再弱化 capability gate
- dict context 只作为 deprecated 输入，不改变安全语义
- 所有 url_params 全量 strict validate
- 所有 path_params 全量 safe_join validate
```

---

# PR-5：Schema validation 默认 close object schema，并调整 cache 顺序

## 问题

当前 executor 是：

```text
policy → cache lookup → coerce → schema validate → execute
```

这会让 cache hit 可能绕过 schema validation。executor 当前确实在 cache lookup 后才 coerce 和 validate。([GitHub][2])

同时，`validate_tool_arguments()` 只是按传入 schema 做 Draft202012 校验；JSON Schema 默认允许额外字段，除非 `additionalProperties=false`。([GitHub][6])

## 修改文件

```text
src/seekflow/tools/validation.py
src/seekflow/tools/executor.py
tests/tools/test_argument_validation.py
tests/tools/test_executor_cache_schema_order.py
```

## 目标执行顺序

```text
parse / repair
→ input size limit
→ coerce
→ close schema
→ schema validate
→ policy authorize
→ approval
→ cache lookup
→ runner execute
→ output limit
→ redact / wrap / truncate
→ cache write
→ audit
```

注意：policy 放在 schema validation 之后更稳，因为 policy 应该看到最终 coerced/validated args。若担心 policy 应在所有重资源操作前执行，可以先做一个轻量 pre-policy；但半生产最清晰做法是：

```text
parse → input limit → coerce → schema validate → policy
```

## close schema 实现

```python
def close_object_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a copy where object schemas default to additionalProperties=False."""
    import copy

    def visit(node: Any) -> Any:
        if isinstance(node, dict):
            node = copy.deepcopy(node)

            if node.get("type") == "object" or "properties" in node:
                node.setdefault("type", "object")
                node.setdefault("additionalProperties", False)

                props = node.get("properties", {})
                for key, sub in list(props.items()):
                    props[key] = visit(sub)

            if node.get("type") == "array" and "items" in node:
                node["items"] = visit(node["items"])

            for key in ("anyOf", "oneOf", "allOf"):
                if key in node and isinstance(node[key], list):
                    node[key] = [visit(x) for x in node[key]]

            return node

        return node

    return visit(schema)
```

`validate_tool_arguments()`：

```python
def validate_tool_arguments(schema, arguments, *, close_schema: bool = True):
    if close_schema:
        schema = close_object_schema(schema)
    validator = Draft202012Validator(schema)
    ...
```

## cache 顺序修复

把 cache lookup 从当前 policy 后、coerce/schema 前，移动到 schema validation + policy + approval 后。

```python
# After schema validation and policy approval
if self._cache is not None and policy.risk == "read":
    cache_key = make_cache_key(tool_call.name, arguments)
    cached = self._cache.get(cache_key)
    if cached is not None:
        ...
```

## 测试

```python
def test_extra_arg_denied_when_schema_omits_additional_properties():
    ...

def test_nested_extra_arg_denied():
    ...

def test_cache_hit_does_not_bypass_schema_validation():
    ...

def test_schema_validation_before_policy_uses_coerced_args():
    ...

def test_explicit_additional_properties_true_requires_opt_in():
    ...
```

## 验收标准

```text
- hallucinated extra args 默认拒绝
- nested object extra args 默认拒绝
- cache hit 不能绕过 schema validation
- validation errors 不调用工具函数
```

---

# PR-6：`max_input_bytes` / `max_output_bytes` 强制执行

## 问题

`ToolPolicy` 已有 `max_input_bytes` / `max_output_bytes` 字段，但当前 executor 主要靠最终 `_maybe_truncate()`；这不能防止大输入进入 coerce/schema/policy，也不能防止子进程把巨大对象通过 Queue 返回给父进程。`ToolPolicy` 字段在 `types.py` 中存在。([GitHub][7])

## 修改文件

```text
src/seekflow/tools/limits.py
src/seekflow/tools/runners.py
src/seekflow/tools/executor.py
tests/tools/test_tool_resource_limits.py
```

## 新增 `limits.py`

```python
class ToolInputTooLarge(ValueError):
    pass

class ToolOutputTooLarge(ValueError):
    pass

def estimate_json_bytes(value) -> int:
    try:
        raw = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        raw = str(value)
    return len(raw.encode("utf-8"))

def enforce_input_limit(arguments: dict, max_bytes: int) -> None:
    size = estimate_json_bytes(arguments)
    if size > max_bytes:
        raise ToolInputTooLarge(f"tool arguments too large: {size} > {max_bytes}")

def serialize_bounded(value, max_bytes: int) -> tuple[str, bool]:
    if isinstance(value, str):
        raw = value
    else:
        raw = json.dumps(value, ensure_ascii=False, default=str)

    b = raw.encode("utf-8")
    if len(b) <= max_bytes:
        return raw, False

    # Safe byte truncation
    truncated = b[:max_bytes].decode("utf-8", errors="ignore")
    return truncated + "\n...[truncated by max_output_bytes]...", True
```

## executor 接入

在 parse/repair 后立即：

```python
policy = tool_def.policy
if policy:
    enforce_input_limit(arguments, policy.max_input_bytes)
```

runner 返回后、redaction 前：

```python
max_out = policy.max_output_bytes if policy else 100_000
raw_serialized, output_truncated = serialize_bounded(run_result.result, max_out)
```

后续 redaction 和 untrusted wrap 都使用 `raw_serialized`，不要再对原始巨大对象做 `json.dumps()`。

## ProcessRunner 子进程内 bounded serialization

更安全做法是在子进程内就限制输出：

```python
def _run_in_subprocess(func, args, queue, max_output_bytes):
    try:
        result = func(**args)
        serialized, truncated = serialize_bounded(result, max_output_bytes)
        queue.put({
            "ok": True,
            "result": serialized,
            "output_truncated": truncated,
        })
    except Exception as e:
        queue.put({"ok": False, "error": str(e)})
```

`ProcessRunner.run()` 接收 `max_output_bytes`。

为避免大对象先进入父进程，runner 接口建议改为：

```python
def run(self, func, arguments: dict, timeout_s: float, *, max_output_bytes: int = 100_000) -> ToolRunResult:
    ...
```

## 测试

```python
def test_input_too_large_denied_before_runner_called():
    ...

def test_output_too_large_truncated_before_redaction():
    ...

def test_process_runner_bounds_large_result_in_child():
    ...

def test_audit_hash_uses_bounded_output():
    ...

def test_binary_like_output_safe_truncation():
    ...
```

## 验收标准

```text
- 超大输入不会进入 runner
- 超大输出不会完整进入父进程、redaction、audit、模型上下文
- output_truncated 被记录到 repair_notes 或 audit
```

---

# PR-7：side-effect retry 必须显式幂等

## 问题

executor 读取 `metadata["max_retries"]`，但没有按 risk 限制。对 read 工具 retry 可以接受；对 write/network/destructive 默认 retry 会造成重复副作用。executor 当前直接读取 metadata 中的 max_retries/retry_delay。([GitHub][2])

## 修改文件

```text
src/seekflow/types.py
src/seekflow/tools/executor.py
tests/tools/test_retry_side_effects.py
```

## 规则

新增或使用 `ToolPolicy.idempotent`：

```python
if policy.risk == "read":
    effective_max_retries = max_retries
elif policy.idempotent:
    effective_max_retries = max_retries
else:
    effective_max_retries = 0
```

对于 network 工具：

```text
GET-like、声明 idempotent=True 的工具可以 retry
POST / write / delete / destructive 默认不 retry
```

## 测试

```python
def test_read_tool_can_retry():
    ...

def test_write_tool_not_retried_by_default():
    ...

def test_network_tool_not_retried_unless_idempotent():
    ...

def test_destructive_tool_never_retried_without_explicit_idempotent():
    ...
```

## 验收标准

```text
- write/network/destructive 默认只执行一次
- idempotent=True 才允许 retry
- audit 记录 attempts
```

---

# PR-8：ProcessRunner 强化

## 问题

`ProcessRunner` 已经能 spawn 子进程并 timeout kill，这是重大进步。当前实现使用 `multiprocessing.get_context("spawn")`，超时后 terminate、grace、kill，完成后从 queue 取结果。([GitHub][8])

但作为半生产基础隔离，还应增强：

* queue size 限制；
* queue get timeout；
* 子进程 result bounded serialization；
* 记录 exitcode；
* 关闭 queue；
* 清晰区分 killed / crashed / no result；
* audit 中记录 runner exit info。

## 修改文件

```text
src/seekflow/tools/runners.py
src/seekflow/tools/executor.py
tests/tools/test_process_runner_hardening.py
```

## ToolRunResult 增强

```python
@dataclass
class ToolRunResult:
    ok: bool
    result: Any = None
    error: str | None = None
    killed: bool = False
    runner_name: str = ""
    elapsed_ms: int = 0
    exit_code: int | None = None
    output_truncated: bool = False
```

## queue 安全

```python
queue: multiprocessing.Queue = ctx.Queue(maxsize=1)
...
try:
    data = queue.get(timeout=0.2)
except queue.Empty:
    return ToolRunResult(
        ok=False,
        error=f"Tool process exited with code {proc.exitcode} without result",
        exit_code=proc.exitcode,
        runner_name=self.name,
        elapsed_ms=elapsed,
    )
finally:
    queue.close()
    queue.join_thread()
    proc.close()
```

## 测试

```python
def test_process_runner_records_exit_code_on_crash():
    ...

def test_process_runner_queue_empty_does_not_hang():
    ...

def test_process_runner_closes_queue():
    ...

def test_process_runner_large_output_bounded():
    ...
```

---

# PR-9：xfail 收敛与 CI 半生产闸门

## 问题

作者报告显示当前是 `830 passed / 52 skipped / 53 xfailed / 0 failed`。形式上没有 failed，但 53 个 xfailed 中包括 runtime、thinking、tool_executor、v3_agent、version consistency 等核心路径。

这不能作为“完全半生产级”的质量基线。

## 修改文件

```text
pytest.ini 或 pyproject.toml
tests/*
.github/workflows/ci.yml
docs/production-readiness.md
```

## 规则

核心路径不允许 xfail：

```text
tests/test_runtime.py
tests/test_tool_executor.py
tests/test_policy.py
tests/test_thinking.py
tests/deepseek/*
tests/tools/*
tests/security/*
tests/test_version_consistency.py
```

允许 xfail 的只应是：

```text
legacy crew/checkpoint
deprecated compatibility
non-core benchmark
known external environment tests
```

所有 xfail 必须：

```python
@pytest.mark.xfail(strict=True, reason="issue #123: precise reason")
```

禁止：

```python
reason="pre-existing: user business changes"
```

## CI 加检测脚本

新增 `scripts/check_xfail_policy.py`：

```python
import ast
from pathlib import Path

CORE_PATHS = [
    "tests/test_runtime.py",
    "tests/test_tool_executor.py",
    "tests/test_policy.py",
    "tests/test_thinking.py",
    "tests/tools/",
    "tests/security/",
    "tests/deepseek/",
]

def is_core(path: str) -> bool:
    return any(path == p or path.startswith(p) for p in CORE_PATHS)

bad = []

for file in Path("tests").rglob("test_*.py"):
    text = file.read_text()
    if "xfail" not in text:
        continue

    if is_core(str(file)):
        bad.append(f"{file}: xfail not allowed in core tests")

    if "strict=True" not in text:
        bad.append(f"{file}: xfail must be strict=True")

    if "issue #" not in text and "issue#" not in text:
        bad.append(f"{file}: xfail reason must include issue id")

if bad:
    raise SystemExit("\n".join(bad))
```

CI：

```yaml
- run: python scripts/check_xfail_policy.py
- run: pytest
```

## 验收标准

```text
- 核心路径 0 xfail
- 所有 xfail strict=True
- 所有 xfail 有 issue id
- version consistency 不允许 xfail
```

---

# PR-10：文档、版本、发布状态同步

## 问题

README 仍是 `v0.2.5-dev`，说 main 是 security-hardening beta，PyPI stable 是 0.1.0，同时还说 per-tool timeout 通过 ThreadPoolExecutor；pyproject 仍是 `0.2.5.dev0` 和 beta classifier。([GitHub][3])

这会严重误导使用者，也降低框架可信度。

## 修改文件

```text
README.md
pyproject.toml
docs/SECURITY.md
docs/security/levels.md
docs/production-readiness.md
CHANGELOG.md
```

## README 状态区改成

```markdown
# SeekFlow v0.3.6 — Level 2 Semi-production Candidate

SeekFlow is a DeepSeek-native secure tool runtime.

Current supported security levels:

| Level | Status | Scope |
|---|---|---|
| Level 0 | Supported | Local trusted scripts |
| Level 1 | Supported | Internal trusted tools |
| Level 2 | Supported after enabling PolicyEngine + ToolPolicy + ProcessRunner | Non-fully-trusted prompts with trusted registered tools |
| Level 3 | Experimental / not supported by default | Untrusted third-party tools, untrusted MCP |
| Level 4 | Not supported | Multi-tenant SaaS |

Important boundaries:

- ProcessRunner provides hard timeout / crash isolation, not full sandboxing.
- Code execution and destructive tools require ContainerRunner / ContainerSandbox.
- Without ContainerSandbox, code_exec/destructive tools are denied.
- Prompt cache is best-effort and cannot be guaranteed.
```

## Security Architecture 更新

把 “Per-tool timeout via ThreadPoolExecutor” 改成：

```text
Per-tool execution:
- InProcessRunner: trusted read-only tools only; no hard timeout.
- ProcessRunner: default for untrusted read/network/write; hard timeout via child process kill.
- ContainerRunner: required for code_exec/destructive; Docker isolation.
```

## pyproject

如果准备发布半生产候选：

```toml
version = "0.3.6"
description = "DeepSeek-native secure tool runtime — Level 2 semi-production candidate"
classifiers = [
  "Development Status :: 4 - Beta",
  ...
]
```

如果还不准备发布，就不要在 commit message / README 中声称 v0.3.5 semi-production。

## 验收标准

```text
- README 版本 == pyproject 版本
- README 不再提 ThreadPoolExecutor timeout
- SECURITY.md 明确 ProcessRunner 不是 sandbox
- docs/security/levels.md 明确 Level 2 支持边界
```

---

# 3. 最终 Claude Code 执行提示词

可以把下面这一段直接给 Claude：

```text
你要把 SeekFlow 最新 main 从“半生产候选级”推进到“完全半生产级 Level 2”。

请基于当前代码直接修改，不要重写已有模块。当前已有 runners.py、planner.py、ProcessRunner、schema validation、PolicyEngine、validate_url_strict、ContainerSandbox、NormalizedUsage 等。你的任务是补齐闭环。

必须按以下 PR 顺序完成：

PR-1 ToolPolicy 契约修复：
- types.py 中 ToolPolicy 必须增加 runner、trusted、idempotent、allow_in_process_fallback。
- planner.py 不得访问不存在字段。
- 新增 tests/test_types_policy_contract.py。

PR-2 container runner fail-closed：
- executor._runner_for("container") 不得 fallback 到 ProcessRunner。
- 没有真实 ContainerSandbox 时，code_exec/destructive 必须拒绝。
- 可新增 ContainerRunner，但短期至少必须 deny。
- 新增 test_code_exec_without_container_denied、test_container_never_falls_back_to_process。

PR-3 禁止 untrusted pickle fallback：
- 当前 read 工具 pickle error 自动 fallback 到 InProcessRunner，这不安全。
- 只有 ToolPolicy(trusted=True, allow_in_process_fallback=True) 才能 fallback。
- untrusted read 不可 pickle 必须返回错误。
- network/write/code_exec/destructive 永不 fallback。
- audit 记录 fallback_used/fallback_reason。

PR-4 PolicyEngine 收口：
- context=None 必须等价 conservative context，不得弱化 capability gate。
- dict context 统一 normalize，后续 path/url 校验必须使用 normalized workspace_root/allowed_domains。
- network.public_http 使用 policy.url_params or {"url"} 全量 validate_url_strict。
- filesystem path_params 全量 safe_join。

PR-5 Schema validation 强化：
- validate_tool_arguments 默认 close object schema，additionalProperties=false。
- nested object 也要 close。
- cache lookup 必须移动到 coerce + schema validate + policy + approval 之后。
- cache hit 不能绕过 schema validation。

PR-6 Resource limits：
- max_input_bytes 在 runner 前强制检查。
- max_output_bytes 在子进程返回前或 redaction 前强制 bounded serialization。
- 大输出不能完整进入父进程、redaction、audit 或模型上下文。

PR-7 Retry side-effect 控制：
- read 工具可 retry。
- write/network/destructive 默认不 retry。
- 只有 policy.idempotent=True 才允许 side-effect retry。
- audit 记录 attempts。

PR-8 ProcessRunner hardening：
- Queue maxsize=1。
- queue.get timeout。
- 记录 exit_code。
- close queue/join_thread/proc.close。
- 大结果 bounded serialization。
- crash/no-result 不得 hang。

PR-9 xfail 收敛：
- core runtime/executor/policy/tools/security/deepseek/thinking/version consistency 不允许 xfail。
- 所有 xfail 必须 strict=True 且 reason 包含 issue id。
- 新增 scripts/check_xfail_policy.py 并接入 CI。

PR-10 文档版本同步：
- README 和 pyproject 版本一致。
- README 不再写 ThreadPoolExecutor timeout。
- 文档明确 ProcessRunner 是 timeout isolation，不是 sandbox。
- docs/security/levels.md 明确 Level 2 支持边界，Level 3/4 不支持。

最终验收：
- pytest 无 failed。
- core tests 无 xfail。
- executor 中 container 不 fallback process。
- untrusted pickle fallback 被拒绝。
- code_exec/destructive 无 ContainerSandbox 时拒绝。
- network.public_http 无 allowed_domains 时拒绝。
- extra hallucinated args 默认 schema validation 拒绝。
- max_input_bytes/max_output_bytes 生效。
- README/pyproject/SECURITY 状态一致。
```

---

# 4. 最终 Definition of Done

完成所有 PR 后，才能声明“完全半生产级”。

```text
代码闸门：
- ToolPolicy 契约与 planner 使用一致
- executor 不直接执行 untrusted tool
- ProcessRunner 提供 hard timeout
- Container runner 不 fallback process
- code_exec/destructive 无 container 必拒绝
- unpickleable untrusted read 不 fallback in-process
- context=None 不绕过 capability
- dict context 不改变安全语义
- url_params/path_params 全量校验
- schema validation 默认 close object
- cache hit 不绕过 validation
- input/output bytes limit 生效
- side-effect retry 默认关闭

测试闸门：
- pytest 0 failed
- core tests 0 xfail
- 所有非核心 xfail strict=True + issue id
- runner timeout / container deny / pickle fallback / schema close / resource limit 都有测试

文档闸门：
- README 版本 == pyproject 版本
- README 不再宣称 ThreadPoolExecutor timeout
- SECURITY.md 写清 ProcessRunner != sandbox
- docs/security/levels.md 写清 Level 2 支持、Level 3/4 不支持
```

---

# 5. 最终评价

作者这次推送的方向是正确的：`runners.py`、`planner.py`、`ProcessRunner`、schema validation 和 runner audit 都是通向半生产级的必要基础。报告中的 PR3 改造确实切中了上一轮最大问题。

但当前代码仍有几个半生产级不能接受的断点：`ToolPolicy` 字段与 planner 契约不一致、container fallback process、untrusted pickle fallback、schema/cache/resource limit 顺序不闭环，以及文档版本严重过期。([GitHub][7])

执行完这份 RFC 后，SeekFlow 才可以从：

> 半生产候选级

跨越到：

> **完全半生产级 Level 2：非完全可信 prompt + 可信注册工具 + 强制 policy + process hard timeout + 高危工具 fail-closed。**

[1]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/planner.py "raw.githubusercontent.com"
[2]: https://github.com/WYZAAACCC/SeekFlow/raw/refs/heads/main/src/seekflow/tools/executor.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/README.md "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/sandbox.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/policy.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/validation.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/types.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/runners.py "raw.githubusercontent.com"
