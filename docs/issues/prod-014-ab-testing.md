# prod-014: Prompt A/B 测试框架 — 对比不同 prompt 的效果

**状态**: 待开始
**优先级**: P2
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

生产环境中 prompt 优化是持续过程。换一个 system prompt 到底是变好还是变坏？当前 eval 框架只做 pass/fail 判断，不能做 A/B 对比。需要统计显著的对比测试。

## 任务

1. 创建 `ABRunner` 类
2. `ABRunner.compare(agent_a, agent_b, tasks)` 对同一批任务用两个 Agent 各跑一次
3. 对比维度：cost, latency, output_length, tool_calls, user_rating
4. 输出统计报告：均值、方差、p 值（Welch's t-test）
5. 支持 `min_runs_per_variant: int = 10` 确保统计显著性

## 验收标准

- [ ] 10 个任务跑 A/B 对比 → 输出统计报告含 p 值
- [ ] 报告显示哪个 variant 更好（cost/latency/quality）
- [ ] p < 0.05 时标注 "统计显著"

## 测试建议

- Mock Agent 返回预设结果 → 验证统计计算正确
- 验证 min_runs 不足时发出 warning

## 分类: ready-for-agent
