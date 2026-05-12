# v3-016: 迁移指南 + 基准对比报告

**状态**: 待开始
**优先级**: P2
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)
**阻塞**: Phase 1-4 全部完成

---

## 背景

有 LangChain 或 CrewAI 经验的开发者在评估 DTK 时，第一个问题是："我已有的代码怎么迁移过来？"迁移指南直接回答这个问题——给出并排的代码对比，展示 DTK 如何用更少的代码完成同样的事。

基准对比报告则是技术决策者的关键参考——量化 DTK 的优势（成本、延迟、质量、代码量）。

## 任务

### 迁移指南 1: LangChain → DTK

- 并排对比 5 个常见场景：
  1. 创建简单 Agent（LC: create_agent → DTK: DeepSeekAgent）
  2. 多工具调用（LC: @tool + AgentMiddleware → DTK: agent.add_tool()）
  3. 流式输出（LC: agent.stream() → DTK: agent.run() 默认流式）
  4. 结构化输出（LC: with_structured_output → DTK: output_pydantic）
  5. RAG 管道（LC: RetrievalQA chain → DTK: files=[] 直接导入）
- 每个场景给出：LangChain 代码 → DTK 等效代码 → 代码行数对比 → 注意事项

### 迁移指南 2: CrewAI → DTK

- 并排对比 4 个常见场景：
  1. 定义 Agent（CA: Agent(role, goal, backstory) → DTK: DeepSeekAgent(role, goal, backstory)）
  2. 顺序多 Agent（CA: Crew(process=sequential) → DTK: Crew(process="sequential")）
  3. 层级多 Agent（CA: Crew(process=hierarchical) → DTK: Crew(process="hierarchical")）
  4. 工具注册（CA: @CrewBase + @tool → DTK: agent.add_tool()）
- 每个场景对比代码行数、必需依赖、启动时间

### 基准对比报告

- 三框架性能对比（复用现有 benchmark 框架，使用 v3 Agent API 重新运行）
- 对比维度：延迟、成本、token 效率、缓存命中率、输出质量（人工评估）
- 差异化对比：thinking mode 可用性、1M 上下文利用率、错误信息质量
- 新增"代码量对比"：展示实现相同功能所需代码行数

## 验收标准

- [ ] 迁移指南中每个场景都有可运行的代码示例
- [ ] 基准对比涵盖所有 4 个 Agent 类型 × 3 个框架
- [ ] 基准报告包含 thinking mode on/off 的质量对比
- [ ] 迁移指南和基准报告保存到 `docs/guides/` 目录

## 测试建议

- 所有迁移指南中的代码示例必须在 CI 中可运行（集成测试）
- 基准对比使用固定的数据集和评估标准，确保可复现

## 分类

**needs-info** — 迁移指南依赖 v3 API 稳定（Phase 1-4 完成）。基准报告依赖 v3 API 稳定 + 三框架 benchmark 环境。可以提前设计对比维度和场景。
