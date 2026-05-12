# P0-2: ThinkModeGuard — reasoning_content 多轮自动传递

**状态**: `ready-for-agent`
**优先级**: P0
**类型**: AFK

## Parent

[PRD: 竞品差距收敛](../PRD-benchmark-gap-closure.md)

## What to build

新增 `ThinkModeGuard` 内部组件，在 `chat()` 和 `chat_stream()` 调用前自动处理 reasoning_content 的保存和回传。

当 thinking mode 启用时，DeepSeek API 要求后续请求中必须包含前一轮 assistant 消息的 `reasoning_content` 字段。当前 ToolRuntime 未正确保留和回传该字段，导致多轮工具调用场景下 400 报错：
```
DeepSeekAPIError: Error code: 400 - The `reasoning_content` in the thinking mode must be passed back to the API.
```

ThinkModeGuard 的三个职责：

1. **检测**：扫描消息列表，判断是否存在 reasoning_content 不兼容的情况
2. **修复**：确保所有 assistant 消息的 reasoning_content 字段完整（非 None、非空字符串时保留）
3. **降级判断**：当检测到无法修复的不兼容情况时，返回建议的降级策略

核心逻辑：
- `chat()` 和 `chat_stream()` 调用前，扫描 `messages` 列表
- 对于每一条 role="assistant" 的消息，如果原始响应包含 `reasoning_content`，确保它存在于消息 dict 中
- Session 保存消息时必须保留 `reasoning_content` 字段（当前可能被丢弃）
- 如果用户显式传入了缺少 reasoning_content 的外部 assistant 消息，发出 warning 但不阻止请求

## Acceptance criteria

- [ ] `thinking_mode="enabled"` + 多轮工具调用 agent 运行成功，无 400 错误
- [ ] `thinking_mode="disabled"` 场景行为不变（回归测试）
- [ ] Session 保存的消息包含 reasoning_content 字段（如果模型返回了的话）
- [ ] 从 Session 加载后继续对话，reasoning_content 不丢失
- [ ] 外部传入的 assistant 消息缺少 reasoning_content 时，发出 `UserWarning` 但不崩溃

## Test suggestions

- 单元测试：构造包含/不包含 reasoning_content 的 messages，验证 `_apply_thinking_mode` 行为
- 集成测试：`thinking_mode="enabled"` 跑 financial agent（至少 2 轮工具调用），验证无 400 错误
- 参考：`tests/test_thinking.py` 扩展多轮场景

## Blocked by

None - can start immediately
