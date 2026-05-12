# v3-008: Crew 生命周期 — 上下文传递、错误聚合、结果汇总

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)
**阻塞**: v3-006

---

## 背景

v3-006 和 v3-007 实现了 Sequential 和 Parallel 的基本调度。但生产级 Crew 还需要完整的生命周期管理：

1. **上下文传递**：Sequential 模式中前一个 Agent 的输出如何格式化后传给下一个 Agent
2. **错误聚合**：多个 Agent 可能产生不同类型的错误，如何统一收集和报告
3. **结果汇总**：最终输出应包含哪些信息（每个 Agent 的摘要、总览、关键数据）
4. **进度回调**：长任务需要实时反馈执行进度

CrewAI 的 event 系统用了 ~100 个事件类来处理这些——大部分是冗余。DTK 需要一个更精简的方案。

## 任务

1. 实现 `CrewContext`：贯穿 Crew 执行过程的共享上下文对象
   - `shared_data: dict` — Agent 间共享的键值存储
   - `history: list[TaskResult]` — 已完成 Task 的结果历史
   - `get(key, default)` / `set(key, value)` — 共享数据访问
2. 上下文传递协议：
   - Sequential：每个 Task 结束后，TaskResult 自动写入 `CrewContext.history`
   - 下一个 Task 的 description 自动追加 "前置任务结果: {上一个 Task 的输出摘要}"
3. 错误聚合：
   - 每个 Task 的异常被捕获并包装为 `TaskError`（包含 task_index、agent_name、error_message）
   - `CrewResult.errors: list[TaskError]` 包含所有失败
4. 进度回调：
   - `Crew(kickoff_callback: Callable[[CrewProgress], None] | None = None)`
   - `CrewProgress` 包含：current_task_index、total_tasks、current_agent_name、status（"running"/"completed"/"failed"）
5. 结果汇总：
   - `CrewResult.summary: str` — 自动生成的多 Agent 执行摘要（每个 Agent 的名称 + 任务 + 状态 + 输出长度）

## 验收标准

- [ ] Sequential Crew 中 t1 的输出作为 t2 的上下文传入
- [ ] 一个 Task 失败时，后续 Task 仍可访问 CrewContext 中的共享数据
- [ ] CrewResult.errors 包含完整的 TaskError 信息（task_index、agent_name、error_message）
- [ ] kickoff_callback 在每个 Task 开始/完成时被调用
- [ ] CrewResult.summary 包含所有 Task 的执行摘要

## 测试建议

- E2E 测试：3 Agent Sequential Crew → 验证上下文正确传递
- E2E 测试：Parallel Crew + kickoff_callback → 验证回调被调用 3 次
- 单元测试：CrewContext 读写隔离
- 边界测试：空 callback、callback 抛出异常不影响 Crew 执行

## 分类

**ready-for-agent** — 纯逻辑层，不涉及新 API。但需确认 callback 签名和 CrewContext 接口设计符合预期后再开始实现。
