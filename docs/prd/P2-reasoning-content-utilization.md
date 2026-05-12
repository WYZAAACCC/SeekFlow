# P2: Reasoning Content 利用

## Problem Statement

DeepSeek 的 `deepseek-reasoner` 模型在调用工具前会产出一段 `reasoning_content`（思维链），描述模型为什么选择某个工具、它打算如何利用工具结果回答用户。

当前 `ChatResponse` 已经捕获了 `reasoning_content` 字段，但**完全未利用**——它只是在 response 对象里存着，不做任何处理。

两个痛点：
1. **工具选择错误无法预警**：模型在 reasoning 中说"我需要调用 `get_weather` 获取天气数据"，但实际 tool_call 却调了 `get_time`。这是模型幻觉的一种形式，当前完全无法检测。
2. **调试不透明**：开发者只能看到最终工具调用结果，看不到模型**为什么**这么选。排查"为什么模型调了这个工具"时完全黑盒。

## Solution

两层利用：

**第一层：工具选择一致性校验（非阻塞）**
- 解析 `reasoning_content`，提取其中提到的工具名称（正则匹配）
- 比对实际 `tool_calls` 中的名称
- 不一致时 → 记录 trace warning（不中断对话，仅可观测性）
- 统计不一致率，帮助用户评估模型可靠性

**第二层：流式 Reasoning 输出（可选）**
- `chat_stream()` 中增加 `reasoning` 事件类型，将 reasoning content 作为独立流输出
- 用户在 UI 中可以折叠/展开"模型思考过程"
- 类似 ChatGPT 的 "Thinking" 展示

## User Stories

1. 作为一个调试者，当模型的 reasoning 说"应该用工具 A"但实际调用了工具 B 时，我希望 trace 中有一条 warning，让我能回溯这个不一致。
2. 作为一个产品集成者，在流式对话 UI 中，我希望收到独立的 `reasoning` 事件，这样我可以把"模型思考过程"折叠展示，提升用户信任感。
3. 作为一个评估者，我希望在一次 benchmark 运行后能看到 reasoning-tool_call 不一致的统计（次数、比例、具体案例），用于量化模型可靠性。
4. 作为一个非流式调用者，我希望 `ToolRuntimeResult` 中包含本轮对话所有的 reasoning content 列表，方便事后分析。
5. 作为一个使用普通 `deepseek-chat` 模型的用户（非 reasoner），我不希望因为缺少 reasoning 字段而报错或降级——功能应该静默跳过。

## Implementation Decisions

### 模块划分

- **新增模块：`ReasoningInspector`** — 纯函数模块。`extract_tool_names(reasoning: str) -> set[str]` 从 reasoning 文本中提取工具名称（正则 `\b(get_weather|add|...)\b`，用已注册的工具名列表构建模式）。`check_consistency(reasoning: str, actual_tools: list[str]) -> ConsistencyResult` 返回一致/不一致/无 reasoning。
- **修改模块：`ToolRuntime.chat()` 和 `chat_stream()`** — 收到 response 后调用 `ReasoningInspector.check_consistency()`，不一致时记录 `reasoning_mismatch` trace 事件。
- **修改模块：`chat_stream()` 事件模型** — 新增 `StreamEvent(type="reasoning", content=...)` 事件类型。
- **修改模块：`ToolRuntimeResult`** — 新增 `reasoning_contents: list[str]` 字段，收集本对话中所有 reasoning。

### 工具名称提取策略

```python
# 仅在 reasoning 文本中匹配已注册的工具名
registered_names = registry.list_names()  # ["get_weather", "add", ...]
pattern = r'\b(' + '|'.join(re.escape(n) for n in registered_names) + r')\b'
```

### 不一致处理

不阻塞对话。仅记录 trace 事件：

```python
{
    "type": "reasoning_mismatch",
    "reasoning_mentions": ["get_weather"],
    "actual_calls": ["get_time"],
    "step": 2
}
```

## Testing Decisions

### 测试原则
- 用 mock response（带 reasoning_content）测试一致性检查逻辑
- 不依赖真实 DeepSeek reasoner 模型（成本高且不稳定）
- 重点测试边界：空 reasoning、中文工具名、reasoning 中提到非工具词

### 测试模块
- `ReasoningInspector.extract_tool_names()` 单元测试：英文名、中文名、混合文本、无匹配
- `ReasoningInspector.check_consistency()` 单元测试：一致/不一致/无 reasoning/多工具
- `ToolRuntime` 集成测试：mock client 返回含 reasoning 的 response，验证 trace 中有 reasoning_mismatch 事件
- `chat_stream()` 测试：验证 reasoning 事件类型正确产生

### 参考先例
- `tests/test_runtime.py` 的 mock client 模式
- `verify_reliability.py` B4 流式测试

## Out of Scope

- 对 reasoning content 的语义分析或 LLM 评分
- 基于 reasoning 不一致的自动重试或工具纠正
- reasoning content 的持久化存储和检索
- 对非 DeepSeek 模型推理内容的适配
- 跨对话的 reasoning pattern 学习和统计

## Further Notes

- `extract_tool_names()` 用正则简单匹配，不做 NLP 语义理解。准确性不是 100%，但成本为零，且不影响对话流程。
- 流式 reasoning 输出是可选的——如果用户不传 `stream_reasoning=True`，reasoning 只在最终 result 中可见。
- DeepSeek 的 `deepseek-chat` 模型在某些情况下也可能返回 reasoning（beta 功能），需要兼容处理。
