# P2-2: chat() + chat_stream() 集成 Reasoning + Trace 事件

**状态**: `ready-for-agent`
**优先级**: P2
**类型**: AFK

## Parent

[P2: Reasoning Content 利用](../prd/P2-reasoning-content-utilization.md)

## What to build

将 `ReasoningInspector` 集成到 `ToolRuntime.chat()` 和 `chat_stream()` 流程中，在不阻塞对话的前提下记录 reasoning 信息。

具体工作：
- `chat()` 中：收到 response 后，若 `response.reasoning_content` 非空 → 调用 `ReasoningInspector.check_consistency()` → 不一致时记录 `reasoning_mismatch` trace 事件
- `chat_stream()` 中：若模型在流式输出中产生 reasoning（通过 chunk 的 `reasoning_content` 字段）→ 收集累积 → 工具调用结束后执行一致性检查
- TraceRecorder 新增 `reasoning_mismatch` 事件类型：包含 `reasoning_mentions`、`actual_calls`、`step`、`reasoning_snippet`（前 200 字符）
- `ToolRuntimeResult` 新增 `reasoning_contents: list[str]` 字段，收集本对话中所有 reasoning 文本
- 不一致**不中断对话**——仅记录 warning 级别 trace 事件

## Acceptance criteria

- [ ] 当 reasoning 提到 "get_weather" 但实际调了 "get_time"，trace 中有 `reasoning_mismatch` 事件
- [ ] 无 reasoning 时 trace 中无 `reasoning_mismatch` 事件
- [ ] `result.reasoning_contents` 包含本对话中收集的所有 reasoning
- [ ] 使用非 reasoner 模型时功能静默跳过，不报错
- [ ] 现有所有 B 组验证测试通过（reasoning 集成不影响正常流程）

## Blocked by

- [P2-1: ReasoningInspector 工具名提取 + 一致性校验](./P2-1-reasoning-inspector.md)

## Test suggestions

- Mock client 返回带 reasoning_content 的 response，验证 trace 事件
- Mock reasoning 与实际 tool_calls 不一致，验证 `reasoning_mismatch` 产生
- 参考 `tests/test_runtime.py` mock client 模式
