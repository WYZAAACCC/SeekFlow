# v3-002: Task 定义 — description + expected_output + Agent 绑定

**状态**: 待开始
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)
**阻塞**: v3-001

---

## 背景

单 Agent 场景中，Task 与 Agent 是一对一关系。但当进入多 Agent 编排时，需要独立的 Task 概念：一个 Task 绑定一个 Agent，有自己的 description 和 expected_output，多个 Task 组成 Crew。

CrewAI 的 Task 设计已被验证：`description` 告诉 Agent 做什么，`expected_output` 告诉 Agent 产出什么格式。

## 任务

1. 创建 `deepseek_toolkit/agent/task.py`，实现 `Task` 类（Pydantic BaseModel）
2. 字段：
   - `description: str` — 任务描述（必填）
   - `expected_output: str` — 期望输出格式描述（必填）
   - `agent: DeepSeekAgent | None = None` — 绑定的 Agent（可选，在 Crew 中自动填充）
   - `context: list[Task] | None = None` — 前置任务列表（用于 Sequential 模式传递上下文）
   - `output_pydantic: type[BaseModel] | None = None` — 结构化输出模型（可选）
3. `Task.run(context: str = "") -> TaskResult` 方法：调用绑定的 Agent 执行此 Task
4. `TaskResult` 包含：`output: str`、`agent_result: AgentResult`、`context_for_next: str`

## 验收标准

- [ ] Task 实例化后，调用 `.run()` 成功执行
- [ ] `context` 参数正确传递——前置 Task 的输出作为后置 Task 的 context_for_next
- [ ] `output_pydantic` 为 None 时正常返回字符串
- [ ] Task 未绑定 Agent 时 `.run()` 抛出清晰错误

## 测试建议

- 单元测试：Task 定义 → 验证 schema → 绑定 Agent → 验证
- E2E 测试：Task(description="读取数据", agent=agent) → Task.run() → 验证 TaskResult
- 边界测试：空 description、空 expected_output 应抛出 ValidationError

## 分类

**ready-for-agent** — 纯数据模型 + 简单委托逻辑，无外部依赖。阻塞于 v3-001。
