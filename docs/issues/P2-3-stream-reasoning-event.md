# P2-3: StreamEvent(type="reasoning") 流式 Reasoning 输出

**状态**: `ready-for-agent`
**优先级**: P2
**类型**: AFK

## Parent

[P2: Reasoning Content 利用](../prd/P2-reasoning-content-utilization.md)

## What to build

在 `chat_stream()` 中新增 `reasoning` 事件类型，将模型的 reasoning content 作为独立的事件流输出，让 UI 层可以折叠/展开"模型思考过程"。

具体工作：
- `StreamEvent` 类型新增 `"reasoning"` 事件类型
- `chat_stream()` 中，当收到 chunk 的 `reasoning_content` 时，yield `StreamEvent(type="reasoning", content=reasoning_text)`
- reasoning 事件在 tool_call 事件之前产生（符合实际 API 顺序）
- reasoning 内容也在最后的 `done` 事件的 `reasoning_content` 字段中保留完整文本
- 兼容性：使用非 reasoner 模型时，不产生 reasoning 事件（静默）

## Acceptance criteria

- [ ] `chat_stream()` 中 reasoning 事件类型按正确顺序 yield（reasoning → content → tool_call_start → tool_call_result → content → done）
- [ ] `done` 事件包含完整 reasoning 文本
- [ ] 无 reasoning 时事件流中不出现 reasoning 事件
- [ ] 验证脚本 B4 流式测试兼容新事件类型

## Blocked by

- [P2-2: chat() + chat_stream() 集成 Reasoning + Trace 事件](./P2-2-chat-reasoning-integration.md)
