# Issue #5: Thinking Mode 一等参数

**优先级**: P1  
**状态**: 待开始  
**分类**: enhancement  
**Triage**: ready-for-agent  
**Phase**: 1 — DeepSeek 核心 API  
**依赖**: 无 — 可立即开始  
**覆盖用户故事**: #6 (一等参数), #11 (reasoning_content 自动透传)

---

## 背景

DeepSeek V4 的核心差异化能力是 Thinking Mode（深度思考）。当前库中开启方式是通过 `extra_body={"thinking": {"type": "enabled"}}`，这有三个问题：

1. **不直观**：用户需要了解 DeepSeek API 的 raw JSON 结构
2. **不类型安全**：`extra_body` 是 `dict[str, Any]`，拼写错误在运行时才发现
3. **reasoning_content 透传已实现但不易发现**：使用 `extra_body` 的用户不知道库已自动处理

Thinking Mode 的合法值：
- `"disabled"` — 不使用（默认）
- `"enabled"` — 标准思考
- `"max"` — 最大思考深度

## 任务

1. 在 `chat()` 和 `chat_stream()` 签名中新增 `thinking_mode` 参数：
   ```python
   thinking_mode: Literal["disabled", "enabled", "max"] | None = None
   ```
2. 内部自动转换为 `extra_body={"thinking": {"type": thinking_mode}}`
3. 当 `thinking_mode` 和 `extra_body` 同时包含 `thinking` key 时，`thinking_mode` 优先并输出警告
4. 更新所有示例和文档中的 `extra_body={"thinking": ...}` 为 `thinking_mode=...`
5. `reasoning_content` 自动透传逻辑保持不变

## 验收标准

- [ ] `thinking_mode="enabled"` 等价于 `extra_body={"thinking": {"type": "enabled"}}`
- [ ] `thinking_mode="max"` 等价于 `extra_body={"thinking": {"type": "max"}}`
- [ ] `thinking_mode=None`（默认）不发送 thinking 参数
- [ ] 同时传入 `thinking_mode` 和 `extra_body` 中的 thinking 时，前者优先 + 警告
- [ ] `reasoning_content` 在多轮对话中正确透传（回归测试）
- [ ] 现有 274 个测试不受影响
- [ ] 新增 ≥6 个测试

## 测试建议

- 测试三种 thinking_mode 值的参数正确性
- 测试与 extra_body 的合并逻辑
- 测试 reasoning_content 透传不被破坏
- 测试 thinking_mode 在 chat_stream 中的行为
- 参考现有 thinking 测试：[examples/07_real_api_test.py](../../examples/07_real_api_test.py)
