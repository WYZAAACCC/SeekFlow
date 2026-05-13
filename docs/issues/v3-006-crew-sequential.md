# v3-006: Crew 定义 + Sequential Process

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)
**阻塞**: v3-001, v3-002

---

## 背景

单 Agent 能解决大部分问题，但复杂任务需要多 Agent 协作。CrewAI 的 Crew 模型（Agent + Task + Process）已被市场验证——开发者理解"把 Agent 分配 Task，按顺序执行"这个心智模型。

CrewAI 有 ~100 个事件类实现了 Sequential 编排。DTK v3 的目标是用不到 1/10 的代码量实现同样功能。

## 任务

1. 创建 `seekflow/agent/crew.py`，实现 `Crew` 类
2. 字段：
   - `tasks: list[Task]` — 任务列表（必填，至少 1 个）
   - `process: Process = Process.SEQUENTIAL` — 编排模式
   - `checkpoint: bool = False` — 是否启用 checkpoint（Phase 4 实现）
3. 实现 `Process` 枚举（`seekflow/agent/orchestration.py`）：
   - `SEQUENTIAL = "sequential"`
   - `PARALLEL = "parallel"`
   - `HIERARCHICAL = "hierarchical"`
4. `Crew.kickoff() -> CrewResult` 方法
5. Sequential 模式逻辑：
   - 按 `tasks` 列表顺序依次执行
   - 每个 Task 执行后，其 `TaskResult.context_for_next` 传入下一个 Task
   - 任何 Task 失败时，记录错误并停止后续执行（除非 checkpoint 开启）
6. `CrewResult` 包含：`outputs: list[TaskResult]`、`final_output: str`（最后一个 Task 的输出）、`errors: list[str]`、`total_cost: float`、`total_latency_ms: float`

## 验收标准

- [ ] `Crew(tasks=[t1, t2], process="sequential").kickoff()` 按序执行 t1→t2
- [ ] t1 的 context_for_next 正确传入 t2
- [ ] t1 失败时 t2 不执行，CrewResult.errors 包含 t1 的错误
- [ ] CrewResult.final_output 等于最后一个 Task 的输出
- [ ] CrewResult.total_cost 等于所有 Task 的 cost 之和

## 测试建议

- E2E 测试：2 个 Agent → 2 个 Task → Sequential Crew → 验证执行顺序和结果传递
- E2E 测试：第一个 Task 失败 → 验证第二个不执行 + 错误记录
- 边界测试：空 tasks 列表 → 抛出 ValidationError

## 分类

**ready-for-agent** — 核心逻辑简单（顺序循环 + 上下文传递），依赖 v3-001 和 v3-002 的 Agent/Task 接口稳定。
