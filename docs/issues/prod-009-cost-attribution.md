# prod-009: 成本归属 — 按租户/任务标签追踪费用

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

生产环境需要知道哪个客户/任务花了多少钱。当前只有 AgentResult.cost，无法区分不同客户。CostTracker 按模型累计但无标签。

## 任务

1. Agent.__init__ 增加 `cost_tag: str | None = None` 参数
2. AgentResult 增加 `cost_tag` 和 `model` 字段
3. AgentResult 增加 `to_cost_log() -> dict` 方法，返回包含时间戳、模型、标签、token、成本的单行记录
4. 提供 `CostLedger` 类：收集多个 AgentResult 的 cost_log，支持按 tag/model/时间范围聚合查询
5. CostLedger 支持导出 CSV

## 验收标准

- [ ] agent.run(task, cost_tag="customer-123") → AgentResult.cost_tag = "customer-123"
- [ ] CostLedger 正确聚合多个 tag 的成本
- [ ] CSV 导出包含所有字段

## 测试建议

- 单元测试：CostLedger 聚合查询
- 单元测试：CSV 导出格式

## 分类: ready-for-agent
