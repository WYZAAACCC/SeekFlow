# P0-1: CostTracker 修复 — 让 cost 不再显示 CNY 0

**状态**: `ready-for-agent`
**优先级**: P0
**类型**: AFK

## Parent

[PRD: 竞品差距收敛](../PRD-benchmark-gap-closure.md)

## What to build

修复 CostTracker 的计费逻辑。当前在所有 agent 运行中 cost 始终为 CNY 0.000000，而 LangChain 在相同场景下正确输出 CNY 0.013~0.104。

排查并修复以下可能的问题点：
- API 响应中 token usage 的提取路径是否与 DeepSeek 实际返回结构一致（可能与 OpenAI 格式有差异）
- 模型名称与 pricing table 的匹配逻辑（确保 `deepseek-v4-pro` 能匹配到 input: 1.74 / output: 3.48 CNY per 1M tokens）
- 累计值的累加逻辑（单次 record 和 total_cost 的数值累加是否正确）
- cached_tokens 的计费是否正确（cached input: 0.028 CNY per 1M tokens，应从 prompt_tokens 中扣除）

计费公式：
```
fresh_prompt = prompt_tokens - cached_tokens
cost = (fresh_prompt * 1.74 + cached_tokens * 0.028 + completion_tokens * 3.48) / 1_000_000
```

不改动 `CostTracker.record(model, usage)` 的公开签名。

## Acceptance criteria

- [ ] 运行 single agent 后 `CostTracker.total_cost > 0`
- [ ] 连续运行 4 个 agent 后累计 cost 递增（不归零、不变为负数）
- [ ] `deepseek-v4-pro` 的 cost 与 LangChain 计算值在 ±5% 误差范围内
- [ ] cached_tokens > 0 时 prompt cost 正确拆分为 fresh + cached 两部分
- [ ] 不存在的模型名称调用 `record()` 时有合理的 fallback（默认定价或 warning）

## Test suggestions

- 单元测试：用 mock usage dict 调用 `record()`，验证返回值 > 0
- 集成测试：跑 DTK financial agent，检查 `report.cost > 0`
- 参考：`tests/test_thinking.py` 的测试风格

## Blocked by

None - can start immediately
