下面这份可以直接交给 Claude Code。它不是审计报告，而是**最终修复规格书 / 工程施工方案**。目标是让 Claude Code 按顺序完成修复、补测试、统一架构，并把 SeekFlow 从“功能点堆叠的 beta 骨架”推进到“可信、可运行、可审计的 DeepSeek-native agent runtime”。

---

# SeekFlow 最终修复与改进方案

## 0. 当前事实基线

以当前公开 `main` 分支为准：

1. README 宣称 `SeekFlow v0.2.5`、production-grade security、620+ tests，并把项目定位为 DeepSeek-native agent framework。GitHub 页面同时显示当前仓库没有正式 releases。([GitHub][1])
2. PyPI 当前公开包是 `seekflow 0.1.0`，上传于 2026-05-13，且未使用 Trusted Publishing。([PyPI][2])
3. `src/seekflow` 目录中已经存在 `execution`、`deepseek`、`security`、`tools` 等目录，因此不要再把 `execution` 包缺失当成当前 P0。([GitHub][3])
4. `src/seekflow/tools` 目录当前只有 `__init__.py`、`decorator.py`、`executor.py`、`registry.py`、`schema.py`、`strict.py`，没有 `builtins.py`。([GitHub][4])
5. DeepSeek 官方当前 Chat Completion API 的模型为 `deepseek-v4-flash` 和 `deepseek-v4-pro`，thinking 参数为 `thinking.type=enabled|disabled`，`reasoning_effort=high|max`，并使用 `max_tokens`。([DeepSeek API Docs][5])
6. DeepSeek 官方明确要求：thinking mode 下发生 tool call 的 assistant turn，其 `reasoning_content` 必须在后续请求中完整传回，否则会返回 400。([DeepSeek API Docs][6])
7. DeepSeek 官方 agent 集成文档明确写到 DeepSeek V4 兼容点：不支持 developer role、支持 reasoning_effort、使用 `max_tokens`、thinking mode 下不支持 tool_choice、tool-call turn 需要 `reasoning_content` 和 assistant content。([DeepSeek API Docs][7])
8. DeepSeek 官方 JSON Output 要求设置 `response_format={"type":"json_object"}`，prompt 中显式包含 JSON 指令和示例，并说明 JSON Output 偶尔可能返回 empty content。([DeepSeek API Docs][8])
9. DeepSeek 官方模型页显示 V4 Flash / Pro 支持 JSON Output、Tool Calls、Context Caching，context length 为 1M，max output 为 384K；`deepseek-chat` 和 `deepseek-reasoner` 未来会废弃，并分别兼容为 `deepseek-v4-flash` 的 non-thinking / thinking 模式。([DeepSeek API Docs][9])

---

# 1. 总目标

把 SeekFlow 修成以下形态：

```text
一个真正 DeepSeek-native 的轻量 agent runtime：

- 默认安全；
- 默认可 import、可运行；
- DeepSeek thinking/tool-call 协议完全正确；
- 工具执行有统一 policy enforcement；
- 文件、网络、代码执行不可绕过安全边界；
- retry、stream、circuit breaker 行为可靠；
- JSON Output + repair + schema validation 闭环；
- prompt cache、usage、cost、budget 统一；
- README、版本、PyPI、release 状态一致；
- 所有关键路径有测试兜底。
```

不要把目标做成“大而全的 LangChain 替代品”。SeekFlow 的核心护城河应该是：

```text
DeepSeek protocol correctness
+ lightweight tool runtime
+ cache-aware cost control
+ hardened tool execution
+ structured output reliability
```

---

# 2. 非目标与禁止事项

Claude Code 执行时必须遵守：

1. **不要重写整个项目。** 先闭环现有模块，再做局部重构。
2. **不要为了让测试通过而降低安全策略。** 默认安全必须更严格，不可更宽松。
3. **不要在 thinking mode 下发送 `tool_choice`。** DeepSeek V4 thinking mode 不支持该参数。([DeepSeek API Docs][7])
4. **不要压缩、删除、重排发生 tool call 的 assistant turn 的 `reasoning_content`。** DeepSeek 官方要求后续请求完整传回。([DeepSeek API Docs][6])
5. **不要在 stream 已经向上游 yield 内容后自动 retry。** 这会造成重复 token、错序 token 或语义不一致。
6. **不要让 `NoSandbox` 执行不可信代码。** `NoSandbox` 只能表示 code execution disabled。
7. **不要让文件读取默认允许 `.env`、私钥、证书、token 文件。**
8. **不要让 HTTP 工具绕过 hardened HTTP client。** 禁止工具内部直接使用裸 `urllib.request.urlopen()` 或 `requests.get()`。
9. **不要在多个地方硬编码 DeepSeek 模型价格。** 只能有一个 model/pricing registry。
10. **不要继续宣称 production-grade，除非所有 P0/P1 验收项通过。**

---

# 3. 推荐提交顺序

按下面顺序做 12 个提交。每个提交必须带测试。

```text
commit 01: fix package/runtime import sanity
commit 02: add safe built-in tools
commit 03: centralize DeepSeek adapter params
commit 04: fix DeepSeek message protocol validation
commit 05: fix retry/stream/circuit breaker behavior
commit 06: enforce ToolPolicy completely
commit 07: harden file embedding and filesystem paths
commit 08: harden HTTP/network tool path
commit 09: harden Python/SQLite execution path
commit 10: unify model registry, usage, cost, budget
commit 11: finish JSON Output + repair + validation pipeline
commit 12: release/docs/CI cleanup
```

---

# 4. P0：先让项目真实可运行

## 4.1 新增 `src/seekflow/tools/builtins.py`

当前 `DeepSeekAgent.allow_filesystem()`、`allow_network()`、`allow_python()`、`allow_sqlite()` 会引用 `seekflow.tools.builtins`，但该文件不存在；这是最硬的运行级断裂。`tools` 目录当前也确实没有 `builtins.py`。([GitHub][4])

新增：

```text
src/seekflow/tools/builtins.py
```

必须提供：

```python
make_calculate()
make_read_file(workspace_root: str | Path, *, max_bytes: int = 1_000_000)
make_write_file(workspace_root: str | Path, *, max_bytes: int = 1_000_000, allow_overwrite: bool = False)
make_list_dir(workspace_root: str | Path, *, max_entries: int = 200)
make_fetch_url(allowed_domains: set[str] | list[str], *, timeout_s: float = 10.0, max_bytes: int = 1_000_000)
make_python_exec(sandbox: Sandbox, *, timeout_s: float = 5.0, max_output_bytes: int = 200_000)
make_sqlite_query(db_path: str | Path, *, readonly: bool = True, timeout_s: float = 3.0, max_rows: int = 200)
```

每个 factory 返回 `ToolDefinition`，并且必须带 `ToolPolicy`：

```python
ToolPolicy(
    capabilities={...},
    risk="read" | "network" | "write" | "code_exec",
    timeout_s=...,
    max_input_bytes=...,
    max_output_bytes=...,
    workspace_root=...,
    allowed_domains=...,
    parallel_safe=...,
    requires_approval=...,
)
```

建议 mapping：

```text
calculate:
  capabilities={"compute.basic"}
  risk="read"
  trusted=True
  parallel_safe=True

read_file:
  capabilities={"filesystem.read"}
  risk="read"
  trusted=False
  workspace_root required

write_file:
  capabilities={"filesystem.write"}
  risk="write"
  trusted=False
  workspace_root required
  requires_approval=True by default

list_dir:
  capabilities={"filesystem.read"}
  risk="read"
  trusted=False

fetch_url:
  capabilities={"network.http"}
  risk="network"
  allowed_domains required
  requires_approval=False if domain allowlist explicit

python_exec:
  capabilities={"code.exec"}
  risk="code_exec"
  requires_approval=True
  sandbox required and must not be NoSandbox

sqlite_query:
  capabilities={"database.read"} for readonly
  capabilities={"database.write"} for write mode
  risk="read" or "write"
```

必须做到：

```python
make_python_exec(NoSandbox())
```

直接抛异常，不能注册成功。

### 新增测试

```text
tests/test_agent_builtin_tools.py
```

测试：

```python
def test_tools_builtins_module_imports():
    import seekflow.tools.builtins

def test_allow_filesystem_registers_tools(tmp_path):
    agent = DeepSeekAgent(...)
    agent.allow_filesystem(tmp_path)
    assert "read_file" in agent.tool_names()

def test_allow_network_requires_domains():
    with pytest.raises(ValueError):
        make_fetch_url([])

def test_allow_python_rejects_no_sandbox():
    with pytest.raises(ValueError):
        make_python_exec(NoSandbox())

def test_builtin_tool_policies_present(tmp_path):
    td = make_read_file(tmp_path)
    assert td.policy is not None
    assert "filesystem.read" in td.policy.capabilities
```

---

## 4.2 增加 import smoke tests

新增：

```text
tests/test_import_smoke.py
```

覆盖：

```python
def test_public_imports():
    import seekflow
    from seekflow import DeepSeekAgent, tool
    from seekflow.runtime import ToolRuntime
    from seekflow.client import DeepSeekClient
    from seekflow.tools.executor import ToolExecutor
    from seekflow.policy import PolicyEngine
    from seekflow.execution.context import ToolExecutionContext
    from seekflow.execution.approval import ApprovalRequest
```

再加 CLI / package 检查：

```python
def test_package_contains_required_submodules():
    import importlib
    for mod in [
        "seekflow.tools.builtins",
        "seekflow.deepseek.params",
        "seekflow.deepseek.protocol",
        "seekflow.security.http",
    ]:
        importlib.import_module(mod)
```

验收命令：

```bash
pytest tests/test_import_smoke.py tests/test_agent_builtin_tools.py -q
```

---

# 5. P0：DeepSeekAdapter 统一协议参数

当前项目已经有 `deepseek/params.py`、`deepseek/protocol.py` 等模块，不要另起一套完全重复的新系统。要做的是把所有 DeepSeek 相关兼容逻辑收敛到一个 adapter 层。

## 5.1 新增或改造 `src/seekflow/deepseek/adapter.py`

定义：

```python
@dataclass(frozen=True)
class DeepSeekCapabilities:
    supports_developer_role: bool = False
    supports_reasoning_effort: bool = True
    max_tokens_field: str = "max_tokens"
    supports_tool_choice_in_thinking: bool = False
    requires_reasoning_content_for_tool_calls: bool = True
    requires_assistant_content_for_tool_calls: bool = True
    supports_json_output: bool = True
    supports_context_caching: bool = True
```

定义：

```python
@dataclass(frozen=True)
class ThinkingConfig:
    enabled: bool = True
    effort: Literal["high", "max"] = "high"
```

定义：

```python
class DeepSeekAdapter:
    def normalize_model(self, model: str, thinking: ThinkingConfig | None) -> NormalizedModel: ...
    def normalize_messages(self, messages: list[dict], *, thinking: ThinkingConfig) -> list[dict]: ...
    def build_chat_params(self, *, model: str, messages: list[dict], tools: list[dict] | None, thinking: ThinkingConfig, response_format: Any | None, stream: bool, **kwargs) -> dict: ...
    def normalize_usage(self, usage: Any) -> dict: ...
```

## 5.2 模型 alias 规则

必须统一：

```text
deepseek-chat:
  actual_model = deepseek-v4-flash
  thinking.enabled = False

deepseek-reasoner:
  actual_model = deepseek-v4-flash
  thinking.enabled = True

deepseek-v4-flash:
  thinking.enabled = user config or default True

deepseek-v4-pro:
  thinking.enabled = user config or default True
```

不要再把 `deepseek-reasoner` 映射到 `deepseek-v4-pro`。官方说明 `deepseek-chat` 和 `deepseek-reasoner` 分别对应 `deepseek-v4-flash` 的 non-thinking / thinking 模式。([DeepSeek API Docs][9])

## 5.3 参数规则

DeepSeekAdapter 必须做：

```python
if thinking.enabled:
    params["extra_body"]["thinking"] = {"type": "enabled"}
    params["reasoning_effort"] = thinking.effort
    params.pop("tool_choice", None)
    params.pop("temperature", None)
    params.pop("top_p", None)
    params.pop("presence_penalty", None)
    params.pop("frequency_penalty", None)
else:
    params["extra_body"]["thinking"] = {"type": "disabled"}
```

依据：DeepSeek 官方说明 thinking mode 使用 `extra_body={"thinking":{"type":"enabled"}}`，`reasoning_effort` 支持 `high|max`，且 thinking mode 下 temperature/top_p/presence/frequency penalty 不生效。([DeepSeek API Docs][6])

`max_completion_tokens` 兼容：

```python
if "max_completion_tokens" in kwargs:
    if "max_tokens" not in kwargs:
        kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
    else:
        kwargs.pop("max_completion_tokens")
```

DeepSeek 官方 API 使用 `max_tokens`。([DeepSeek API Docs][5])

developer role 处理：

```python
if message["role"] == "developer":
    # 默认转换为 system，或者在 strict_provider=True 时抛错
    message["role"] = "system"
```

DeepSeek agent 集成文档明确 `supportsDeveloperRole: false`。([DeepSeek API Docs][7])

## 5.4 runtime/client 必须只通过 Adapter 构造请求

改造：

```text
src/seekflow/client.py
src/seekflow/runtime.py
src/seekflow/agent/agent.py
src/seekflow/deepseek/params.py
```

要求：

```text
runtime 不再手工拼 thinking 参数
agent 不再维护自己的 _THINKING_IGNORED_PARAMS
client 不再散落处理 max_tokens / extra_body / tool_choice
所有 DeepSeek 兼容规则只在 DeepSeekAdapter 中实现
```

### 测试

新增：

```text
tests/deepseek/test_adapter_params.py
```

覆盖：

```python
def test_thinking_enabled_adds_extra_body_and_effort():
    ...

def test_thinking_removes_tool_choice():
    ...

def test_non_thinking_can_keep_tool_choice():
    ...

def test_developer_role_converted_to_system():
    ...

def test_max_completion_tokens_maps_to_max_tokens():
    ...

def test_deepseek_reasoner_alias_maps_to_flash_thinking():
    ...

def test_deepseek_chat_alias_maps_to_flash_non_thinking():
    ...
```

---

# 6. P0：DeepSeek message protocol validator

DeepSeek thinking + tool-call 协议是 SeekFlow 的核心，不允许靠“差不多”的 message repair。

## 6.1 改造 `src/seekflow/deepseek/protocol.py`

实现 mode-aware validator：

```python
@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    index: int | None = None
    severity: Literal["error", "warning"] = "error"

def validate_deepseek_messages(
    messages: list[dict],
    *,
    thinking_enabled: bool,
    require_assistant_content_for_tool_calls: bool = True,
    repair: bool = False,
) -> list[ValidationIssue]:
    ...
```

规则：

```text
1. role 只能是 system/user/assistant/tool；developer 必须在 adapter 层转换或拒绝。
2. assistant message 有 tool_calls 时：
   - content 不得为 None；若 repair=True，可改为 ""。
   - thinking_enabled=True 时 reasoning_content 必须存在且为 str。
   - thinking_enabled=False 时不强制 reasoning_content。
3. 每个 tool_call.id 必须有且只有一个后续 tool message 对应。
4. tool message 必须有 tool_call_id 和 content。
5. tool message 不能出现在没有 pending tool_call 的位置。
6. 不允许裁剪后留下 assistant tool_calls 而丢失对应 tool result。
7. 不允许重排 tool_call 和 tool result。
```

## 6.2 runtime 修复

在每次调用 DeepSeek 前：

```python
messages = adapter.normalize_messages(messages, thinking=thinking)
issues = validate_deepseek_messages(messages, thinking_enabled=thinking.enabled, repair=False)
if any(issue.severity == "error" for issue in issues):
    raise DeepSeekProtocolError(...)
```

在内部 repair 阶段允许：

```python
messages = repair_deepseek_messages(messages, thinking_enabled=thinking.enabled)
```

但 repair 必须有限，不允许伪造 reasoning_content。**如果 thinking tool-call turn 缺失 reasoning_content，必须 fail closed。**

## 6.3 context trimming 修复

改造 `_runtime_base.trim_messages()`：

```text
永远不要拆散：
assistant(tool_calls=[...], reasoning_content=...)
+ 后续 N 个 tool message

这是一个 atomic block。
```

如果必须裁剪，整块裁掉；不能裁掉其中一半。

### 测试

新增：

```text
tests/deepseek/test_message_protocol.py
tests/test_runtime_trimming_protocol.py
```

覆盖：

```python
def test_thinking_tool_call_requires_reasoning_content():
    ...

def test_non_thinking_tool_call_does_not_require_reasoning_content():
    ...

def test_assistant_tool_call_content_none_repaired_to_empty():
    ...

def test_tool_result_without_pending_tool_call_rejected():
    ...

def test_duplicate_tool_result_rejected():
    ...

def test_trim_preserves_tool_call_blocks():
    ...

def test_trim_never_compresses_tool_call_reasoning_content():
    ...
```

---

# 7. P0：修复 runtime 中的 `tool_choice` 冲突

当前 runtime 在最后一步可能设置 `tool_choice="none"`；这与 DeepSeek V4 thinking mode 不支持 `tool_choice` 冲突。DeepSeek agent 集成文档明确 thinking compat 下 `supportsToolChoice: false`。([DeepSeek API Docs][7])

## 修复规则

在 runtime 里不要直接写：

```python
call_kwargs["tool_choice"] = "none"
```

改为：

```python
if steps_remaining <= 1:
    if provider_is_deepseek and thinking.enabled:
        messages.append({
            "role": "user",
            "content": "请直接给出最终答案，不要再调用工具。"
        })
    else:
        call_kwargs["tool_choice"] = "none"
```

更推荐：runtime 不关心 provider 细节，直接把 `tool_choice` 交给 adapter 清理：

```python
params = adapter.build_chat_params(...)
```

DeepSeekAdapter 中：

```python
if thinking.enabled:
    params.pop("tool_choice", None)
```

### 测试

```python
def test_runtime_final_step_does_not_send_tool_choice_in_thinking_mode():
    ...

def test_runtime_final_step_can_send_tool_choice_none_in_non_thinking_mode():
    ...
```

---

# 8. P0：retry / stream / circuit breaker 修复

## 8.1 统一错误模型

当前 `DeepSeekClient.chat()` 会把 OpenAI SDK 异常映射为自定义错误，而 `RetryExecutor` 仍主要捕获 `APIStatusError`。必须统一。

新增或改造：

```text
src/seekflow/errors.py
```

定义：

```python
class DeepSeekAPIError(Exception):
    status_code: int | None
    code: str | None
    retry_after: float | None
    retryable: bool
    message: str

class RateLimitError(DeepSeekAPIError): ...
class ServiceUnavailableError(DeepSeekAPIError): ...
class AuthenticationError(DeepSeekAPIError): ...
class BadRequestError(DeepSeekAPIError): ...
class PaymentRequiredError(DeepSeekAPIError): ...
class PermissionDeniedError(DeepSeekAPIError): ...
```

`map_http_error()` 必须返回：

```text
400: BadRequestError retryable=False
401: AuthenticationError retryable=False
402: PaymentRequiredError retryable=False
403: PermissionDeniedError retryable=False
404: NotFoundError retryable=False
408: Timeout retryable=True
409: Conflict retryable=True only if idempotent
429: RateLimitError retryable=True
500/502/503/504: ServiceUnavailableError retryable=True
```

## 8.2 RetryExecutor 改造

`RetryExecutor` 必须 catch：

```python
except DeepSeekAPIError as e:
    ...
except APIStatusError as e:
    ...
except APITimeoutError as e:
    ...
except APIConnectionError as e:
    ...
```

bounded retry：

```python
deadline = time.monotonic() + policy.max_elapsed_s
for attempt in range(policy.max_attempts):
    ...
```

禁止当前这种“用 max_delay * retries 当隐式 deadline”的模糊策略。改成：

```python
@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    max_elapsed_s: float = 60.0
    initial_delay_s: float = 0.5
    max_delay_s: float = 8.0
    jitter: bool = True
    retry_statuses: frozenset[int] = frozenset({408, 409, 429, 500, 502, 503, 504})
```

## 8.3 stream retry 规则

当前 stream retry 试图用 `yielded_count` 跳过重复 chunk。这是不可靠的。修改为：

```python
has_yielded = False

try:
    for chunk in fn():
        has_yielded = True
        yield chunk
except RetryableError:
    if has_yielded:
        raise StreamInterruptedError(
            "stream interrupted after bytes were yielded; automatic retry disabled"
        )
    retry...
```

禁止 token-level dedupe。

## 8.4 CircuitBreaker

CircuitBreaker 只记录 retryable upstream errors：

```text
计入 breaker:
  408/429/500/502/503/504
  connection timeout
  read timeout

不计入 breaker:
  400 bad request
  401 auth
  402 payment
  403 permission
  404 not found
  schema validation error
  local policy denial
```

成功后必须重置或衰减失败计数。

### 测试

新增：

```text
tests/test_retry_executor_errors.py
tests/test_stream_retry.py
tests/test_circuit_breaker_semantics.py
```

覆盖：

```python
def test_retry_executor_retries_custom_rate_limit_error():
    ...

def test_retry_executor_does_not_retry_bad_request():
    ...

def test_429_respects_retry_after_and_max_attempts():
    ...

def test_stream_retries_before_first_yield():
    ...

def test_stream_does_not_retry_after_first_yield():
    ...

def test_non_retryable_errors_do_not_trip_circuit_breaker():
    ...

def test_success_resets_circuit_breaker_failure_count():
    ...
```

---

# 9. P1：ToolPolicy enforcement 必须完整闭环

当前 `ToolPolicy` 有很多字段，但不代表真正被 executor 强制执行。修复目标：**所有工具调用都必须通过一个中央执行路径，不允许 built-in tool、MCP tool、用户自定义 tool 绕过 policy。**

## 9.1 修改 `src/seekflow/tools/executor.py`

执行顺序固定：

```text
1. load tool_def
2. parse arguments
3. canonicalize arguments
4. input byte limit
5. JSON schema validation/coercion
6. PolicyEngine.authorize()
7. approval if required
8. execute with kill-safe timeout
9. serialize result
10. redact secrets
11. output byte limit
12. wrap untrusted output
13. audit record
14. return ToolRuntimeResult
```

伪代码：

```python
def execute(self, tool_name: str, arguments: dict | str, context: ToolExecutionContext) -> ToolRuntimeResult:
    tool_def = registry.get(tool_name)

    args = parse_or_repair_arguments(arguments, tool_def)
    args_json = canonical_json(args)
    enforce_max_input_bytes(args_json, tool_def.policy)

    args = validate_and_coerce_schema(args, tool_def.schema)

    decision = self.policy_engine.authorize(tool_def, args, context)
    if not decision.allowed:
        return ToolRuntimeResult(error=PolicyDenied(...))

    if decision.requires_approval:
        approved = self.approval_handler.request(...)
        if not approved:
            return ToolRuntimeResult(error=ApprovalDenied(...))

    result = self.execution_backend.run(
        tool_def.func,
        args,
        timeout_s=tool_def.policy.timeout_s,
        sandbox=select_sandbox(tool_def.policy, context),
    )

    result = redact_secrets(result)
    result = enforce_output_limit(result, tool_def.policy.max_output_bytes)
    result = wrap_untrusted(result, source=tool_name)

    audit.write(...)
    return result
```

## 9.2 PolicyContext 默认严格

修改 `PolicyEngine`：

```python
class PolicyEngine:
    def __init__(self, *, mode: Literal["strict", "compat"] = "strict"):
        ...
```

默认：

```text
mode="strict"
allow_no_policy=False
context missing -> deny non-read tools
dangerous_tools_enabled=False
max_risk="read"
allowed_capabilities={"compute.basic", "filesystem.read"} only if explicitly granted
```

禁止无 context 时默认 destructive。

## 9.3 path 参数语义

不要用“字符串里包含 `/` 或 `\`”猜路径。给 ToolPolicy 增加：

```python
path_params: frozenset[str] = frozenset()
url_params: frozenset[str] = frozenset()
```

例如：

```python
ToolPolicy(
    capabilities={"filesystem.read"},
    risk="read",
    workspace_root=workspace_root,
    path_params=frozenset({"path"}),
)
```

PolicyEngine 用 `path_params` 校验：

```python
for name in policy.path_params:
    validate_file_access(args[name], workspace_root=effective_workspace_root)
```

effective root：

```python
root = policy.workspace_root or context.workspace_root
```

## 9.4 output limit

`max_result_chars` 是 UI/LLM 层概念，`ToolPolicy.max_output_bytes` 是安全边界。两者都保留，但语义分开：

```text
max_output_bytes:
  hard security limit

max_result_chars:
  prompt rendering limit
```

### 测试

```text
tests/test_tool_policy_enforcement.py
```

覆盖：

```python
def test_no_policy_tool_denied_by_default():
    ...

def test_policy_max_input_bytes_enforced():
    ...

def test_policy_max_output_bytes_enforced():
    ...

def test_policy_timeout_uses_policy_timeout_s():
    ...

def test_path_params_validated_against_context_workspace():
    ...

def test_url_params_validated_against_allowed_domains():
    ...

def test_approval_required_invokes_handler():
    ...

def test_approval_denial_prevents_execution():
    ...
```

---

# 10. P1：文件安全与 file embedding 修复

## 10.1 改造 `src/seekflow/files.py`

当前文件嵌入逻辑不能绕过 workspace sandbox。修改签名：

```python
def embed_files_into_message(
    message: str | dict,
    files: list[str | Path],
    *,
    workspace_root: str | Path,
    max_file_bytes: int = 1_000_000,
    max_total_bytes: int = 4_000_000,
    allowed_extensions: set[str] | None = None,
    deny_extensions: set[str] | None = None,
    deny_globs: list[str] | None = None,
) -> dict:
    ...
```

默认 deny：

```python
DEFAULT_DENY_GLOBS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa",
    "id_ed25519",
    ".aws/*",
    ".gcp/*",
    ".azure/*",
    ".git/*",
    "node_modules/*",
    ".venv/*",
]
```

把 `.env` 从默认文本扩展中移除。

## 10.2 使用统一 validator

所有文件读取前必须：

```python
path = validate_file_access(
    requested_path,
    workspace_root=workspace_root,
    allow_ext=allowed_extensions,
    deny_ext=deny_extensions,
    deny_globs=deny_globs,
)
```

防止：

```text
../secret
symlink escape
absolute path escape
.env read
private key read
hidden credential dir read
```

### 测试

```text
tests/test_files_security.py
```

覆盖：

```python
def test_embed_files_requires_workspace_root():
    ...

def test_embed_files_blocks_dotenv(tmp_path):
    ...

def test_embed_files_blocks_path_traversal(tmp_path):
    ...

def test_embed_files_blocks_symlink_escape(tmp_path):
    ...

def test_embed_files_respects_max_total_bytes(tmp_path):
    ...
```

---

# 11. P1：HTTP / SSRF 防护闭环

当前已有 `security/http.py`，不要废弃；要把所有网络工具强制接到它上面。

## 11.1 改造 `src/seekflow/security/http.py`

保留现有 hardened 功能，并补齐：

```text
- 默认 HTTPS only；
- 默认禁止 redirects，或每跳 redirect 重新校验；
- 禁止 userinfo；
- 禁止 localhost/private/reserved/link-local/multicast；
- 禁止 metadata IP；
- allowed_domains 必须显式；
- allowed_ports 默认 {443}；
- 超时；
- 响应最大字节数；
- 禁用环境代理；
- content-type allowlist 可配置；
- final_url 也必须校验。
```

终局增强可以加入：

```text
DNS resolve -> validate IP -> connect to validated IP with original Host/SNI
```

但这可作为 P2 production profile，不必阻塞 P1。

## 11.2 fetch_url built-in 强制使用 hardened HTTP

`make_fetch_url()` 内部只能调用：

```python
fetch_url_hardened(...)
```

不能裸调 `urllib` 或 `requests`。

### 测试

```text
tests/test_security_http.py
tests/test_builtin_fetch_url.py
```

覆盖：

```python
def test_blocks_localhost():
    ...

def test_blocks_127_0_0_1():
    ...

def test_blocks_169_254_169_254():
    ...

def test_blocks_private_ipv4():
    ...

def test_blocks_ipv6_loopback():
    ...

def test_blocks_userinfo_trick():
    ...

def test_redirect_to_private_ip_blocked():
    ...

def test_domain_not_in_allowlist_blocked():
    ...

def test_response_size_limit_enforced():
    ...
```

---

# 12. P1：Python / SQLite 执行安全

## 12.1 Python execution

`make_python_exec()` 只接受显式 sandbox：

```python
def make_python_exec(sandbox: Sandbox, ...):
    if isinstance(sandbox, NoSandbox):
        raise ValueError("Python execution requires ProcessSandbox or ContainerSandbox")
```

### ProcessSandbox

标注：

```text
ProcessSandbox is not safe for hostile multi-tenant workloads.
```

实现最低要求：

```text
- clean env
- temp cwd
- timeout with process kill
- output limit
- no inherited stdin
- no shell=True
```

Linux 下尽量加：

```python
resource.setrlimit(resource.RLIMIT_CPU, ...)
resource.setrlimit(resource.RLIMIT_AS, ...)
resource.setrlimit(resource.RLIMIT_NOFILE, ...)
```

### ContainerSandbox

加强 Docker 参数：

```bash
--network none
--read-only
--tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m
--cap-drop ALL
--security-opt no-new-privileges
--pids-limit 64
--memory 256m
--cpus 1
--user 65534:65534
--ulimit nofile=64:64
```

## 12.2 SQLite

`make_sqlite_query()` 默认 readonly：

```python
sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
```

只允许：

```text
SELECT
WITH ... SELECT
PRAGMA table_info
```

禁止：

```text
ATTACH
DETACH
INSERT
UPDATE
DELETE
DROP
ALTER
CREATE
VACUUM
.load
```

设置：

```python
conn.set_progress_handler(...)
conn.set_authorizer(...)
```

限制：

```text
max_rows
timeout
output bytes
```

### 测试

```text
tests/test_builtin_python_exec.py
tests/test_builtin_sqlite.py
```

覆盖：

```python
def test_python_exec_rejects_no_sandbox():
    ...

def test_python_exec_timeout_kills_process():
    ...

def test_python_exec_output_limit():
    ...

def test_sqlite_readonly_allows_select():
    ...

def test_sqlite_readonly_blocks_insert():
    ...

def test_sqlite_blocks_attach():
    ...

def test_sqlite_limits_rows():
    ...
```

---

# 13. P1：JSON Output + repair + schema validation

DeepSeek 官方 JSON Output 要求 `response_format={"type":"json_object"}`、prompt 中包含 JSON 指令和示例、合理设置 `max_tokens`，并提示可能出现 empty content。([DeepSeek API Docs][8])

## 13.1 建立统一 pipeline

新增或改造：

```text
src/seekflow/deepseek/json_output.py
src/seekflow/repair/json_repair.py
```

实现：

```python
def run_structured_output(
    client,
    *,
    model: str,
    messages: list[dict],
    schema: type[BaseModel] | dict,
    thinking: ThinkingConfig,
    max_repair_attempts: int = 1,
    max_reemit_attempts: int = 1,
) -> StructuredOutputResult:
    ...
```

流程：

```text
1. 添加/检查 system prompt 中有 JSON 指令和示例。
2. 设置 response_format={"type":"json_object"}。
3. 调用 DeepSeek。
4. 如果 content 为空：
   - 记录 empty_content；
   - 改写 prompt 后最多重试一次。
5. json.loads。
6. Pydantic / JSON Schema validate。
7. 若 parse 失败，做 mechanical repair。
8. repair 后再次 validate。
9. 若 validate 失败，做 model re-emit。
10. 仍失败则 fail closed，返回 StructuredOutputError。
```

## 13.2 dangerous tool 参数禁止低置信 repair

对于工具调用参数：

```text
risk in {"write", "network", "code_exec", "destructive"}:
  repair_confidence < 0.95 -> deny execution
```

错误消息、常量、README 必须统一，不允许一处写 0.85，一处写 0.95。

### 测试

```text
tests/test_json_output_pipeline.py
tests/test_tool_argument_repair_safety.py
```

覆盖：

```python
def test_json_output_sets_response_format():
    ...

def test_json_prompt_contains_json_word_and_example():
    ...

def test_empty_content_retries_once():
    ...

def test_repaired_json_is_validated_again():
    ...

def test_dangerous_tool_low_confidence_repair_denied():
    ...

def test_safe_tool_high_confidence_repair_allowed():
    ...
```

---

# 14. P2：统一 ModelRegistry / pricing / usage / budget

当前价格和模型能力不要分散在 `agent.py`、`budget.py`、`cost.py`、`models.py` 多处。

## 14.1 新增统一 registry

新增：

```text
src/seekflow/deepseek/models.py
src/seekflow/models.py
```

保留一个 source of truth：

```python
@dataclass(frozen=True)
class Pricing:
    input_cache_hit_per_1m_usd: Decimal
    input_cache_miss_per_1m_usd: Decimal
    output_per_1m_usd: Decimal
    effective_at: datetime
    source: str

@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    aliases: dict[str, AliasSpec]
    context_length: int
    max_output_tokens: int
    supports_thinking: bool
    supports_tool_calls: bool
    supports_json_output: bool
    supports_context_caching: bool
    supports_fim_non_thinking_only: bool
    pricing: Pricing
```

默认数据应与 DeepSeek 官方模型页一致：V4 Flash / Pro context length 1M、max output 384K、支持 JSON Output、Tool Calls、Context Caching，FIM 仅 non-thinking mode。([DeepSeek API Docs][9])

提供：

```python
ModelRegistry.default()
ModelRegistry.from_yaml(path)
ModelRegistry.resolve(model, thinking)
ModelRegistry.price_usage(model, usage)
```

## 14.2 usage normalization

统一 usage 格式：

```python
@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
```

DeepSeekAdapter 负责从 SDK usage 中解析：

```text
prompt_cache_hit_tokens
prompt_cache_miss_tokens
cached_tokens fallback
```

## 14.3 Budget preflight

`CostBudget` 必须在请求前执行，而不是事后统计：

```python
estimated = estimator.estimate(
    model=model,
    prompt_tokens=token_count(messages),
    max_output_tokens=max_tokens,
    cache_hit_ratio_estimate=...
)
budget.check_preflight(estimated)
```

请求后 reconcile：

```python
actual = registry.price_usage(model, usage)
budget.record_actual(actual)
```

### 测试

```text
tests/test_model_registry.py
tests/test_cost_budget.py
```

覆盖：

```python
def test_alias_resolution_deepseek_chat():
    ...

def test_alias_resolution_deepseek_reasoner():
    ...

def test_pricing_uses_cache_hit_and_miss_separately():
    ...

def test_budget_preflight_blocks_over_budget():
    ...

def test_budget_actual_usage_reconciles():
    ...
```

---

# 15. P2：Prompt cache 极致化

DeepSeek 当前 cache hit 与 cache miss 价格差距极大，官方也明确区分 cache hit / miss 价格。([DeepSeek API Docs][9])

## 15.1 CacheCompiler 规范

稳定 prefix 必须只包含：

```text
- provider invariant
- normalized system prompt
- policy prompt
- canonical tool schema
- stable memory summary
```

volatile tail 包含：

```text
- latest user query
- current tool results
- current file snippets
```

所有 tool schema JSON：

```python
json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
```

## 15.2 cache metrics

Trace / diagnostics 必须包含：

```text
system_hash
tool_schema_hash
prefix_hash
prompt_cache_hit_tokens
prompt_cache_miss_tokens
cache_hit_ratio
estimated_cache_savings_usd
```

## 15.3 不破坏 DeepSeek protocol

cache compression / trimming 不得：

```text
- 删除 tool-call assistant reasoning_content；
- 拆散 assistant tool_calls + tool messages；
- 改写 tool_call_id；
- 重排 tool messages。
```

### 测试

```text
tests/test_cache_compiler.py
tests/test_cache_protocol_invariants.py
```

覆盖：

```python
def test_tool_schema_hash_stable_across_dict_order():
    ...

def test_prefix_hash_stable_when_user_tail_changes():
    ...

def test_tool_call_reasoning_not_compressed():
    ...

def test_tool_call_blocks_not_split_by_cache_compression():
    ...
```

---

# 16. P2：MCP 修复

若保留 MCP，则必须统一走 ToolExecutor 和 PolicyEngine。

## 16.1 MCP tool 命名

统一：

```text
mcp.{server_id}.{tool_name}
```

避免一处用 `server__tool`，另一处按 `.` split。

## 16.2 MCP subprocess 安全

默认 env：

```python
env = {}
```

只有 allowlist 中的变量传入。

必须有：

```text
startup timeout
request timeout
readline timeout
process kill
stderr capture limit
stdout capture limit
```

JSON-RPC id 必须递增，不能固定。

## 16.3 MCP policy

MCP discovered tool 必须被包成 `ToolDefinition`，并带 policy：

```python
ToolPolicy(
    capabilities={"mcp.call"},
    risk="network" or "write" depending config,
    timeout_s=...,
    requires_approval=...
)
```

### 测试

```text
tests/test_mcp_executor.py
```

覆盖：

```python
def test_mcp_tool_names_canonical():
    ...

def test_mcp_env_default_empty():
    ...

def test_mcp_request_ids_unique():
    ...

def test_mcp_timeout_kills_process():
    ...

def test_mcp_tool_goes_through_policy_engine():
    ...
```

---

# 17. P2：Observability / audit / trace

## 17.1 Audit record

每次 tool call 记录：

```python
@dataclass(frozen=True)
class ToolAuditRecord:
    run_id: str
    tool_name: str
    started_at: datetime
    ended_at: datetime
    duration_ms: int
    policy_risk: str
    capabilities: set[str]
    approved: bool
    args_hash: str
    result_hash: str | None
    error_type: str | None
    output_bytes: int
```

禁止把原始 secret、完整参数、完整工具输出写入 audit。

## 17.2 Trace event

增加事件：

```text
deepseek.request.built
deepseek.protocol.validated
deepseek.response.received
tool.policy.checked
tool.approval.requested
tool.execution.started
tool.execution.finished
retry.scheduled
circuit.opened
budget.preflight.checked
cache.prefix.compiled
```

## 17.3 OpenTelemetry 可选

不要强依赖 OpenTelemetry。提供 optional extra：

```toml
[project.optional-dependencies]
otel = ["opentelemetry-api", "opentelemetry-sdk"]
```

---

# 18. Release / 文档 / CI

## 18.1 README 必须诚实

当前 README 宣称 production-grade、620+ tests，但 GitHub 无 release、PyPI 仍是 0.1.0。([GitHub][1])

修改 README 顶部：

```text
SeekFlow v0.2.5-beta

Status:
- main branch: beta
- PyPI stable: 0.1.0 until v0.2.5 is published
- production use: only after passing security checklist
```

如果完成发布，则改为：

```text
SeekFlow v0.2.5
Production readiness: security-hardened beta
```

不要使用 “production-grade” 直到所有安全测试通过。

## 18.2 添加 feature matrix

```text
Feature                    Status
DeepSeek V4 thinking       stable
Tool-call reasoning replay stable
Safe built-in tools        stable
MCP                        beta
Python sandbox             beta / container recommended
JSON repair                stable
Prompt cache compiler      beta
Cost preflight             stable
```

## 18.3 CI

新增 GitHub Actions：

```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install -e ".[dev]"
      - run: ruff check src tests
      - run: mypy src/seekflow
      - run: pytest -q
```

## 18.4 发布

```text
1. bump pyproject version
2. tag v0.2.5
3. create GitHub release
4. publish PyPI using Trusted Publishing
5. verify pip install seekflow==0.2.5
6. run import smoke test against installed wheel
```

PyPI 当前 0.1.0 未使用 Trusted Publishing，修复发布链路时应改用 Trusted Publishing。([PyPI][2])

---

# 19. 最终测试矩阵

Claude Code 完成后必须能跑：

```bash
python -m pip install -e ".[dev]"
ruff check src tests
mypy src/seekflow
pytest -q
```

必须新增并通过：

```text
tests/test_import_smoke.py
tests/test_agent_builtin_tools.py
tests/deepseek/test_adapter_params.py
tests/deepseek/test_message_protocol.py
tests/test_runtime_trimming_protocol.py
tests/test_retry_executor_errors.py
tests/test_stream_retry.py
tests/test_circuit_breaker_semantics.py
tests/test_tool_policy_enforcement.py
tests/test_files_security.py
tests/test_security_http.py
tests/test_builtin_fetch_url.py
tests/test_builtin_python_exec.py
tests/test_builtin_sqlite.py
tests/test_json_output_pipeline.py
tests/test_tool_argument_repair_safety.py
tests/test_model_registry.py
tests/test_cost_budget.py
tests/test_cache_compiler.py
tests/test_cache_protocol_invariants.py
tests/test_mcp_executor.py
```

最低验收标准：

```text
- import smoke 100% pass
- allow_filesystem/network/python/sqlite 不再 ImportError
- DeepSeek thinking tool-call reasoning_content 不丢失
- thinking mode 下不发送 tool_choice
- non-thinking tool-call 不强制 reasoning_content
- RetryExecutor 能处理自定义 DeepSeekAPIError
- stream 已 yield 后不 retry
- ToolPolicy 所有关键字段被 executor 强制执行
- .env / private key / path traversal / symlink escape 被阻断
- fetch_url SSRF regression pass
- Python exec 无 sandbox 不可注册
- SQLite readonly 阻断写操作
- model alias / pricing / usage 只有一个 source of truth
- README、pyproject、PyPI/release 策略一致
```

---

# 20. Claude Code 可直接执行的任务说明

把下面这段直接交给 Claude Code：

```text
你要修复 WYZAAACCC/SeekFlow。不要重写整个项目，按现有架构做闭环式修复。

最高优先级：
1. 新增 src/seekflow/tools/builtins.py，提供 make_calculate / make_read_file / make_write_file / make_list_dir / make_fetch_url / make_python_exec / make_sqlite_query。所有 built-in tools 必须返回带 ToolPolicy 的 ToolDefinition，并且必须走中央安全模块。
2. 增加 import smoke tests，确保 seekflow、DeepSeekAgent、ToolRuntime、DeepSeekClient、ToolExecutor、PolicyEngine、ToolExecutionContext、ApprovalRequest、seekflow.tools.builtins 均可 import。
3. 新增或改造 DeepSeekAdapter，把 thinking、reasoning_effort、tool_choice、developer role、max_tokens、response_format、model alias、usage normalization 全部集中到 adapter 层。
4. 修复 DeepSeek thinking tool-call 协议：thinking mode 下 assistant tool_calls 必须保留 reasoning_content；non-thinking mode 不强制 reasoning_content；assistant tool_calls content None 修为 ""；tool_call_id 必须一一对应。
5. 修复 runtime：thinking mode 下绝不发送 tool_choice，包括 final step tool_choice="none"。
6. 修复 RetryExecutor：捕获 DeepSeekAPIError；429/5xx bounded retry；400/401/402/403/404 不计入 circuit breaker；stream 在 yield 任何 chunk 后禁止自动 retry。
7. ToolExecutor 必须完整执行 ToolPolicy：max_input_bytes、max_output_bytes、timeout_s、workspace_root、allowed_domains、capabilities、risk、requires_approval。
8. files.py 的 embed_files_into_message 必须要求 workspace_root，并调用 validate_file_access；默认禁止 .env、私钥、证书、云凭据、.git、node_modules、.venv。
9. make_fetch_url 必须使用 hardened HTTP client，禁止直接 urllib/requests；必须防 SSRF、redirect to private IP、userinfo trick、localhost/private/reserved IP。
10. make_python_exec 必须拒绝 NoSandbox；ProcessSandbox 要 kill-safe timeout；ContainerSandbox 增强 docker hardening。
11. make_sqlite_query 默认 readonly，只允许 SELECT/WITH SELECT/安全 PRAGMA，禁止 ATTACH/INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/VACUUM。
12. 统一 ModelRegistry/Pricing/Usage/Budget，删除 agent.py、budget.py、cost.py 等多处硬编码价格；deepseek-chat -> deepseek-v4-flash non-thinking，deepseek-reasoner -> deepseek-v4-flash thinking。
13. JSON Output pipeline 必须设置 response_format={"type":"json_object"}，prompt 包含 JSON 指令和示例，处理 empty content，parse 后 schema validate，repair 后再次 validate，危险工具低置信 repair 禁止执行。
14. 修复 README 和发布说明，不要在未完成验收前宣称 production-grade；版本、release、PyPI 状态必须一致。

禁止：
- 不要删除 safety tests。
- 不要为了兼容让默认 policy 更宽松。
- 不要在 thinking mode 下发送 tool_choice。
- 不要压缩或删除 tool-call assistant 的 reasoning_content。
- 不要在 stream 已 yield 后自动 retry。
- 不要让文件、网络、Python、SQLite 工具绕过 ToolExecutor 和 PolicyEngine。

完成后必须通过：
ruff check src tests
mypy src/seekflow
pytest -q

必须新增测试：
tests/test_import_smoke.py
tests/test_agent_builtin_tools.py
tests/deepseek/test_adapter_params.py
tests/deepseek/test_message_protocol.py
tests/test_runtime_trimming_protocol.py
tests/test_retry_executor_errors.py
tests/test_stream_retry.py
tests/test_circuit_breaker_semantics.py
tests/test_tool_policy_enforcement.py
tests/test_files_security.py
tests/test_security_http.py
tests/test_builtin_fetch_url.py
tests/test_builtin_python_exec.py
tests/test_builtin_sqlite.py
tests/test_json_output_pipeline.py
tests/test_tool_argument_repair_safety.py
tests/test_model_registry.py
tests/test_cost_budget.py
tests/test_cache_compiler.py
tests/test_cache_protocol_invariants.py
tests/test_mcp_executor.py
```

---

# 21. 最终 Definition of Done

这个项目只有在满足下面条件后，才能重新宣称“production-hardened beta”：

```text
Functional:
  - pip install 后所有 public imports 正常；
  - README quick start 可运行；
  - dangerous tools opt-in 可运行；
  - DeepSeek thinking/tool-call 多轮协议正确。

Security:
  - 默认无危险工具；
  - 所有工具强制 ToolPolicy；
  - 文件 sandbox 不可绕过；
  - HTTP SSRF regression pass；
  - Python exec 必须 sandbox；
  - SQLite 默认 readonly；
  - audit 不泄露 secret。

Reliability:
  - retry bounded；
  - stream retry 安全；
  - circuit breaker 不被 400/401/403 污染；
  - timeout kill-safe；
  - context trimming 不破坏 tool-call blocks。

DeepSeek-native:
  - thinking 参数正确；
  - reasoning_content replay 正确；
  - thinking mode 不发送 tool_choice；
  - developer role 处理正确；
  - max_tokens 字段正确；
  - JSON Output pipeline 正确；
  - cache hit/miss usage 和成本正确。

Release:
  - README 与实际能力一致；
  - pyproject version、GitHub tag、GitHub release、PyPI version 一致；
  - PyPI 使用 Trusted Publishing；
  - CI 通过 ruff/mypy/pytest；
  - security checklist 写入 docs。
```

**这份方案的核心思想：不要再继续堆功能点，而是把当前已有模块打通成一条不可绕过的主路径。SeekFlow 真正值得做的方向不是“又一个 agent 框架”，而是“DeepSeek 协议正确、成本可控、安全默认、极轻量”的 agent runtime。**

[1]: https://github.com/WYZAAACCC/SeekFlow "GitHub - WYZAAACCC/SeekFlow: DeepSeek-native agent framework with production-grade reliability · GitHub"
[2]: https://pypi.org/project/seekflow/ "seekflow · PyPI"
[3]: https://github.com/WYZAAACCC/SeekFlow/tree/main/src/seekflow "SeekFlow/src/seekflow at main · WYZAAACCC/SeekFlow · GitHub"
[4]: https://github.com/WYZAAACCC/SeekFlow/tree/main/src/seekflow/tools "SeekFlow/src/seekflow/tools at main · WYZAAACCC/SeekFlow · GitHub"
[5]: https://api-docs.deepseek.com/api/create-chat-completion "Create Chat Completion | DeepSeek API Docs"
[6]: https://api-docs.deepseek.com/guides/thinking_mode "Thinking Mode | DeepSeek API Docs"
[7]: https://api-docs.deepseek.com/quick_start/agent_integrations/oh_my_pi "Using DeepSeek with Oh My Pi | DeepSeek API Docs"
[8]: https://api-docs.deepseek.com/guides/json_mode "JSON Output | DeepSeek API Docs"
[9]: https://api-docs.deepseek.com/quick_start/pricing "Models & Pricing | DeepSeek API Docs"
