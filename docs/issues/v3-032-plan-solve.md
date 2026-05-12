# v3-032: Plan & Solve 模式 — Agent 先规划再执行

**状态**: 已完成
**优先级**: P2
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景
Plan & Solve 是 2025 年验证的 SOTA Agent 模式：复杂任务先制定计划，再按计划逐步执行。优于直接 ReAct 处理多步依赖任务。

## 任务
1. Agent.plan_solve(task): 第一阶段生成3-5步计划，第二阶段按计划执行
2. 复用 Agent.run() 进行两阶段调用

## 验收标准
- [x] plan_solve() 先输出计划再执行
- [x] 最终输出基于计划步骤

## 分类: ready-for-agent
