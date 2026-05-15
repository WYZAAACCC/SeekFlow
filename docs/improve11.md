# SeekFlow v0.3.4 → 完全半生产级技术修复与改进方案

下面这份可以直接交给 Claude Code 执行。目标不是把 SeekFlow 做成完整企业级 SaaS，而是把它从当前“受控内部试用级 / 接近半生产级”推进到**真正稳定的半生产级**。

---

# 0. 目标定义：什么叫“完全半生产级”

本方案里的“完全半生产级”指：

> 可以在内部生产前环境中承载**非完全可信 prompt + 可信注册工具 + 有限网络访问 + 明确 workspace 文件访问 + 审计可回放**的 Agent Runtime。

它不要求达到多租户 SaaS、非可信第三方插件市场、强合规审计、跨租户隔离等 Level 4 能力。

但必须满足：

1. **工具执行不能拖死宿主进程。**
2. **高风险工具不能绕过 sandbox / runner。**
3. **网络工具默认 deny，必须 allowed domains。**
4. **文件工具必须 workspace-bound。**
5. **模型生成的 tool arguments 必须 schema validate。**
6. **dict legacy context 不能绕过 capability gate。**
7. **stream / non-stream 不应产生安全语义漂移。**
8. **trace / audit 默认不泄露 secrets、文件原文、reasoning 原文。**
9. **全量测试不能裸露失败；已知失败必须 xfail 并绑定 issue。**
10. **文档必须准确说明支持的安全等级。**

作者给出的报告显示当前基线为 `9ff7494 / v0.3.4`，测试结果仍是 `792 passed / 47 failed / 3 skipped`，并且报告自己也列出“Tool timeout 线程不杀死”“DNS rebinding TOCTOU”“Container sandbox kill on timeout”“MCP subprocess zombie”等未覆盖边缘场景。 实施报告也明确说明 improve10 中 ToolRunner 抽象、DeepSeekClientConfig、Config Linter、独立 state machine 等没有实现，其中 ToolRunner 被认为由 sandbox 层“等效”覆盖，但源码显示 executor 仍直接调用工具函数，因此这个判断需要修正。

---

# 1. 当前状态判断

## 1.1 已经达到的部分

v0.3.4 已经完成了几件重要改进：

* Agent / Runtime / Executor 之间已接入 `PolicyEngine` 和 `ToolExecutionContext`，主链路比之前完整。
* Runtime 输入不可变已修复，`messages` 先 deepcopy 再嵌入文件。实施报告记录 commit `04cd6e1` 专门修复了这个问题。
* `NormalizedUsage` 已接入 runtime，替代了手写 usage dict。实施报告记录 commit `6560397` 完成了这部分。
* cache metrics 已接入 Agent，`NormalizedUsage` 增加了 cache ratio。实施报告记录 commit `0996950` 完成了这部分。
* DeepSeek strict schema compiler、JSON output helper、cache compiler、telemetry、audit record 等模块已经存在，不需要重复造轮子。

这些改动方向正确，说明项目已经从“原型”进入“受控内部试用级”。

---

## 1.2 尚未达到完全半生产级的原因

当前仍有五个硬阻塞。

### 阻塞 1：`ToolExecutor` 仍直接执行工具函数

最新 `executor.py` 仍然使用 `ThreadPoolExecutor` 执行工具函数，或者在没有 timeout 时直接 `tool_def.func(**arguments)`；虽然 `ToolExecutor` 接收了 `sandbox`，但实际执行路径没有强制通过 sandbox / runner。源码中的执行顺序注释写了 “sandbox → execute”，但代码仍是线程池/直接调用。([GitHub][1])

这意味着：

* sandbox 抽象存在，但不是所有工具的强制执行边界；
* 自定义工具可以在宿主 Python 进程中运行；
* code/network/write/destructive 工具只要函数本身不主动调用 sandbox，就不会被隔离；
* timeout 无法强杀正在运行的线程。

这是当前最大的半生产级阻塞。

---

### 阻塞 2：`network.public_http` 空 allowed domains 仍可能放行

当前 `policy.py` 中 network 检查逻辑是：如果存在 `network.public_http` capability，会取 `policy.allowed_domains` 或 context 的 allowed domains；但只有 `domains` 非空时才调用 `validate_url_strict`。如果 domains 为空，policy 没有立即 deny。([GitHub][2])

半生产级要求：

> 任何 public HTTP 能力都必须显式 allowed domains；空 domains = deny。

否则自定义网络工具可能绕过 SSRF 默认边界。

---

### 阻塞 3：dict legacy context 仍绕过 capability gate

`policy.py` 里 capability gate 仍写着“only for proper ToolExecutionContext, not dict”，并且实际条件是 `has_context and not isinstance(context, dict) and missing` 才 deny。([GitHub][2])

这意味着 legacy dict context 仍可能绕过 capability 检查。半生产级不能有两套安全语义。

---

### 阻塞 4：工具参数缺少执行前 JSON Schema validation

DeepSeek 官方文档明确说明，tool call arguments 是模型生成的 JSON 字符串，开发者需要在执行工具前验证，因为模型可能生成无效 JSON 或 hallucinated 参数。DeepSeek API 文档也说明 tools 的 `parameters` 是 JSON Schema，strict mode 是 beta 能力。([DeepSeek API Docs][3])

当前 executor 做了 parse、repair、coerce、policy、execute，但缺少统一的 JSON Schema validation。([GitHub][1])

这会导致：

* schema 外字段可能进入工具；
* 必填字段缺失可能到工具内部才报错；
* 类型错误可能被过度 coercion；
* strict schema 只约束模型输出，不构成执行侧安全边界。

---

### 阻塞 5：47 个失败测试不能作为半生产基线

报告显示全量测试为 `792 passed / 47 failed / 3 skipped`。

即使这些失败是“已有失败”，也不能作为半生产级发布基线。半生产级要求：

* 要么全部修复；
* 要么明确 `xfail`，每个 xfail 绑定 issue、原因、修复计划；
* CI 不能裸露 failed tests。

---

# 2. 改造总原则

Claude 执行时必须遵守以下原则。

## 2.1 不重写已有好模块

不要重写：

* `NormalizedUsage`
* `DeepSeekStrictSchemaCompiler`
* `json_output.py`
* `CacheCompiler`
* `CacheStabilizer`
* `CacheSentinel`
* `RunTrace` / `StepTrace`
* `ToolAuditRecord`
* `validate_url_strict`
* `fetch_url_hardened`

现有报告显示这些模块大多已经存在，当前核心问题是**执行路径没强制接线**，而不是模块不存在。

## 2.2 接线优先，安全语义优先

必须把已有 policy、sandbox、schema、redaction、usage 模块变成强制路径。

## 2.3 半生产级不是“功能更多”，而是“默认不出事”

不要优先做：

* 多 agent；
* graph DSL；
* memory；
* 更多内置工具；
* UI；
* 平台化 durable store。

先解决：

* runner；
* hard timeout；
* fail-closed policy；
* schema validation；
* MCP timeout；
* 测试归零。

---

# 3. 目标架构

当前代码结构可以保留，但必须新增三层：

```text
ToolExecutor
  ├── ArgumentValidator
  ├── ExecutionPlanner
  └── ToolRunner
        ├── InProcessRunner
        ├── ProcessRunner
        └── ContainerRunner
```

执行链必须变成：

```text
tool_call
  → lookup tool
  → parse / repair arguments
  → coerce basic types
  → JSON Schema validate
  → policy authorize
  → approval if required
  → execution plan
  → runner selected
  → execute with hard timeout
  → serialize bounded output
  → redact secrets
  → wrap untrusted
  → truncate
  → audit
```

注意：**不允许 executor 再直接调用 `tool_def.func(**arguments)`。**

---

# 4. PR 拆分方案

建议分 8 个 PR 执行。每个 PR 都能独立测试和回滚。

---

# PR 0：建立半生产级闸门

## 目标

先把“什么叫半生产通过”写成可执行检查，避免后续改动没有验收标准。

## 修改文件

```text
docs/production-readiness.md
docs/security/levels.md
docs/security/threat-model.md
docs/security/known-limitations.md
README.md
pyproject.toml
.github/workflows/ci.yml
```

## 文档必须写清楚

```text
Level 0: 本地可信脚本
Level 1: 内部可信用户 + 可信工具
Level 2: 非完全可信 prompt + 可信注册工具
Level 3: 非可信工具 / MCP / 外部插件
Level 4: 多租户 SaaS
```

当前目标是 **Level 2 fully supported**。

## CI 闸门

半生产级 CI 必须包含：

```bash
pytest
ruff check src tests
mypy src/seekflow/usage.py src/seekflow/policy.py src/seekflow/tools src/seekflow/security src/seekflow/deepseek
```

## 失败测试处理

当前 47 个失败测试必须二选一：

1. 修复；
2. 标记 `xfail(strict=True, reason="issue #...")`。

不允许 CI 裸露 failed。

## 验收标准

```text
- docs/security/levels.md 明确当前目标 Level 2
- README 不再声称超出当前安全等级的能力
- pytest 不出现裸 failed
- 所有 xfail 都有 issue id
```

---

# PR 1：PolicyEngine 完整 fail-closed

## 目标

修复两个硬漏洞：

1. dict context 绕过 capability gate；
2. network allowed domains 为空不 deny。

## 修改文件

```text
src/seekflow/policy.py
src/seekflow/execution/context.py 或 src/seekflow/policy.py 内部
tests/security/test_policy_fail_closed.py
tests/test_policy.py
```

## 具体改法

### 1. 新增 context normalization

```python
def _normalize_context(context: Any) -> ToolExecutionContext:
    from seekflow.execution.context import ToolExecutionContext

    if isinstance(context, ToolExecutionContext):
        return context

    if isinstance(context, dict):
        warnings.warn(
            "dict policy context is deprecated; use ToolExecutionContext",
            DeprecationWarning,
            stacklevel=2,
        )
        return ToolExecutionContext(
            run_id=context.get("run_id", ""),
            dangerous_tools_enabled=context.get("dangerous_tools_enabled", False),
            allowed_capabilities=set(context.get("allowed_capabilities", {"read"})),
            max_risk=context.get("max_risk", "read"),
            workspace_root=context.get("workspace_root"),
            allowed_domains=set(context.get("allowed_domains", set())),
            sandbox=context.get("sandbox"),
        )

    return ToolExecutionContext(
        run_id="",
        dangerous_tools_enabled=False,
        allowed_capabilities={"read"},
        max_risk="read",
    )
```

如果当前项目没有统一 `ToolExecutionContext` 文件，就先在 `policy.py` 内部实现 `_NormalizedPolicyContext`，但最终建议收敛到 `execution/context.py`。

### 2. capability gate 对所有 context 生效

删除当前逻辑：

```python
if has_context and not isinstance(context, dict) and missing:
```

改成：

```python
missing = policy.capabilities - ctx.allowed_capabilities
if missing:
    return PolicyDecision(
        allowed=False,
        reason=f"Missing capabilities: {sorted(missing)}",
    )
```

### 3. network 必须 non-empty allowed domains

当前 `ToolPolicy` 已有 `allowed_domains`、`url_params`、`workspace_root` 等字段。([GitHub][4])

改成：

```python
if "network.public_http" in policy.capabilities:
    domains = set(policy.allowed_domains or ctx.allowed_domains or set())
    if not domains:
        return PolicyDecision(
            allowed=False,
            reason="network.public_http requires non-empty allowed_domains",
        )

    url_params = policy.url_params or frozenset({"url"})
    for name in url_params:
        val = args.get(name)
        if not isinstance(val, str) or not val:
            return PolicyDecision(
                allowed=False,
                reason=f"network URL parameter '{name}' is required",
            )

        try:
            validate_url_strict(val, NetworkPolicy(allowed_domains=domains))
        except ValueError as e:
            return PolicyDecision(
                allowed=False,
                reason=f"SSRF blocked: {e}",
            )
```

`validate_url_strict` / `NetworkPolicy` 已存在，且项目已有 hardened HTTP 模块，不要重写。报告也说明 `validate_url_strict` 和 `fetch_url_hardened` 已经接入部分路径。

## 新增测试

```python
def test_dict_context_missing_capability_denied():
    ...

def test_network_without_allowed_domains_denied():
    ...

def test_network_with_empty_policy_and_context_domains_denied():
    ...

def test_network_url_param_validated_for_custom_tool():
    ...

def test_none_context_allows_only_read():
    ...

def test_filesystem_without_workspace_denied():
    ...
```

## 验收标准

```text
- dict context 不能绕过 capability
- network.public_http 无 domains 必 deny
- url_params 每个 URL 都 strict validate
- 老 dict context 只保留 DeprecationWarning，不保留宽松语义
```

---

# PR 2：ArgumentValidator，执行前 JSON Schema 校验

## 目标

补齐工具调用安全边界：模型输出的 arguments 不能只 parse/repair/coerce，还必须 schema validate。

DeepSeek 文档说明 `tools[].function.parameters` 是 JSON Schema；同时 tool arguments 是模型生成的字符串，strict 也只是 beta 行为，执行端仍需验证。([DeepSeek API Docs][3])

## 修改文件

```text
src/seekflow/tools/validation.py
src/seekflow/tools/executor.py
pyproject.toml
tests/tools/test_argument_validation.py
```

## 依赖选择

如果项目已经依赖 `jsonschema`，直接使用。
如果没有，新增：

```toml
jsonschema>=4.21
```

如果不想增加依赖，则实现最小 validator 不够稳，不建议。

## 新文件：`tools/validation.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str


class ToolArgumentValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        joined = "; ".join(f"{i.path}: {i.message}" for i in issues)
        super().__init__(joined)


def validate_tool_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    if not schema:
        return

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.path))

    if errors:
        issues = [
            ValidationIssue(
                path=".".join(str(p) for p in error.path) or "$",
                message=error.message,
            )
            for error in errors
        ]
        raise ToolArgumentValidationError(issues)
```

## executor 接入位置

当前 executor 顺序是 parse/repair → policy → cache → coerce → execute。([GitHub][1])

建议改成：

```text
parse/repair
→ coerce
→ schema validate
→ policy authorize
→ cache lookup
→ execute
```

为什么 policy 放 schema 后面？

* policy 应该基于最终 sanitized / coerced / validated args 做判断；
* 否则 path/url validation 可能看到的是未规范化参数；
* 但如果担心恶意超大 args 先打爆 validator，应先做 input bytes limit。

最终顺序建议：

```text
parse/repair
→ input size limit
→ coerce
→ schema validate
→ policy authorize
→ approval
→ cache lookup
→ execute
```

## executor 伪代码

```python
arguments = parse_or_repair(tool_call.arguments)

_check_input_size(arguments, tool_def.policy)

if self.repair:
    arguments, coercion_notes = coerce_arguments(arguments, tool_def.parameters)

try:
    validate_tool_arguments(tool_def.parameters, arguments)
except ToolArgumentValidationError as e:
    return ToolExecutionResult(
        ok=False,
        error=f"Argument validation failed: {e}",
        ...
    )

decision = self.policy_engine.authorize(tool_def, arguments, context=self.context)
```

## 新增测试

```python
def test_missing_required_argument_denied_before_func_called():
    ...

def test_extra_argument_denied_when_additional_properties_false():
    ...

def test_wrong_type_denied_after_coercion_attempt():
    ...

def test_nested_schema_validation():
    ...

def test_enum_validation():
    ...

def test_validation_error_is_returned_as_tool_error_not_exception():
    ...
```

## 验收标准

```text
- 工具函数不会在 schema invalid 时被调用
- validation error 出现在 ToolExecutionResult.error
- audit 记录 validation_denied
- repair 后仍 invalid 必须 deny
```

---

# PR 3：ToolRunner / ExecutionPlanner 强制接入

## 目标

修复最大阻塞：executor 直接执行工具函数。

当前 executor 接收 `sandbox`，但真正执行仍是线程池/直接调用。([GitHub][1])
这个 PR 必须让所有工具执行都经过 runner。

## 修改文件

```text
src/seekflow/tools/runners.py
src/seekflow/tools/planner.py
src/seekflow/tools/executor.py
src/seekflow/types.py
tests/tools/test_runner_selection.py
tests/tools/test_executor_no_direct_bypass.py
```

## 3.1 修改 `ToolPolicy`

在 `ToolPolicy` 中新增：

```python
RunnerKind = Literal["auto", "in_process", "process", "container"]

runner: RunnerKind = "auto"
trusted: bool = False
```

如果不想在 policy 增加 `trusted`，也可以继续使用 `tool_def.metadata["trusted"]`，但建议长期迁移到 policy，因为 trusted 是安全语义，不应藏在 metadata。

当前 `ToolPolicy` 已经有 risk、timeout、max input/output、parallel_safe、approval、allowed_domains、workspace_root 等字段，增加 runner 是自然扩展。([GitHub][4])

---

## 3.2 新增 `ExecutionPlan`

`src/seekflow/tools/planner.py`

```python
from dataclasses import dataclass
from typing import Literal

RunnerKind = Literal["in_process", "process", "container"]


@dataclass(frozen=True)
class ExecutionPlan:
    runner: RunnerKind
    timeout_s: float
    requires_hard_timeout: bool
    allow_parallel: bool
    cache_allowed: bool
    reason: str
```

## 3.3 Runner 选择规则

```python
def plan_execution(tool_def, context, timeout: float | None) -> ExecutionPlan:
    policy = tool_def.policy

    if policy is None:
        raise RuntimeError("tool without policy cannot execute")

    requested = getattr(policy, "runner", "auto")
    effective_timeout = timeout or policy.timeout_s

    if requested != "auto":
        return validate_explicit_runner(requested, policy, effective_timeout)

    caps = policy.capabilities
    risk = policy.risk
    trusted = bool(getattr(policy, "trusted", False) or tool_def.metadata.get("trusted", False))

    if "code.exec" in caps or risk in {"code_exec", "destructive"}:
        return ExecutionPlan("container", effective_timeout, True, False, False, "code/destructive requires container")

    if risk in {"network", "write"} or "network.public_http" in caps or "filesystem.write" in caps:
        return ExecutionPlan("process", effective_timeout, True, False, False, "side-effect tool requires process")

    if trusted and risk == "read" and policy.parallel_safe:
        return ExecutionPlan("in_process", effective_timeout, False, True, True, "trusted read tool")

    return ExecutionPlan("process", effective_timeout, True, False, policy.risk == "read", "default untrusted isolation")
```

## 3.4 新增 `ToolRunner`

`src/seekflow/tools/runners.py`

```python
from dataclasses import dataclass
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class ToolRunResult:
    ok: bool
    value: Any = None
    error: str | None = None
    elapsed_ms: int = 0
    killed: bool = False
    runner: str = ""


class ToolRunner(Protocol):
    name: str

    def run(
        self,
        func: Callable[..., Any],
        arguments: dict[str, Any],
        timeout_s: float,
    ) -> ToolRunResult:
        ...
```

---

## 3.5 `InProcessRunner`

只允许 trusted read 工具使用。

```python
class InProcessRunner:
    name = "in_process"

    def run(self, func, arguments, timeout_s):
        start = time.monotonic()
        try:
            value = func(**arguments)
            return ToolRunResult(
                ok=True,
                value=value,
                elapsed_ms=int((time.monotonic() - start) * 1000),
                runner=self.name,
            )
        except Exception as e:
            return ToolRunResult(
                ok=False,
                error=str(e),
                elapsed_ms=int((time.monotonic() - start) * 1000),
                runner=self.name,
            )
```

注意：`InProcessRunner` 不提供 hard timeout。只有安全 planner 允许它用于 trusted read tools。

---

## 3.6 `ProcessRunner`

用于默认半生产隔离。

```python
class ProcessRunner:
    name = "process"

    def run(self, func, arguments, timeout_s):
        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue(maxsize=1)

        p = ctx.Process(target=_child_entry, args=(q, func, arguments))
        start = time.monotonic()
        p.start()
        p.join(timeout_s)

        killed = False
        if p.is_alive():
            killed = True
            p.terminate()
            p.join(0.5)
            if p.is_alive():
                p.kill()
                p.join(0.5)

            return ToolRunResult(
                ok=False,
                error=f"Tool timed out after {timeout_s}s",
                elapsed_ms=int((time.monotonic() - start) * 1000),
                killed=True,
                runner=self.name,
            )

        if q.empty():
            return ToolRunResult(
                ok=False,
                error=f"Tool process exited with code {p.exitcode} without result",
                elapsed_ms=int((time.monotonic() - start) * 1000),
                killed=killed,
                runner=self.name,
            )

        payload = q.get()
        return ToolRunResult(
            ok=payload["ok"],
            value=payload.get("value"),
            error=payload.get("error"),
            elapsed_ms=int((time.monotonic() - start) * 1000),
            runner=self.name,
        )
```

子进程入口：

```python
def _child_entry(q, func, arguments):
    try:
        value = func(**arguments)
        q.put({"ok": True, "value": value})
    except Exception as e:
        q.put({"ok": False, "error": repr(e)})
```

注意事项：

* Windows/macOS spawn 下 func 必须 pickleable。
* 对不可 pickle 的 local closure 工具，planner 应报错并提示设置 `runner="in_process"` 仅限 trusted dev。
* 半生产级不应允许 untrusted closure in-process。

---

## 3.7 `ContainerRunner`

第一阶段可以桥接现有 `ContainerSandbox`，但必须由 executor 强制调用。

如果当前 `ContainerSandbox` 只能执行 code string，不能执行 Python callable，则先用于 `code.exec` 工具；普通 Python callable 高风险工具先走 `ProcessRunner`。后续再做真正 callable containerization。

最低实现：

```python
class ContainerRunner:
    name = "container"

    def __init__(self, sandbox):
        self.sandbox = sandbox

    def run(self, func, arguments, timeout_s):
        if not hasattr(func, "__seekflow_code__"):
            return ToolRunResult(
                ok=False,
                error="ContainerRunner requires a sandbox-executable code tool",
                runner=self.name,
            )

        result = self.sandbox.execute(func.__seekflow_code__, timeout=timeout_s)
        return ToolRunResult(
            ok=result.ok,
            value=result.output,
            error=result.error,
            elapsed_ms=result.elapsed_ms,
            killed=getattr(result, "killed", False),
            runner=self.name,
        )
```

更好的长期版本是把 tool 定义变成：

```python
ToolDefinition(
    func=...,
    execution=PythonCallableExecution | CodeExecution | SubprocessExecution
)
```

但本轮半生产级可以先以 ProcessRunner 覆盖大多数自定义工具。

---

## 3.8 executor 接入

删除 executor 中的直接执行逻辑：

```python
with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
    future = pool.submit(tool_def.func, **arguments)
    raw_result = future.result(timeout=effective_timeout)
```

改成：

```python
plan = plan_execution(tool_def, self.context, timeout)
runner = self._runner_for(plan)

run_result = runner.run(tool_def.func, arguments, plan.timeout_s)

if not run_result.ok:
    return ToolExecutionResult(
        ok=False,
        error=run_result.error,
        elapsed_ms=run_result.elapsed_ms,
        ...
    )

raw_result = run_result.value
```

## 新增测试

```python
def test_executor_never_directly_calls_untrusted_tool():
    ...

def test_trusted_read_parallel_safe_can_use_in_process():
    ...

def test_network_tool_uses_process_runner():
    ...

def test_code_exec_tool_requires_container_runner():
    ...

def test_unpickleable_untrusted_tool_denied():
    ...

def test_runner_name_recorded_in_audit():
    ...
```

## 验收标准

```text
- grep executor.py 不得出现直接 tool_def.func(**arguments)，除 InProcessRunner 内部外
- network/write/code/destructive 工具不得 in-process
- runner 写入 audit
- 现有 trusted read 工具不被破坏
```

---

# PR 4：Hard Timeout 与 Batch Deadline

## 目标

让工具 timeout 真正可终止。

当前 `ThreadPoolExecutor.future.result(timeout=...)` 不能杀死线程，且 context manager 退出时可能继续等待 worker。([GitHub][1])
半生产级必须保证 untrusted 工具 timeout 后主请求能返回。

## 修改文件

```text
src/seekflow/tools/runners.py
src/seekflow/tools/executor.py
tests/tools/test_timeout_hard_kill.py
tests/tools/test_batch_deadline.py
```

## 要求

### ProcessRunner hard kill

```text
timeout → terminate → grace → kill → join → result killed=True
```

### Batch 总 deadline

当前 executor batch 会把 parallel-safe read tools 放线程池，再 sequential 执行 side-effect tools。([GitHub][1])

改造后：

```python
def execute_batch(self, tool_calls, timeout: float | None = None):
    deadline = time.monotonic() + (timeout or self.batch_timeout_s)
    for tool_call in tool_calls:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return timeout result for remaining calls
        self.execute(tool_call, timeout=remaining)
```

### 并行 read 工具

并行 read 工具也必须通过 runner：

* trusted read → InProcessRunner，可以并发；
* untrusted read → ProcessRunner，可以并发，但要限制 max workers；
* 每个 future 要有 remaining deadline；
* batch 超时要取消未开始任务并 kill 已开始 process。

## 测试

```python
def test_infinite_loop_process_tool_killed_within_deadline():
    ...

def test_sleep_999_tool_returns_timeout_result():
    ...

def test_timeout_does_not_hang_executor_context_manager():
    ...

def test_batch_deadline_applies_to_parallel_tools():
    ...

def test_batch_deadline_applies_to_sequential_tools():
    ...
```

## 验收标准

```text
- infinite loop 工具不会拖死 pytest
- timeout 结果中 killed=True
- audit 记录 timeout/killed/runner
- batch 不因单个工具卡死
```

---

# PR 5：ToolPolicy resource limits 强制执行

## 目标

让 `ToolPolicy.max_input_bytes` 和 `max_output_bytes` 真正生效。

当前 `ToolPolicy` 已有这些字段。([GitHub][4])
但 executor 主要用 `max_result_chars` 做最终 truncate，不能替代执行前/输出边界。

## 修改文件

```text
src/seekflow/tools/executor.py
src/seekflow/tools/limits.py
tests/tools/test_tool_limits.py
```

## 输入限制

在 parse/repair 后立即检查：

```python
def check_input_size(arguments, policy):
    raw = json.dumps(arguments, ensure_ascii=False, default=str)
    size = len(raw.encode("utf-8"))
    if size > policy.max_input_bytes:
        raise ToolInputTooLarge(...)
```

## 输出限制

runner 返回后，redaction 前先做 bounded serialization：

```python
def serialize_tool_output(value, max_bytes):
    raw = json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value
    b = raw.encode("utf-8")
    if len(b) > max_bytes:
        return raw[:safe_char_limit] + "\n...[truncated by max_output_bytes]..."
    return raw
```

注意：不能让超大对象先完整进入 audit/hash/redaction。

## 测试

```python
def test_input_bytes_limit_denied_before_tool_called():
    ...

def test_output_bytes_limit_applied_before_model_context():
    ...

def test_large_binary_like_output_truncated_safely():
    ...

def test_audit_hash_uses_truncated_or_bounded_output():
    ...
```

---

# PR 6：MCP 半生产安全边界

## 目标

MCP 不能默认等同 trusted local tool。
报告中也把 MCP subprocess zombie 列为未覆盖边缘场景。

## 修改文件

```text
src/seekflow/mcp/config.py
src/seekflow/mcp/executor.py
src/seekflow/tools/planner.py
tests/mcp/test_mcp_policy.py
tests/mcp/test_mcp_timeout.py
```

## 新增信任等级

```python
MCPTrustLevel = Literal["trusted_local", "untrusted_local", "remote"]
```

默认：

```python
trust_level = "untrusted_local"
```

## 规则

```text
trusted_local:
  - 可走 ProcessRunner
  - 仍需 timeout
  - 输出 untrusted wrap

untrusted_local:
  - 必须 ProcessRunner 或 ContainerRunner
  - subprocess 必须可 kill
  - 每次 call 必须 deadline
  - output redacted + untrusted

remote:
  - 必须 network allowed_domains
  - 必须 strict URL validation
  - 必须 response size limit
```

## MCP tool policy 自动生成

每个 MCP tool 注册时生成：

```python
ToolPolicy(
    risk="network" or "read",
    capabilities={"mcp.call"},
    timeout_s=...,
    max_input_bytes=...,
    max_output_bytes=...,
    parallel_safe=False,
    requires_approval=trust_level != "trusted_local",
)
```

如果 MCP tool 声明会写文件、跑命令、访问网络，必须升级 risk。

## 测试

```python
def test_untrusted_mcp_requires_runner():
    ...

def test_mcp_call_timeout_kills_subprocess():
    ...

def test_mcp_output_redacted_and_wrapped():
    ...

def test_mcp_tool_policy_generated():
    ...

def test_remote_mcp_requires_allowed_domains():
    ...
```

---

# PR 7：DeepSeek 半生产协议收口

## 目标

确保 DeepSeek 适配进入半生产稳定状态，不一定重写成完整 state machine，但必须消除关键漂移。

DeepSeek 官方当前要求 JSON output 时设置 `response_format={"type":"json_object"}`，并且 prompt 中必须明确要求 JSON，否则可能输出空白直到 token 上限；stream usage 则通过额外 usage chunk 返回。([DeepSeek API Docs][3])

## 修改文件

```text
src/seekflow/deepseek/adapter.py
src/seekflow/deepseek/json_output.py
src/seekflow/runtime.py
tests/deepseek/test_stream_usage.py
tests/deepseek/test_json_output_guard.py
tests/deepseek/test_reasoning_trace_privacy.py
```

## 必须完成

### 1. stream usage 统一归一化

所有 usage 必须走：

```python
normalize_usage(raw_usage)
```

不要在 stream path 手写 dict。

### 2. JSON output guard

如果使用 JSON output：

* 自动设置 `response_format={"type": "json_object"}`；
* 自动确保 system/user prompt 包含 JSON 指令；
* `finish_reason == "length"` 时返回 structured error；
* empty content retry 一次；
* parse 后 schema validate。

DeepSeek 文档明确指出 JSON output 如果没有 prompt 指示，可能出现长时间空白输出；这必须由框架保护。([DeepSeek API Docs][3])

### 3. reasoning trace privacy

默认：

* 不落盘 raw `reasoning_content`；
* trace 只记录 `reasoning_present`、`reasoning_tokens`；
* debug raw capture 必须显式开启。

DeepSeek API 文档中 response message 包含 `reasoning_content` 字段。([DeepSeek API Docs][3])

## 测试

```python
def test_stream_usage_chunk_accumulated_once():
    ...

def test_json_output_injects_json_instruction():
    ...

def test_json_output_length_finish_reason_errors():
    ...

def test_reasoning_content_not_persisted_by_default():
    ...
```

---

# PR 8：半生产发布闸门与文档纠偏

## 目标

让文档、测试、版本状态和真实能力一致。

## 修改文件

```text
README.md
SECURITY.md
docs/production-readiness.md
docs/security/known-limitations.md
CHANGELOG.md
pyproject.toml
.github/workflows/ci.yml
```

## README 必须准确写

```text
Current security level:
- Level 0: supported
- Level 1: supported
- Level 2: supported after enabling PolicyEngine + ToolRunner + workspace/domain constraints
- Level 3: experimental
- Level 4: not supported
```

## SECURITY.md 必须列出

```text
默认安全保证：
- no-policy deny
- network requires allowed domains
- filesystem requires workspace
- code exec requires real sandbox
- untrusted output redacted + wrapped
- tool arguments schema validated
- untrusted tools use process/container runner
```

## known limitations

```text
- ProcessRunner cannot safely execute non-pickleable closures unless marked trusted in-process
- ContainerRunner callable isolation limited unless tool provides code/subprocess execution spec
- MCP remote trust requires explicit configuration
- DeepSeek prompt cache is best-effort, not guaranteed
```

DeepSeek context caching 官方说明是服务端自动缓存共同前缀，命中通过 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` 观察，但不是客户端可强制保证的机制。([DeepSeek API Docs][5])

---

# 5. 关键代码级修改摘要

下面是 Claude 最应该优先改的几个点。

## 5.1 `policy.py` 必改点

当前问题源头：

```text
capability gate excludes dict context
network validation only runs when domains exists
```

必须改成：

```python
ctx = normalize_context(context)

if tool_def.policy is None and not self._allow_no_policy:
    deny

if policy.risk != "read" and not ctx.dangerous_tools_enabled:
    deny

if risk_order(policy.risk) > risk_order(ctx.max_risk):
    deny

missing = policy.capabilities - ctx.allowed_capabilities
if missing:
    deny

if "network.public_http" in policy.capabilities:
    domains = policy.allowed_domains or ctx.allowed_domains
    if not domains:
        deny
    validate every url_param

if filesystem capability:
    workspace_root required
    safe_join every path_param

if code.exec:
    real sandbox required

if destructive or requires_approval:
    requires approval
```

---

## 5.2 `executor.py` 必改点

当前问题源头：

```python
future = pool.submit(tool_def.func, **arguments)
raw_result = future.result(timeout=effective_timeout)
```

必须改成：

```python
arguments = parse_or_repair(...)
check_input_size(...)
arguments = coerce(...)
validate_tool_arguments(...)

decision = policy_engine.authorize(...)
approval if required

plan = plan_execution(...)
runner = runner_for(plan)

run_result = runner.run(tool_def.func, arguments, plan.timeout_s)
if not run_result.ok:
    return error result

raw = serialize_bounded(run_result.value, policy.max_output_bytes)
safe = redact_secrets(raw)
if not trusted:
    safe = wrap_untrusted(tool_name, safe).format_for_model()
final = truncate_result(safe)
audit(...)
return result
```

---

## 5.3 `types.py` 建议扩展

当前 `ToolPolicy` 已经有半生产所需的大部分字段。([GitHub][4])

新增：

```python
RunnerKind = Literal["auto", "in_process", "process", "container"]

runner: RunnerKind = "auto"
trusted: bool = False
```

可选新增：

```python
audit_level: Literal["metadata", "hashes", "redacted_preview"] = "hashes"
```

---

## 5.4 `sandbox.py` 建议增强

当前 `ContainerSandbox` 已经有 Docker 隔离参数，如 network none、read-only、tmpfs、cap drop、no-new-privileges 等。([GitHub][6])

但要半生产更稳，timeout 后必须显式 kill 容器。

建议：

```text
- docker run --name seekflow-{run_id}-{tool_call_id}
- timeout 后 docker kill name
- finally docker rm -f name
- audit 记录 container_name、killed=True
```

---

# 6. 半生产级验收测试清单

Claude 完成所有 PR 后，必须新增或确保以下测试通过。

## 6.1 Policy

```text
test_no_policy_denied_by_default
test_dict_context_missing_capability_denied
test_network_without_allowed_domains_denied
test_network_url_strict_validation_custom_tool
test_filesystem_without_workspace_denied
test_code_exec_without_real_sandbox_denied
test_destructive_requires_approval
```

## 6.2 Executor / Runner

```text
test_executor_does_not_direct_call_untrusted_func
test_trusted_read_uses_in_process_runner
test_untrusted_read_uses_process_runner
test_network_uses_process_runner
test_write_uses_process_runner
test_code_exec_uses_container_runner
test_runner_recorded_in_audit
```

## 6.3 Timeout

```text
test_infinite_loop_tool_hard_killed
test_sleep_tool_hard_timeout
test_timeout_returns_before_deadline_plus_grace
test_no_zombie_process_after_timeout
test_batch_deadline_kills_slow_tool
```

## 6.4 Schema validation

```text
test_missing_required_arg_denied
test_extra_arg_denied
test_wrong_type_denied
test_nested_schema_denied
test_enum_denied
test_tool_func_not_called_when_args_invalid
```

## 6.5 Network / SSRF

```text
test_localhost_denied
test_127_0_0_1_denied
test_169_254_169_254_denied
test_private_dns_denied
test_redirect_to_private_denied
test_userinfo_url_denied
test_http_denied_if_policy_https_only
```

## 6.6 Filesystem

```text
test_path_traversal_denied
test_symlink_escape_denied
test_absolute_path_outside_workspace_denied
test_workspace_missing_denied
```

## 6.7 DeepSeek

```text
test_stream_usage_chunk_normalized
test_reasoning_not_persisted_by_default
test_json_output_requires_json_instruction
test_json_output_empty_content_retried_once
test_strict_schema_compiler_snapshot
```

## 6.8 MCP

```text
test_untrusted_mcp_requires_runner
test_mcp_timeout_kills_subprocess
test_mcp_output_redacted_wrapped
test_remote_mcp_requires_allowed_domains
```

---

# 7. Claude 执行提示词

可以把下面这段直接给 Claude Code。

```text
你要把 WYZAAACCC/SeekFlow 从 v0.3.4 的“受控内部试用级”推进到“完全半生产级 Level 2”。

请不要重写已有好模块。已有 NormalizedUsage、DeepSeekStrictSchemaCompiler、json_output.py、CacheCompiler、telemetry、ToolAuditRecord、validate_url_strict、fetch_url_hardened 等模块应优先接线而不是重做。

必须完成以下硬性修复：

1. PolicyEngine fail-closed：
   - dict context 统一转换为 typed context，不能绕过 capability gate。
   - network.public_http 必须要求 non-empty allowed_domains。
   - 所有 url_params 必须 validate_url_strict。
   - filesystem capability 必须 workspace_root。
   - code.exec 必须 real sandbox。
   - destructive / requires_approval 必须 approval handler。

2. Tool arguments validation：
   - 新增 tools/validation.py。
   - 用 jsonschema Draft202012Validator 校验 tool_def.parameters。
   - parse/repair/coerce 后、execute 前必须 validate。
   - validation 失败时 tool func 不能被调用。

3. ToolRunner / ExecutionPlanner：
   - 新增 tools/runners.py 和 tools/planner.py。
   - ToolPolicy 增加 runner: "auto" | "in_process" | "process" | "container"。
   - 所有工具执行必须经过 runner。
   - executor.py 不允许直接调用 tool_def.func(**arguments)，除 InProcessRunner 内部。
   - trusted read parallel_safe 才能 in_process。
   - untrusted read/network/write 默认 process。
   - code_exec/destructive 默认 container。

4. Hard timeout：
   - ProcessRunner 使用 multiprocessing spawn。
   - timeout 后 terminate → grace → kill。
   - 返回 killed=True。
   - batch 有总 deadline。
   - 不允许 ThreadPoolExecutor timeout 作为 untrusted 工具安全边界。

5. Resource limits：
   - ToolPolicy.max_input_bytes 执行前强制。
   - ToolPolicy.max_output_bytes 模型可见前强制。
   - 大输出不能先进入 audit/redaction 再截断。

6. MCP security：
   - 增加 trust_level。
   - untrusted MCP 必须 process/container runner。
   - MCP call 必须 timeout 可 kill。
   - MCP output 必须 redact + wrap_untrusted。
   - remote MCP 必须 allowed_domains。

7. DeepSeek protocol hardening：
   - stream/non-stream usage 都走 normalize_usage。
   - JSON output 自动确保 response_format=json_object 和 JSON 指令。
   - finish_reason=length 返回 structured error。
   - raw reasoning_content 默认不进入 persistent trace。

8. Release gate：
   - pytest 不能裸 failed。
   - 当前 47 个失败测试必须修复或 xfail(strict=True) 并绑定 issue。
   - README / SECURITY.md / docs/security/levels.md 必须准确说明当前支持 Level 2，不要声称 Level 3/4。

每个 PR 必须新增测试。最终验收：
- pytest 无裸 failed；
- security tests 全通过；
- executor 不再直接执行 untrusted tools；
- infinite loop tool 被 hard kill；
- network without domains denied；
- dict context missing capability denied；
- invalid tool args denied before func called；
- secrets and reasoning_content 不进入默认 trace。
```

---

# 8. 最终里程碑

## Milestone A：半生产安全闭环

必须完成：

* PR 1 Policy fail-closed；
* PR 2 JSON Schema validation；
* PR 3 ToolRunner；
* PR 4 Hard timeout；
* PR 5 resource limits。

达到后：

> 可以称为 Level 2 半生产候选。

## Milestone B：半生产可发布

必须完成：

* PR 6 MCP 安全边界；
* PR 7 DeepSeek 协议收口；
* PR 8 CI/docs/release gate；
* 测试无裸失败。

达到后：

> 可以称为完全半生产级。

## Milestone C：生产试点前置

后续再做：

* durable run store；
* signed audit；
* OTel 全链路；
* per-tenant policy；
* container callable isolation；
* stronger DNS rebinding mitigation；
* release signing / SBOM。

这些不是当前半生产阻塞，但生产级前必须做。

---

# 9. 最终判断

v0.3.4 的方向正确，作者已经修掉了不少真实问题，尤其是 runtime immutability、usage 归一化、cache metrics 接线、redaction 和 policy 主链路接线。

但当前还不能称为完全半生产级。核心原因不是模块少，而是**安全边界没有强制闭环**：

* executor 仍直接执行工具；
* timeout 仍基于线程；
* network policy 仍可空域名放行；
* dict context 仍可绕过 capability；
* arguments 缺 schema validation；
* 测试仍有裸失败。

把上述 PR 做完后，SeekFlow 才能真正从“受控内部试用级”跨越到“完全半生产级”。

[1]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/executor.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/policy.py "raw.githubusercontent.com"
[3]: https://api-docs.deepseek.com/api/create-chat-completion "Create Chat Completion | DeepSeek API Docs"
[4]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/types.py "raw.githubusercontent.com"
[5]: https://api-docs.deepseek.com/guides/kv_cache "Context Caching | DeepSeek API Docs"
[6]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/sandbox.py "raw.githubusercontent.com"
