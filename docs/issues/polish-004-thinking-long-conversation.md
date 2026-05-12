# polish-004: Thinking Mode 长对话稳定性测试

**状态**: 待开始
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

Thinking mode 的 `reasoning_content` 在多轮对话中必须正确传递——这是 DeepSeek API 的要求，也是 DTK 最大独有功能。当前只有单轮和 3 轮的基础测试。10+ 轮的稳定性和 reasoning 完整性没有被验证过。

## 任务

1. 构造 10 轮 thinking mode 对话：
   - `Agent(thinking=True).chat("分析 Q1")` → `.chat("分析 Q2")` → ... → `.chat("分析 Q10")`
   - 每轮要求 Agent 引用前一轮的结果
   - 每轮后检查消息历史中 reasoning_content 的存在

2. 验证每轮：
   - `AgentResult.reasoning_content` 非空
   - `AgentResult.diagnostics.context_used` 逐步增长（reasoning 在积累）
   - 无 400 错误（reasoning_content 正确传递）
   - 第 10 轮仍能引用第 1 轮的信息

3. 压力变化：
   - 测试A：纯文本对话（无工具调用）
   - 测试B：每轮调用 1-2 个工具
   - 测试C：工具调用失败后重试（验证 reasoning 在重试中不丢失）

## 验收标准

- [ ] 三个测试各跑 10 次
- [ ] 10 轮对话零 400 错误
- [ ] 每轮 reasoning_content 非空
- [ ] 第 10 轮仍能正确引用历史上下文

## 测试建议

- 使用真实 DeepSeek API（核心差异化功能，必须真枪实弹）
- 每轮打印 reasoning_content 的前 100 字符
- 对比 LangChain 同场景（会 400 错误——作为反面证据）
- 结果写入 `output/polish/thinking/` 目录

## 分类: ready-for-agent
