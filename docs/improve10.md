# SeekFlow 生产级跨越技术修复与改进方案 RFC

下面这份可以直接交给 Claude 作为工程执行文档。它不是“泛泛优化建议”，而是面向 SeekFlow 现有代码结构、前两份审计结论和 DeepSeek 官方协议约束整理出的**可落地重构路线**。

---

# 0. 总目标

把 SeekFlow 从当前的 **security-hardening beta / 半成品生产加固状态**，推进到：

> **半生产级：可用于可信内部用户 + 有限工具集 + 明确 sandbox + 明确 policy 的生产前环境。**
> **生产级：可用于非完全可信输入、可观测、可审计、可回放、可限流、可配置安全边界的 DeepSeek-native secure tool runtime。**

仓库 README 当前仍标记为 `v0.2.5-dev`、`security-hardening beta`，并写明主分支在 v0.2.5 发布和完整 security checklist 通过前不建议生产使用；仓库页面也显示没有正式 GitHub Releases。这个状态说明改造应以“安全语义冻结 + 运行时内核重构 + DeepSeek 协议正确性”为主，而不是继续堆功能。([GitHub][1])

---

# 1. 最高层判断

SeekFlow 的方向是对的，但必须收敛。

它不应该变成另一个 LangChain、CrewAI 或通用 workflow 框架。它应该定位为：

> **DeepSeek-native、tool-safety-first、cache-aware、strict-schema-first 的轻量 Agent Runtime。**

核心内核只有四个：

1. **DeepSeek 协议正确性**
   thinking、`reasoning_content`、tool call、strict schema、stream usage、JSON mode、FIM、prompt cache 全部由统一 adapter/state machine 处理。

2. **工具执行安全性**
   policy、approval、sandbox、runner、timeout、audit 必须 fail-closed。

3. **成本与上下文可控性**
   usage 归一化、cache hit/miss、budget、token estimate、context trim 全部结构化。

4. **可观测与可审计**
   run id、step id、tool audit、redaction、OTel、replay fixture，不记录敏感 reasoning 原文作为默认行为。

---

# 2. 非谈判式原则

Claude 执行时必须遵守这些原则：

## 2.1 安全默认拒绝

无 policy 的工具默认拒绝。
无 workspace 的文件工具默认拒绝。
无 allowed domains 的网络工具默认拒绝。
无 sandbox 的 code execution 默认拒绝。
无 approval handler 的 destructive 工具默认拒绝。

当前 `PolicyEngine` 已有 strict/compat、risk、capability 等结构，但 legacy context 和兼容路径仍容易制造安全语义不一致；这部分必须收敛到统一 typed context。([GitHub][2])

## 2.2 timeout 必须真实终止

当前工具执行器里出现 `concurrent.futures` / `ThreadPoolExecutor` 风格的 per-tool timeout 设计；这种 timeout 不能可靠杀死阻塞线程或死循环函数，最多只能让主线程等超时。([GitHub][3])

生产级要求：

* trusted pure function 可以 in-process；
* untrusted 或 side-effect 工具必须 process/container；
* timeout 后必须 hard kill；
* batch 执行必须有总 deadline；
* 不允许 zombie process。

## 2.3 DeepSeek 协议只能由 Adapter/StateMachine 生成

runtime、agent、client 不允许散落式拼 DeepSeek 参数。
`thinking`、`reasoning_effort`、`response_format`、`stream_options`、`strict`、`base_url/beta_base_url`、usage 解析都必须走统一 adapter。

DeepSeek 官方 Chat Completion 当前明确支持 `thinking` 对象、`reasoning_effort`，返回中包含 `reasoning_content`，tool call arguments 是模型生成的 JSON 字符串且需要用户侧校验；usage 里也有 `prompt_cache_hit_tokens`、`prompt_cache_miss_tokens` 和 reasoning token 明细。([DeepSeek API Docs][4])

## 2.4 stream 和 non-stream 必须共享业务状态机

DeepSeek streaming 在 `stream_options.include_usage` 时会额外返回一个 usage chunk，且该 chunk 的 `choices` 为空；如果 stream/non-stream 各写一套逻辑，usage、tool call 聚合、budget、trace 很容易不一致。([DeepSeek API Docs][4])

## 2.5 Prompt cache 只能“优化命中”，不能“保证命中”

DeepSeek context caching 默认开启，命中依赖后续请求完整匹配已持久化的 cache prefix unit；官方明确说这是 best-effort，不能保证 100% 命中，且 cache 会在数小时到数天内清理。([DeepSeek API Docs][5])

所以模块名和文档里不要宣称“强制缓存命中”，应该说：

> prompt layout stabilization / cache hit optimization / cache instability analysis。

---

# 3. 目标架构

建议重构成以下边界：

```text
seekflow/
  core/
    messages.py
    usage.py
    run_state.py
    errors.py

  deepseek/
    adapter.py
    models.py
    config.py
    strict_schema.py
    json_output.py
    state_machine.py
    fake_server.py       # test helper, can live under tests

  runtime/
    tool_runtime.py
    stream_runtime.py
    events.py
    budget.py

  tools/
    registry.py
    schema.py
    executor.py
    runners.py
    planner.py
    audit.py

  security/
    policy.py
    context.py
    http.py
    fs.py
    sandbox.py
    redaction.py
    approval.py

  observability/
    trace.py
    otel.py
    replay.py
```

如果暂时不想大规模移动文件，至少要形成这些**逻辑边界**：

* `DeepSeekAdapter`：唯一协议转换层。
* `UsageRecord`：唯一 usage/cost/cache 数据结构。
* `RunStateMachine`：唯一 tool loop 状态机。
* `PolicyEngine`：唯一授权决策层。
* `ToolRunner`：唯一工具执行抽象。
* `AuditRecorder`：唯一审计事件出口。
* `StructuredOutputGuard`：唯一 JSON mode/结构化输出路径。

---

# 4. 改造阶段总览

| 阶段      | 目标                                         | 结果                            |
| ------- | ------------------------------------------ | ----------------------------- |
| Phase 0 | 稳住安全语义和 API 契约                             | 半生产级基础                        |
| Phase 1 | 重构工具执行内核                                   | 真实隔离、真实 timeout               |
| Phase 2 | DeepSeek 协议状态机                             | thinking/tool/stream/usage 正确 |
| Phase 3 | strict schema + JSON output + cache layout | DeepSeek-native 优势成型          |
| Phase 4 | 可观测、审计、发布工程                                | 可进入生产试点                       |
| Phase 5 | 企业级增强                                      | 多租户/队列/持久化/治理                 |

---

# 5. Phase 0：安全语义与基础契约修复

## 5.1 新增 `UsageRecord`

### 新文件

`src/seekflow/core/usage.py` 或 `src/seekflow/usage.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping


@dataclass(frozen=True)
class UsageRecord:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
    reasoning_tokens: int = 0
    source: Literal["non_stream", "stream", "estimated", "unknown"] = "unknown"
    raw: Mapping[str, Any] | None = None

    @property
    def cache_hit_ratio(self) -> float:
        if self.prompt_tokens <= 0:
            return 0.0
        return self.prompt_cache_hit_tokens / self.prompt_tokens

    @property
    def cache_miss_ratio(self) -> float:
        if self.prompt_tokens <= 0:
            return 0.0
        return self.prompt_cache_miss_tokens / self.prompt_tokens
```

### 修改点

* `deepseek/adapter.py`

  * `NormalizedUsage` 改为或桥接到 `UsageRecord`。
  * 增加 `normalize_usage(raw, source)`。
  * 统一读取：

    * `usage.prompt_tokens`
    * `usage.completion_tokens`
    * `usage.total_tokens`
    * `usage.prompt_cache_hit_tokens`
    * `usage.prompt_cache_miss_tokens`
    * `usage.completion_tokens_details.reasoning_tokens`

DeepSeek 官方 usage 明确规定 `prompt_tokens = prompt_cache_hit_tokens + prompt_cache_miss_tokens`，并且 reasoning tokens 位于 `completion_tokens_details.reasoning_tokens`。([DeepSeek API Docs][4])

### 禁止事项

* runtime 不允许再自己构造 `prompt_tokens_details.cached_tokens`。
* cost tracker 不允许直接读 raw usage。
* trace 不允许存多套 usage 结构。

### 验收测试

```text
tests/test_usage_record.py
- test_normalize_deepseek_top_level_cache_usage
- test_normalize_reasoning_tokens
- test_stream_usage_source
- test_missing_usage_defaults_to_zero
- test_prompt_tokens_cache_invariant_warning
```

---

## 5.2 修复 runtime 输入 mutation

### 问题

runtime 处理文件时直接修改传入 `messages`，然后再 deepcopy。这会污染调用方对象、破坏 cache layout、制造复用风险。前面读取到的 runtime 中确实存在 `copy`、`embed_files_into_message`、tool runtime 等入口逻辑，需要将 deepcopy 前置为硬约束。([GitHub][6])

### 修改方案

在所有 public entry：

* `ToolRuntime.chat`
* `ToolRuntime.chat_stream`
* `DeepSeekAgent.run`
* `AsyncToolRuntime.*`

入口第一行做：

```python
working_messages = copy.deepcopy(messages)
```

后续所有文件嵌入、trim、repair、append tool result，都只操作 `working_messages`。

### 验收测试

```python
def test_runtime_does_not_mutate_input_messages():
    original = [{"role": "user", "content": "hi"}]
    before = copy.deepcopy(original)

    runtime.chat(messages=original, files=[...])

    assert original == before
```

---

## 5.3 修复 strict beta endpoint 配置

### 问题

当前 `_make_client` 在 strict 模式下直接把 base URL 改成 `https://api.deepseek.com/beta`。这和 DeepSeek strict 要求 beta endpoint 的方向一致，但对企业 gateway、mock server、region endpoint 不友好。runtime 中可以看到 strict 时直接覆盖 base URL 的逻辑。([GitHub][6])

DeepSeek 官方 strict mode 要求使用 beta base URL，并且所有 function 都设置 `strict=true`。([DeepSeek API Docs][7])

### 修改方案

新增配置对象：

```python
@dataclass(frozen=True)
class DeepSeekClientConfig:
    base_url: str = "https://api.deepseek.com"
    beta_base_url: str = "https://api.deepseek.com/beta"
    strict_endpoint_policy: Literal["auto", "explicit", "error_if_missing"] = "auto"
```

runtime 初始化参数改为：

```python
base_url: str = "https://api.deepseek.com"
beta_base_url: str | None = None
strict_endpoint_policy: str = "auto"
```

行为：

* `strict=False`：使用 `base_url`。
* `strict=True` 且 `beta_base_url` 非空：使用 `beta_base_url`。
* `strict=True` 且 policy=`auto`：默认 `https://api.deepseek.com/beta`，但 trace 记录 endpoint switch。
* `strict=True` 且 policy=`error_if_missing`：无 `beta_base_url` 则报错。
* `strict=True` 且用户传入 custom `base_url` 但没传 `beta_base_url`：warning。

### 验收测试

```text
test_strict_uses_beta_base_url
test_strict_custom_gateway_requires_beta_url_when_error_policy
test_non_strict_uses_base_url
test_trace_records_endpoint_switch
```

---

## 5.4 Policy fail-closed

### 当前风险

`PolicyEngine` 已有 risk/capability/default dangerous disable 设计，但 legacy dict context、compat 模式、无 policy 工具容易放宽安全语义。([GitHub][2])

### 目标

统一安全上下文：

```python
@dataclass(frozen=True)
class ToolExecutionContext:
    dangerous_tools_enabled: bool = False
    allowed_capabilities: frozenset[str] = frozenset()
    max_risk: RiskLevel = "read"
    workspace_root: Path | None = None
    allowed_domains: frozenset[str] = frozenset()
    sandbox_required: bool = True
    approval_required_for: frozenset[RiskLevel] = frozenset({"destructive", "code_exec"})
    run_id: str = ""
    user_id: str | None = None
```

### 具体改动

1. `PolicyEngine.authorize()` 开头统一把 legacy context 转为 `ToolExecutionContext`。
2. `allow_no_policy=False` 作为默认值，且 strict mode 下不可覆盖。
3. `policy.risk != "read"` 且 `dangerous_tools_enabled=False`：拒绝。
4. `policy.capabilities - context.allowed_capabilities` 非空：拒绝。
5. `network.public_http` 能力：

   * `context.allowed_domains` 为空：拒绝。
   * 所有 URL 参数必须 strict validate。
6. `filesystem.*` 能力：

   * `workspace_root is None`：拒绝。
   * 所有 path 参数必须 safe join。
7. `code_exec`：

   * sandbox 不满足：拒绝。
8. `requires_approval=True`：

   * 没有 approval handler：拒绝，而不是静默通过。

### 验收测试

```text
test_no_policy_denied_by_default
test_legacy_context_does_not_bypass_capability_check
test_network_without_allowed_domains_denied
test_filesystem_without_workspace_denied
test_code_exec_without_sandbox_denied
test_destructive_without_approval_handler_denied
```

---

## 5.5 Config Linter / Doctor

新增 CLI：

```bash
seekflow doctor
seekflow security lint
seekflow deepseek preflight
```

检查：

* strict=true 但无 beta_base_url。
* network tool 无 allowed_domains。
* file tool 无 workspace_root。
* code_exec 使用 NoSandbox。
* dangerous_tools=True 但没有 approval_handler。
* trace raw capture 开启。
* 依赖未锁定。
* pyproject 版本和 README 状态不一致。
* no GitHub Release 但 README 声称 production-grade。

---

# 6. Phase 1：工具执行内核重构

这是最重要阶段。它决定 SeekFlow 是否能从“看起来安全”变成“真的能限制工具”。

## 6.1 新增 ToolRunner 抽象

新文件：

`src/seekflow/tools/runners.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolRunRequest:
    run_id: str
    step: int
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    timeout_s: float
    risk: str
    capabilities: frozenset[str]


@dataclass(frozen=True)
class ToolRunResult:
    ok: bool
    result: Any = None
    error: str | None = None
    elapsed_ms: int = 0
    exit_code: int | None = None
    killed: bool = False
    sandbox: str = "none"


class ToolRunner(Protocol):
    name: str

    def run(self, request: ToolRunRequest, func: Any) -> ToolRunResult:
        ...
```

## 6.2 Runner 类型

### InProcessRunner

只允许：

* `risk == "read"`
* `parallel_safe=True`
* `trusted=True`
* 无 network/file/code capability
* timeout 仅作软限制

### ProcessRunner

用于：

* untrusted read-only；
* file read/write；
* network；
* 轻度 side-effect；
* 所有可能阻塞的工具。

要求：

* 使用 `multiprocessing.get_context("spawn")`。
* 子进程只拿最小 env。
* Unix 上设置 process group。
* timeout 后 terminate，宽限后 kill。
* 捕获 stdout/stderr 尺寸上限。
* 返回结构化 error。
* 不允许继承 secrets。

伪代码：

```python
class ProcessRunner:
    name = "process"

    def run(self, request: ToolRunRequest, func: Any) -> ToolRunResult:
        q = ctx.Queue(maxsize=1)
        p = ctx.Process(target=_child_entry, args=(q, func, request.arguments))
        start = time.monotonic()
        p.start()
        p.join(request.timeout_s)

        if p.is_alive():
            p.terminate()
            p.join(0.5)
            if p.is_alive():
                p.kill()
            return ToolRunResult(
                ok=False,
                error=f"Tool timed out after {request.timeout_s}s",
                elapsed_ms=...,
                killed=True,
                sandbox="process",
            )

        if q.empty():
            return ToolRunResult(ok=False, error="Tool process exited without result", ...)
        return q.get()
```

### ContainerRunner

用于：

* code_exec；
* shell；
* browser；
* untrusted MCP；
* destructive tool；
* 用户上传代码处理。

要求：

* `--network none` 默认。
* 非 root 用户。
* `--read-only`。
* tmpfs。
* memory/cpu/pids limit。
* no-new-privileges。
* drop capabilities。
* workspace 只读/读写按 policy 控制。
* timeout 后 `docker kill`。

## 6.3 RunnerSelector

新文件：

`src/seekflow/tools/planner.py`

```python
@dataclass(frozen=True)
class ExecutionPlan:
    runner: str
    requires_sandbox: bool
    timeout_s: float
    cache_allowed: bool
    parallel_allowed: bool
    audit_level: str
```

选择规则：

```text
if risk == "code_exec" or "code_exec" in capabilities:
    ContainerRunner
elif risk in {"write", "network", "destructive"}:
    ProcessRunner or ContainerRunner
elif trusted and risk == "read" and parallel_safe:
    InProcessRunner
else:
    ProcessRunner
```

## 6.4 修改 `ToolExecutor.execute`

当前执行链条注释是对的：parse → repair → lookup → coerce → policy → approval → sandbox → execute → sanitize → truncate → audit。([GitHub][3])

但要确保真的按这个链条执行：

1. parse arguments。
2. repair JSON。
3. lookup tool。
4. coerce arguments。
5. policy authorize。
6. approval。
7. build `ExecutionPlan`。
8. select runner。
9. runner.run。
10. sanitize/untrusted wrap。
11. truncate。
12. audit append。

不得出现任何绕过 runner 的 `tool_def.func(**arguments)`。

## 6.5 batch 执行

规则：

* read-only pure tools 可以并发。
* side-effect tools 串行。
* batch 有总 deadline。
* 任一 destructive 工具失败，不继续执行后续 destructive 工具。
* audit 中记录 batch id。

## 6.6 验收测试

必须新增：

```text
tests/tools/test_runner_timeout.py
- infinite loop tool is killed
- blocking sleep tool is killed
- process runner leaves no child process
- container runner receives no network by default

tests/tools/test_runner_selection.py
- trusted read tool uses in_process
- network tool uses process/container
- code_exec uses container
- destructive without approval denied

tests/tools/test_executor_no_bypass.py
- monkeypatch raw tool func to detect direct call bypass
```

---

# 7. Phase 2：DeepSeek 协议状态机

## 7.1 新增 `DeepSeekRunStateMachine`

新文件：

`src/seekflow/deepseek/state_machine.py`

核心状态：

```python
class StepKind(str, Enum):
    MODEL_REQUEST = "model_request"
    MODEL_DELTA = "model_delta"
    MODEL_COMPLETE = "model_complete"
    TOOL_CALL_DETECTED = "tool_call_detected"
    TOOL_EXECUTION = "tool_execution"
    TOOL_RESULT_APPENDED = "tool_result_appended"
    FINAL = "final"
    ERROR = "error"
```

状态机职责：

* 接收 model response 或 stream delta。
* 聚合 content。
* 聚合 reasoning_content。
* 聚合 tool_calls。
* 校验 tool_call arguments。
* 生成 tool messages。
* 归一化 usage。
* 判断是否继续 loop。
* 触发 budget check。
* 生成 trace event。

## 7.2 stream/non-stream 共用状态机

`chat()` 和 `chat_stream()` 只负责输入事件来源不同：

```text
non-stream:
  response -> state_machine.on_model_complete(response)

stream:
  chunk -> state_machine.on_model_delta(chunk)
  usage chunk -> state_machine.on_usage(chunk.usage)
  done -> state_machine.on_stream_done()
```

业务判断只写一份。

## 7.3 reasoning 处理

DeepSeek response 中 `message.reasoning_content` 是 thinking mode 的思考内容。([DeepSeek API Docs][4])

默认策略：

* 可以用于内部 consistency check。
* 可以进入 ephemeral in-memory state。
* 默认不落盘 trace。
* debug 模式下落盘必须 redaction。
* 对用户最终返回不暴露 raw reasoning。
* 只暴露：

  * `reasoning_tokens`
  * `reasoning_present: bool`
  * `reasoning_summary`，如果明确启用且安全。

## 7.4 Tool call arguments

官方明确说 tool call 的 `function.arguments` 是模型生成的 JSON 格式字符串，但模型不总是生成有效 JSON，也可能生成 schema 外参数，必须在代码中验证。([DeepSeek API Docs][4])

状态机要求：

* arguments string 先 parse。
* parse fail 才 repair。
* repair 后要 schema validate。
* dangerous 工具 repair confidence 不足则拒绝。
* schema 外字段默认拒绝或剔除，不能静默执行。

## 7.5 Fake DeepSeek Server

新增测试辅助：

```text
tests/fakes/deepseek_server.py
tests/fixtures/deepseek/
  thinking_tool_call.json
  stream_tool_call_chunks.jsonl
  stream_usage_chunk.jsonl
  json_empty_content.json
  malformed_tool_args.json
  strict_schema_error.json
  cache_usage_hit_miss.json
```

验收测试：

```text
test_thinking_tool_call_roundtrip
test_stream_fragmented_tool_args_roundtrip
test_stream_usage_empty_choices_chunk
test_malformed_tool_args_repaired_or_denied
test_reasoning_not_persisted_by_default
```

---

# 8. Phase 3：DeepSeek 极致适配

## 8.1 StrictSchemaCompiler V2

DeepSeek strict mode 要求：

* beta endpoint；
* 所有 function 设置 `strict=true`；
* server 会校验 JSON Schema；
* object 的所有 properties 必须 required；
* `additionalProperties=false`；
* strict mode 只支持一部分 JSON Schema 类型。([DeepSeek API Docs][7])

新增文件：

`src/seekflow/deepseek/strict_schema.py`

功能：

```python
class StrictSchemaCompiler:
    def compile(self, schema: dict) -> dict:
        ...

    def validate_compatibility(self, schema: dict) -> list[SchemaIssue]:
        ...

    def compile_tool(self, tool_def: ToolDefinition) -> dict:
        ...
```

处理规则：

* 所有 object：

  * `required = list(properties.keys())`
  * `additionalProperties = False`
* 删除 unsupported keywords：

  * `minLength`
  * `maxLength`
  * 其他 DeepSeek strict 不支持字段
* 保留支持字段：

  * `pattern`
  * `format`
  * `enum`
  * `anyOf`
* nested object 递归闭合。
* optional 字段转成 `anyOf: [type, {"type": "null"}]` 或由项目约定处理。
* schema 太复杂时 fail-fast。

验收测试：

```text
test_all_properties_required
test_additional_properties_false_recursive
test_unsupported_keywords_removed_or_error
test_optional_field_normalization
test_strict_tool_schema_snapshot
```

## 8.2 StructuredOutputGuard

DeepSeek JSON Output 要求：

1. 设置 `response_format={"type":"json_object"}`；
2. system 或 user prompt 中包含 “json” 并提供期望 JSON 示例；
3. 合理设置 `max_tokens`；
4. API 偶尔可能返回空 content。([DeepSeek API Docs][8])

新增文件：

`src/seekflow/deepseek/json_output.py`

```python
@dataclass(frozen=True)
class StructuredOutputSpec:
    schema: dict
    example: dict | None = None
    max_tokens: int | None = None
    repair: bool = True
    require_schema_validation: bool = True


class StructuredOutputGuard:
    def prepare_messages(self, messages, spec): ...
    def prepare_params(self, params, spec): ...
    def parse_response(self, content, spec): ...
```

行为：

* 自动注入短 JSON 示例。
* 如果 prompt 不含 json，自动补充 system instruction。
* 自动设置 response_format。
* empty content retry 一次。
* finish_reason=`length` 直接结构化失败，不 silent repair。
* parse 后 schema validate。
* repair 后返回 `repaired=True` metadata。

验收测试：

```text
test_json_keyword_injected
test_response_format_set
test_empty_content_retried_once
test_length_finish_reason_fails
test_repair_metadata_returned
test_schema_validation_error_exposed
```

## 8.3 PromptLayoutCompiler / CacheInstabilityAnalyzer

DeepSeek cache 默认开启，命中依赖完整匹配 cache prefix unit，长输入和多轮对话中可命中共同前缀；usage 中通过 `prompt_cache_hit_tokens` 和 `prompt_cache_miss_tokens` 观察。([DeepSeek API Docs][5])

新增文件：

`src/seekflow/deepseek/cache_layout.py`

不要宣称“创建缓存”，只做 prompt layout 优化。

### Prompt 分层

```text
L0 Framework invariant prefix
  - runtime protocol
  - safety rules
  - tool result is untrusted data

L1 Agent static identity
  - role
  - goal
  - backstory
  - stable behavior constraints

L2 Tool schema stable block
  - sorted canonical tool schemas
  - schema hash
  - no timestamps
  - no random order

L3 User/static documents
  - stable long docs
  - deterministic chunk order
  - content hash

L4 Dynamic request tail
  - current user query
  - recent volatile memory
  - tool results
  - timestamps/request ids
```

### 输出

```python
@dataclass(frozen=True)
class PromptLayoutReport:
    prefix_hash: str
    cacheable_message_count: int
    dynamic_start_index: int
    unstable_fields: list[str]
    estimated_cacheable_chars: int
```

### CacheInstabilityAnalyzer

输入：`PromptLayoutReport + UsageRecord`
输出：

```text
cache_hit_ratio
likely_instability_reason
- dynamic timestamp in system prompt
- tool schema order changed
- document chunk order changed
- model changed
- user_id/cache isolation changed
- first request not yet persisted
```

验收测试：

```text
test_tool_schema_order_stable
test_timestamp_detected_as_unstable
test_prefix_hash_stable_for_same_tools
test_cache_hit_ratio_from_usage_record
```

## 8.4 FIM Pipeline

DeepSeek FIM 使用 beta base URL，示例通过 completions API 传入 `prompt`、`suffix`、`max_tokens`。([DeepSeek API Docs][9])

目标不是简单 wrapper，而是代码补全/编辑 pipeline。

新增：

`src/seekflow/deepseek/fim.py` 或重构现有 `fim.py`

功能：

* prefix/suffix token budget。
* 自动语言检测。
* AST-aware 截断。
* post-validate：

  * Python: `ast.parse`
  * JS/TS: 可选外部 checker
  * JSON/YAML: parser
* 输出 diff，不直接覆盖文件。
* FIM 使用 `beta_base_url`，不要复用 chat base URL。

验收测试：

```text
test_fim_uses_beta_base_url
test_fim_truncates_prefix_suffix
test_python_fim_ast_validate
test_fim_returns_diff
```

---

# 9. Phase 4：可观测性、审计与发布工程

## 9.1 Trace 模型

新增统一事件：

```python
@dataclass(frozen=True)
class RunEvent:
    run_id: str
    step: int
    kind: str
    timestamp: float
    payload: dict[str, Any]
    redacted: bool = True
```

事件类型：

```text
run.start
model.request
model.response
model.stream.delta
model.usage
tool.plan
tool.policy_decision
tool.approval_requested
tool.approval_result
tool.execution_start
tool.execution_end
tool.audit
budget.check
cache.report
run.final
run.error
```

默认禁止 payload 包含：

* API key；
* raw reasoning_content；
* raw file content；
* raw tool result；
* full user prompt，除非 debug raw capture 明确开启。

## 9.2 AuditRecord

`ToolAuditRecord` 已存在雏形，应独立成稳定结构。当前 executor 源码里已有 audit record 字段，如 timestamp、tool_name、args_hash、result_hash、latency、policy decision、risk level 等。([GitHub][3])

增强为：

```python
@dataclass(frozen=True)
class ToolAuditRecord:
    run_id: str
    step: int
    tool_call_id: str
    tool_name: str
    args_hash: str
    result_hash: str | None
    policy_decision: str
    policy_reason: str
    approval_id: str | None
    runner: str
    sandbox: str
    timeout_s: float
    elapsed_ms: int
    ok: bool
    error_type: str | None
    killed: bool
    redactions: int
    hmac: str | None = None
```

## 9.3 OTel

optional extra，不强制核心依赖。

span 设计：

```text
seekflow.run
  seekflow.model.call
  seekflow.tool.call
  seekflow.policy.authorize
  seekflow.budget.check
  seekflow.json.repair
  seekflow.cache.analyze
```

span attributes 只放安全 metadata：

```text
model.name
thinking.enabled
tool.name
tool.risk
policy.allowed
usage.prompt_tokens
usage.cache_hit_tokens
usage.cache_miss_tokens
duration_ms
```

## 9.4 发布工程

当前 pyproject 仍是 beta classifier，并且 mypy strict 下对 runtime、agent、mcp、compat、fim、structured 等核心模块有 ignore_errors 逐步迁移配置。([GitHub][10])

生产前要求：

* GitHub Release。
* SemVer。
* CHANGELOG。
* SECURITY.md。
* signed tag。
* wheel build。
* SBOM。
* dependency lock。
* CI matrix：

  * Python 3.10/3.11/3.12/3.13；
  * OpenAI SDK tested range；
  * pydantic 2.x；
  * Linux/macOS。
* ruff pass。
* mypy 逐步移除核心模块 ignore：

  * 先移除 `seekflow.deepseek.*`
  * 再移除 `seekflow.tools.*`
  * 再移除 `seekflow.runtime`
  * 最后 agent/mcp/compat。

---

# 10. Phase 5：企业级增强，非第一优先级

这些不要一开始就做，避免把轻量框架做臃肿。

## 10.1 Durable Run Store

接口优先：

```python
class RunStore(Protocol):
    def create_run(...)
    def append_event(...)
    def get_run(...)
    def list_runs(...)
```

默认 in-memory。
插件支持 SQLite/Postgres。

## 10.2 Rate Limit / Backpressure

提供接口：

```python
class RateLimiter(Protocol):
    def acquire(self, key: str, cost: int = 1) -> bool:
        ...
```

默认 no-op。
生产插件可以 Redis。

## 10.3 Approval Workflow

核心只定义：

```python
class ApprovalHandler(Protocol):
    def request_approval(self, request: ApprovalRequest) -> ApprovalDecision:
        ...
```

不要内置 UI。

## 10.4 Multi-tenant Policy Profile

```yaml
profiles:
  internal_readonly:
    max_risk: read
    capabilities: ["filesystem.read"]
  research_network:
    max_risk: network
    capabilities: ["public_http"]
    allowed_domains: ["docs.deepseek.com"]
  admin_code_exec:
    max_risk: code_exec
    requires_approval: true
    sandbox: container
```

---

# 11. Claude 执行顺序

下面是建议直接给 Claude 的任务顺序。

## PR 1：基础契约修复

目标：不改变大架构，先修危险 API 语义。

修改：

```text
src/seekflow/core/usage.py
src/seekflow/deepseek/adapter.py
src/seekflow/runtime.py
src/seekflow/async_runtime.py
src/seekflow/client.py
src/seekflow/cost.py
src/seekflow/trace/*
tests/test_usage_record.py
tests/test_runtime_immutability.py
```

验收：

```bash
pytest tests/test_usage_record.py tests/test_runtime_immutability.py
ruff check src tests
```

## PR 2：strict beta URL 配置化

修改：

```text
src/seekflow/deepseek/config.py
src/seekflow/runtime.py
src/seekflow/client.py
tests/test_deepseek_config.py
```

验收：

```bash
pytest tests/test_deepseek_config.py
```

## PR 3：Policy fail-closed

修改：

```text
src/seekflow/security/context.py
src/seekflow/policy.py
src/seekflow/types.py
tests/security/test_policy_fail_closed.py
```

验收：

```bash
pytest tests/security/test_policy_fail_closed.py
```

不得破坏 quickstart，只能让危险工具需要显式 opt-in。

## PR 4：ToolRunner 内核

修改：

```text
src/seekflow/tools/runners.py
src/seekflow/tools/planner.py
src/seekflow/tools/executor.py
src/seekflow/sandbox.py
tests/tools/test_runner_timeout.py
tests/tools/test_runner_selection.py
tests/tools/test_executor_no_bypass.py
```

验收：

```bash
pytest tests/tools/test_runner_timeout.py tests/tools/test_runner_selection.py
```

这是最大 PR，可以拆成：

* 4A：Runner abstraction；
* 4B：ProcessRunner；
* 4C：ContainerRunner；
* 4D：Executor integration。

## PR 5：DeepSeek 状态机

修改：

```text
src/seekflow/deepseek/state_machine.py
src/seekflow/runtime.py
src/seekflow/async_runtime.py
tests/fakes/deepseek_server.py
tests/deepseek/test_state_machine.py
tests/deepseek/fixtures/*
```

验收：

```bash
pytest tests/deepseek/test_state_machine.py
```

## PR 6：StructuredOutputGuard

修改：

```text
src/seekflow/deepseek/json_output.py
src/seekflow/structured.py
tests/deepseek/test_json_output_guard.py
```

验收：

```bash
pytest tests/deepseek/test_json_output_guard.py
```

## PR 7：StrictSchemaCompiler

修改：

```text
src/seekflow/deepseek/strict_schema.py
src/seekflow/tools/strict.py
tests/deepseek/test_strict_schema.py
tests/snapshots/strict_schema/*
```

验收：

```bash
pytest tests/deepseek/test_strict_schema.py
```

## PR 8：Prompt cache layout

修改：

```text
src/seekflow/deepseek/cache_layout.py
src/seekflow/cache.py
tests/deepseek/test_cache_layout.py
```

验收：

```bash
pytest tests/deepseek/test_cache_layout.py
```

## PR 9：Trace/Audit/Redaction

修改：

```text
src/seekflow/observability/*
src/seekflow/trace/*
src/seekflow/security/redaction.py
src/seekflow/tools/audit.py
tests/observability/*
```

验收：

```bash
pytest tests/observability
```

## PR 10：Docs/Release/Security

修改：

```text
README.md
SECURITY.md
RELEASING.md
docs/security/threat-model.md
docs/security/levels.md
docs/deepseek/protocol.md
docs/production-checklist.md
pyproject.toml
.github/workflows/*
```

验收：

```bash
pytest
ruff check
mypy src/seekflow/deepseek src/seekflow/tools src/seekflow/security
```

---

# 12. 安全等级定义

必须写进文档。

## Level 0：本地可信脚本

* 可信用户。
* 可信工具。
* NoSandbox 可接受。
* 不建议联网。

## Level 1：内部可信用户

* dangerous tools 显式开启。
* workspace root 必填。
* trace redaction 开启。
* network allowlist 必填。

## Level 2：非完全可信 prompt，可信工具

* fail-closed policy。
* ProcessRunner。
* approval handler。
* hardened HTTP。
* no raw reasoning trace。

## Level 3：非可信工具 / MCP / network

* ContainerRunner。
* egress gateway。
* signed audit。
* no direct requests/httpx。
* resource limit。
* replay tests。

## Level 4：多租户 SaaS

* tenant isolation。
* durable run store。
* per-tenant rate limit。
* per-tenant policy profile。
* encryption。
* admin approval workflow。
* compliance logging。

改造完成 Phase 0–2 后，SeekFlow 可以宣称接近 **Level 2 半生产级**。
完成 Phase 3–4 后，才可谨慎宣称 **Level 3 生产试点级**。

---

# 13. 关键验收标准

## 13.1 安全验收

必须全部通过：

```text
SSRF:
- http://127.0.0.1 denied
- http://localhost denied
- http://169.254.169.254 denied
- IPv6 loopback denied
- private DNS resolution denied
- redirect to private IP denied
- no allowed_domains denied

Filesystem:
- ../ traversal denied
- symlink escape denied
- absolute path outside workspace denied
- workspace missing denied

Tool execution:
- infinite loop killed
- blocking IO killed
- no zombie process
- code_exec without container denied
- destructive without approval denied

Trace:
- API key redacted
- JWT redacted
- reasoning_content not persisted by default
- file content not persisted by default
```

## 13.2 DeepSeek 协议验收

```text
Thinking:
- thinking enabled params correct
- reasoning_content parsed
- reasoning tokens recorded
- no raw reasoning in default trace

Tool calls:
- malformed arguments repaired or denied
- schema-invalid args denied
- strict schema all tools strict=true
- strict endpoint uses beta_base_url

Streaming:
- fragmented tool calls aggregate correctly
- final usage chunk parsed
- stream/non-stream same final result under same fake fixture

JSON:
- response_format set
- json prompt injected
- empty content retry
- finish_reason length fails structured

Cache:
- prompt_cache_hit_tokens parsed
- prompt_cache_miss_tokens parsed
- hit ratio calculated
- unstable prefix diagnosed
```

## 13.3 发布验收

```text
- README status matches pyproject status
- GitHub Release exists
- CHANGELOG updated
- SECURITY.md updated
- production checklist passed
- SBOM generated
- dependency audit passed
- mypy core modules pass
```

---

# 14. 应该删除或降级的内容

这些内容会误导生产使用，应调整：

1. **“production-grade reliability/security” 不应出现在默认宣传位**，除非 Phase 3–4 完成。当前 README 同时写 beta 和生产安全，会造成认知冲突。([GitHub][1])

2. **“CacheCompiler 90%+ hit” 不应作为保证。** DeepSeek cache 是 best-effort，不能保证固定命中率。([DeepSeek API Docs][5])

3. **“per-tool timeout safe” 不应在使用 ThreadPoolExecutor 时宣传为强安全边界。** 线程 timeout 不是 hard kill。当前 executor 确实围绕 per-tool timeout 和 concurrent futures 设计，需要重构后才能这样宣传。([GitHub][3])

4. **NoSandbox 只能用于 trusted local dev。** 不能在 production quickstart 中给人“默认沙箱安全”的错觉。

---

# 15. 最终给 Claude 的执行提示

可以把下面这一段直接放进 Claude：

```text
你要改造 WYZAAACCC/SeekFlow，使其从 security-hardening beta 走向半生产级/生产级 DeepSeek-native secure tool runtime。

请不要把它改成通用 LangChain。核心目标是：
1. DeepSeek 协议正确：thinking、reasoning_content、tool calls、stream usage、JSON output、strict schema、FIM、prompt cache。
2. 工具执行安全：fail-closed policy、approval、sandbox、process/container runner、hard timeout、audit。
3. 成本可控：UsageRecord 统一 usage/cost/cache hit/miss/reasoning tokens。
4. 可观测可审计：trace redaction、audit record、run/step event、replay fixture。
5. 发布可信：security docs、doctor/linter、tests、CI、release checklist。

请按 PR 顺序执行：
PR1 UsageRecord + runtime immutability。
PR2 strict beta_base_url 配置化。
PR3 Policy fail-closed。
PR4 ToolRunner/ProcessRunner/ContainerRunner 重构。
PR5 DeepSeekRunStateMachine，stream/non-stream 共享。
PR6 StructuredOutputGuard。
PR7 StrictSchemaCompiler V2。
PR8 PromptLayoutCompiler/CacheInstabilityAnalyzer。
PR9 Trace/Audit/Redaction。
PR10 Docs/CI/Release/Security checklist。

硬性要求：
- 不允许任何工具绕过 ToolRunner 直接执行。
- network.public_http 无 allowed_domains 必须拒绝。
- filesystem 工具无 workspace_root 必须拒绝。
- code_exec 无 container sandbox 必须拒绝。
- destructive 无 approval handler 必须拒绝。
- timeout 必须 hard kill 子进程或容器。
- runtime 不得修改调用方传入的 messages。
- DeepSeek usage 只能通过 UsageRecord。
- stream 和 non-stream 必须共享同一个状态机。
- 默认 trace 不得落盘 reasoning_content、API key、文件原文、完整 tool output。
- 每个 PR 必须新增对应测试，不能只改代码。
```

---

# 16. 最终判断

这套方案是工程可实现的，但不是一两个 patch 能完成。真正跨越的核心是：

> **从“有安全功能的 Agent 框架”，重构为“安全语义可证明的 DeepSeek-native runtime”。**

最重要的三件事：

1. **ToolRunner 内核重构**：解决 timeout、sandbox、side-effect、audit 的真实执行边界。
2. **DeepSeek 状态机**：解决 thinking、tool call、stream、usage、JSON、strict 的协议正确性。
3. **Policy fail-closed + Config Linter**：解决误配置和兼容路径带来的生产风险。

完成 Phase 0–2 后，可以达到可靠的半生产级。
完成 Phase 3–4 后，才有资格谨慎进入生产试点。

[1]: https://github.com/WYZAAACCC/SeekFlow "GitHub - WYZAAACCC/SeekFlow: DeepSeek-native agent framework with production-grade reliability · GitHub"
[2]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/policy.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/executor.py "raw.githubusercontent.com"
[4]: https://api-docs.deepseek.com/api/create-chat-completion "Create Chat Completion | DeepSeek API Docs"
[5]: https://api-docs.deepseek.com/guides/kv_cache "Context Caching | DeepSeek API Docs"
[6]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/runtime.py "raw.githubusercontent.com"
[7]: https://api-docs.deepseek.com/guides/tool_calls "Tool Calls | DeepSeek API Docs"
[8]: https://api-docs.deepseek.com/guides/json_mode "JSON Output | DeepSeek API Docs"
[9]: https://api-docs.deepseek.com/guides/fim_completion "FIM Completion (Beta) | DeepSeek API Docs"
[10]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/pyproject.toml "raw.githubusercontent.com"
