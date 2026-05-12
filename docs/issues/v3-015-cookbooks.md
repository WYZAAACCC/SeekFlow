# v3-015: 5 个 Cookbook 示例

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)
**阻塞**: Phase 1-4 全部完成

---

## 背景

新框架最大的障碍不是技术，是"不知道怎么用"。Cookbook 是降低上手门槛的最有效手段——一个可复制粘贴、立即跑通的示例，比 10 页 API 文档更有说服力。

每个 Cookbook 必须是**端到端**的：从数据获取到最终报告，展示 DTK v3 在真实场景中的最佳实践。

## 任务

创建 5 个 Cookbook（Jupyter Notebook 或 Markdown + 可运行 Python 脚本）：

### Cookbook 1: 数据分析 Agent
- 场景：读取 sales_data.csv → 多维度分析 → 生成图表 → 输出专业报告
- 展示：单 Agent、文件输入、thinking mode、工具链
- 对标：当前 benchmark 中的 data_analysis agent

### Cookbook 2: 投资分析 Agent
- 场景：获取股票数据 → 技术指标计算 → 宏观分析 → 投资建议
- 展示：fetch_stock_data 工具、run_python_experiment、多数据源整合
- 对标：当前 benchmark 中的 investment agent

### Cookbook 3: 代码审查 Agent
- 场景：读取完整代码仓库 → 逐文件分析 → 发现潜在 bug → 生成审查报告
- 展示：1M 上下文（全量代码导入）、thinking mode（复杂推理）
- 差异化：LangChain/CrewAI 无法在 thinking 模式下稳定运行此场景

### Cookbook 4: 文档问答 Agent
- 场景：加载 PDF 论文/报告 → 回答用户提问 → 引用原文
- 展示：Document 桥接（LangChain loader → DTK Agent）、1M 上下文全量导入
- 对比：传统 RAG（chunk+retrieve）vs DTK（全量 dump）的效果和成本差异

### Cookbook 5: 多 Agent 协作
- 场景：研究员搜索→分析师分析→撰稿人润色→输出正式报告
- 展示：Sequential Crew、Parallel Crew、上下文传递、checkpoint/resume

## 验收标准

- [ ] 每个 Cookbook 包含：场景描述、前置依赖、完整代码、预期输出、常见问题
- [ ] 用户复制粘贴代码后无需修改即可在自己的环境中运行
- [ ] 每个 Cookbook 运行时间 < 10 分钟
- [ ] Cookbook 3 展示 thinking mode 多轮对话稳定性（LangChain 做不到）

## 测试建议

- 在 CI 中定期运行所有 Cookbook（每日一次），确保代码和依赖不过期
- Cookbook 输出应与预期输出基本一致（允许 LLM 输出的自然差异）

## 分类

**needs-info** — 需要等 Phase 1-4 的 API 稳定后才能编写。但 Cookbook 的场景设计可以提前开始——先确定每个场景的数据、步骤和预期效果。
