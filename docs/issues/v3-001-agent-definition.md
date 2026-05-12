# v3-001: Agent 定义 — role/goal/backstory + `.run()` 基础运行

**状态**: 待开始
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

---

## 背景

当前 DTK v2 的 `run_agent()` 函数需要手动管理 Session、ToolRuntime、System Prompt、Task 等组件。开发者需要理解 ~10 个概念才能跑起来一个 Agent。CrewAI 的 `Agent(role=..., goal=..., backstory=...)` 3 个参数定义 Agent 的体验已被市场验证——5 行代码出结果。

本 Issue 实现 DTK v3 的 `DeepSeekAgent` 类，将复杂的运行时配置收敛到 3 个自然语言参数。

## 任务

1. 创建 `deepseek_toolkit/agent/agent.py`，实现 `DeepSeekAgent` 类
2. 支持 `role`、`goal`、`backstory` 三个核心参数（均为必填 str）
3. 实现 `.run(task: str, files: list[str] | None = None) -> AgentResult` 方法
4. `.run()` 内部自动完成：构建 system prompt → 创建 Session → 配置 ToolRuntime → 流式执行 → 返回结构化结果
5. `AgentResult` 包含：`final_output: str`、`tool_calls: list`、`tokens: dict`、`cost: float`、`reasoning_content: str | None`
6. 可选参数：`thinking: bool = True`（默认开启）、`model: str = "deepseek-v4-pro"`、`api_key: str | None = None`（默认读环境变量）、`temperature: float = 0.2`、`max_steps: int = 25`

## 验收标准

- [ ] 3 行代码定义 Agent 并成功执行简单任务
- [ ] `agent.run("读取 data/sales_data.csv，计算总销售额")` 返回非空 final_output
- [ ] `AgentResult` 包含所有 5 个字段且值有效
- [ ] `thinking=True`（默认）时，AgentResult.reasoning_content 非空
- [ ] 不传入 api_key 时自动从 `DEEPSEEK_API_KEY` 环境变量读取

## 测试建议

- E2E 测试：定义 Agent → 执行简单计算任务 → 验证 AgentResult 结构
- 参照：`tests/test_thinking.py` 的端到端测试模式
- Mock 场景：api_key 缺失时抛出清晰错误

## 分类

**ready-for-agent** — 接口清晰，无外部依赖，现有 runtime 层可直接复用，可直接开始实现。
