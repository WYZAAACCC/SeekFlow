# v3-014: Hierarchical Process — Manager→Worker 任务分发

**状态**: 待开始
**优先级**: P2
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)
**阻塞**: v3-006, v3-012

---

## 背景

CrewAI 的 Hierarchical Process 是它的核心差异化功能之一：一个 Manager Agent 接收复杂任务，自动分解为子任务，分配给 Worker Agents 执行，然后汇总结果。

实现上，CrewAI 的 Hierarchical 依赖 LiteLLM 做 provider routing（Manager 和 Worker 可以用不同供应商的模型）和复杂的内部工具调用链。

DTK v3 的目标：仅支持 DeepSeek（Manager 和 Worker 都使用 DeepSeek），从而大幅简化实现——不需要跨供应商的工具抽象。

## 任务

1. 在 `orchestration.py` 中实现 Hierarchical 编排逻辑
2. `Crew(process="hierarchical", manager_agent=manager_agent)` 启用层级模式
   - `manager_agent` 必须是一个已配置的 DeepSeekAgent
   - Manager 自动获得 `delegate_task(worker_name, task_description)` 工具
3. Manager 执行流程：
   - 接收到 Crew.kickoff() 的总任务
   - 调用 `delegate_task` 将子任务分配给 Worker
   - Worker 执行子任务并返回结果
   - Manager 汇总所有 Worker 结果，生成最终输出
4. Worker 执行方式：Manager 通过 `delegate_task` 指定 Worker 名称和子任务描述 → 编排引擎查找对应 Agent → 调用 Agent.run()
5. 支持 manager_agent 使用 thinking mode（更复杂的分解和汇总推理）

## 验收标准

- [ ] Manager 将 "分析公司财务状况并给出投资建议" 分解为 ≥2 个子任务
- [ ] 每个子任务分配给正确的 Worker Agent
- [ ] Manager 汇总所有 Worker 结果，生成连贯的最终输出
- [ ] 一个 Worker 失败时，Manager 决定是否重试或跳过
- [ ] CrewResult 包含 Manager 和所有 Worker 的执行详情

## 测试建议

- E2E 测试：Manager(financial_lead) + Worker(research) + Worker(analyst) → 复杂分析任务 → 验证输出质量
- E2E 测试：Worker 工具调用失败 → Manager 决定重试 → 最终成功
- 边界测试：Manager 不调用 delegate_task（直接自己回答）、Manager 无限循环委托

## 分类

**needs-investigation** — 层级编排的 Manager 推理质量高度依赖 prompt 设计和 tool schema。需要先小规模实验验证 Manager 能否可靠地分解和分配任务，再确定接口。
