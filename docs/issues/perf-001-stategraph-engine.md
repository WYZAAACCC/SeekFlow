# perf-001: StateGraph 执行引擎 — Channel-based state + 条件边 + interrupt/resume

**状态**: 待开始
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

当前 TaskGraph 是声明式 DAG，仅有依赖解析 + 并行执行，无状态传递。LangGraph 的 StateGraph 通过 channel-based state + reducer + 条件边实现了图工作流的核心能力——这是 LangChain 生态最不可替代的部分。DTK 不需要复制 LangGraph 的 29,000 行，但需要实现其中最关键的 20%：状态通道、条件边、中断/恢复。

## 任务

1. 创建 `StateGraph` 类：节点 = Agent/Task，边 = 数据流
2. 实现 Channel-based state：每个节点读/写命名的 state channel
3. Channel 支持 reducer：`last_value`（默认）、`append`、`merge`
4. 实现条件边：`add_conditional_edges(source, router, mapping)` — 根据 state 值选择下一节点
5. 实现 `interrupt(node_name)` — 节点内调用暂停执行，等待外部 `Command(resume=value)`
6. 每个节点执行后自动保存 checkpoint（复用 AgentCheckpoint）
7. StateGraph 兼容现有 Crew/Task（Task 可包装为 StateGraph 节点）

## 验收标准

- [ ] StateGraph 3 节点线性流程执行正确
- [ ] 条件边根据 state 值路由到不同节点
- [ ] interrupt() 暂停执行，Command(resume=...) 恢复
- [ ] checkpoint 保存/恢复节点级状态
- [ ] 现有 TaskGraph 测试不受影响

## 测试建议

- 单元测试：Channel reducer（last_value/append/merge）
- E2E：StateGraph 条件路由 → 验证正确节点被选中
- E2E：interrupt → resume → 验证状态恢复

## 分类: ready-for-agent
