# v3-013: Crew Checkpoint/Resume 集成

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)
**阻塞**: v3-006, v3-012

---

## 背景

v3-012 实现了一个通用的 CheckpointStore。本 Issue 将其集成到 Crew 执行流程中，使任何 Crew（无论 Sequential/Parallel/Hierarchical）都能在中断后从保存点恢复。

核心价值：
- Sequential Crew 在第 3 步失败 → resume 从第 3 步继续，不重跑前 2 步
- Agent 执行一半（已调用 5 个工具）时网络中断 → resume 恢复完整对话历史，LLM 从断点继续

## 任务

1. Crew 集成：
   - `Crew(checkpoint=True)` 启用 checkpoint
   - 每个 Task 开始前：自动保存 checkpoint（当前 task_index、完整消息历史）
   - 每个 Task 完成后：更新 checkpoint（标记 task 已完成）
2. 实现 `Crew.resume(thread_id: str | None = None) -> CrewResult`：
   - 加载最近 checkpoint
   - 恢复 Agent 的 Session 消息历史
   - 从 task_index + 1 继续执行
   - 已完成 Task 的 TaskResult 保留（不重跑）
3. `Agent.run()` 集成：
   - 每个 tool call 完成后：自动保存 checkpoint（快照消息历史 + 工具调用列表）
   - resume 时：恢复消息历史 → 模型从上次断点继续
4. `CrewResult` 增加 `resumed_from: int | None` 字段（指示从哪个 task 恢复）

## 验收标准

- [ ] Sequential Crew(3 tasks, checkpoint=True) → 第 2 个 task 失败 → resume → 从第 2 个 task 继续
- [ ] resume 后不重跑已完成的 task（验证每个 Agent 只被调用应有的次数）
- [ ] checkpoint=False（默认）时无性能开销
- [ ] 恢复的 Agent 对话历史完整（含 reasoning_content、tool_calls）
- [ ] 同一 thread_id 不能同时被两个 Crew 使用（检测冲突并报错）

## 测试建议

- E2E 测试：模拟 Task 异常 → 保存 checkpoint → resume → 验证完整性
- E2E 测试：Parallel Crew checkpoint → resume → 验证未完成的任务仅执行一次
- 单元测试：CrewResult.resumed_from 正确赋值
- 边界测试：resume 不存在的 thread_id、checkpoint 文件损坏

## 分类

**ready-for-agent** — 依赖 v3-006（Crew）和 v3-012（CheckpointStore）。核心逻辑是 "执行前保存状态，恢复时加载状态"，复杂度可控。
