# P0-3: ThinkingMode 默认策略 — 多轮场景自动降级

**状态**: `ready-for-agent`
**优先级**: P0
**类型**: AFK

## Parent

[PRD: 竞品差距收敛](../PRD-benchmark-gap-closure.md)

## What to build

修改 `_apply_thinking_mode()` 的行为，使 `thinking_mode` 参数的默认值从"不传参（依赖模型默认）"变为"根据对话轮次智能选择"。

当前行为：`thinking_mode=None` 时不设置 `extra_body["thinking"]`，模型 `deepseek-v4-pro` 默认启用 thinking → 多轮场景直接 400 报错。

新行为：

| 场景 | 用户传参 | 实际行为 |
|------|---------|---------|
| 单轮（只有 system + user） | `None` | `"enabled"` |
| 多轮（含 assistant + tool） | `None` | `"disabled"` + `UserWarning("thinking_mode automatically set to 'disabled' for multi-turn conversation")` |
| 任意 | `"enabled"` | 尊重用户，启用 ThinkModeGuard |
| 任意 | `"disabled"` | 尊重用户 |
| 任意 | `"max"` | 尊重用户，启用 ThinkModeGuard |

单轮/多轮的判断依据：messages 列表中是否包含 role="tool" 的消息。包含即为多轮。

## Acceptance criteria

- [ ] 默认参数下单轮 agent（无工具调用）使用 `thinking_mode="enabled"`
- [ ] 默认参数下多轮 agent（有工具调用）自动降级为 `"disabled"` 并发出 UserWarning
- [ ] 用户显式传 `thinking_mode="enabled"` 时多轮场景不降级（尊重用户选择）
- [ ] 用户显式传 `thinking_mode="disabled"` 时行为不变
- [ ] 用户显式传 `thinking_mode="max"` 时行为不变
- [ ] UserWarning 消息包含降级原因说明

## Test suggestions

- 单元测试：构造单轮/多轮 messages，验证不同 thinking_mode 参数下的 `extra_body` 输出
- 单元测试：验证 UserWarning 在预期场景下发出
- 参考：`tests/test_thinking.py` 扩展默认策略用例

## Blocked by

- [P0-2: ThinkModeGuard](P0-2-think-mode-guard.md)
