# prod-004: 重试成本追踪 — 记录失败重试消耗的 token 与费用

**状态**: 待开始
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

RetryExecutor 重试时，每次失败尝试都消耗了输入 token（¥1.74/M），但成本未单独记录。100K prompt 重试 3 次 = 浪费 ¥0.52，用户无感知。生产环境必须知道重试烧了多少钱。

## 任务

1. RetryExecutor 每次重试记录：attempt_number, prompt_tokens, cost_estimate
2. AgentResult 增加 `retry_attempts: int` 和 `retry_cost: float` 字段
3. ToolRuntimeResult 增加 `retry_events: list[dict]` 记录每次重试的元数据
4. AgentResult.summary() 中显示重试次数和成本

## 验收标准

- [ ] 发生重试时 AgentResult.retry_attempts > 0
- [ ] AgentResult.retry_cost > 0 且为估算的重试消耗
- [ ] 无重试时 retry_attempts=0, retry_cost=0.0

## 测试建议

- Mock 前 2 次 API 调用失败、第 3 次成功 → 验证 retry_attempts=2
- 验证 retry_cost 基于 prompt_tokens 正确计算

## 分类: ready-for-agent
