# v3-007: Parallel Process

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)
**阻塞**: v3-006

---

## 背景

Sequential 模式下，多个 Agent 依次执行，总延迟是所有 Agent 延迟之和。当 Agent 之间无依赖关系时（如同时分析财务数据、搜索行业信息、生成图表），并行执行可将总延迟降到最慢 Agent 的延迟。

CrewAI 不支持 Parallel Process（仅 Sequential 和 Hierarchical）。DTK v3 应原生支持。

LangChain 通过 `RunnableParallel` 实现并行，但需要开发者理解 Runnable 组合语法。DTK 的目标是 `process="parallel"` 一个参数搞定。

## 任务

1. 在 `orchestration.py` 中实现 Parallel 编排逻辑
2. 使用 `concurrent.futures.ThreadPoolExecutor` 并行执行所有 Task
3. 所有 Task 完成后，按原始顺序汇总 TaskResult 列表
4. 部分 Task 失败时：
   - 其他 Task 继续执行（不因一个失败而中止全部）
   - 失败的 Task 结果以 `TaskResult(error=...)` 形式记录
   - CrewResult.errors 包含所有失败 Task 的错误
5. `final_output` 为合并所有 Task 输出的摘要
6. 支持 `max_workers: int = 5` 参数控制最大并发数

## 验收标准

- [ ] `Crew(tasks=[t1, t2, t3], process="parallel").kickoff()` 三个 Task 同时执行
- [ ] 总延迟 ≈ max(t1, t2, t3) 延迟，而非 sum(t1, t2, t3)
- [ ] 其中一个 Task 失败时，其他 Task 正常完成
- [ ] CrewResult.outputs 保持原始 Task 顺序
- [ ] 最大并发数受 max_workers 限制

## 测试建议

- E2E 测试：3 个独立 Task → Parallel Crew → 验证总延迟 < 各 Task 延迟之和
- E2E 测试：一个 Task sleep(5) 后失败，另两个 sleep(1) 成功 → 验证结果完整
- 单元测试：max_workers 限制生效
- 边界测试：只有一个 Task 时 parallel 降级为直接执行

## 分类

**ready-for-agent** — ThreadPoolExecutor 是标准库，实现简单。阻塞于 v3-006 的 Crew/Task 接口定义。
