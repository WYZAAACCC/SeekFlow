# prod-008: 上下文窗口明细 — 展示 token 使用分类与浪费分析

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

AgentResult 给出 context_used/context_total，但只有一个总数。生产环境需要知道：系统提示占多少、文档占多少、对话历史占多少、工具结果占多少。这些信息能帮用户优化上下文利用率——比如发现 40% token 浪费在冗长的工具结果上。

## 任务

1. AgentResult 增加 `context_breakdown: dict` 字段：
   - system_prompt_tokens
   - document_tokens
   - conversation_tokens
   - tool_result_tokens
   - reasoning_tokens
2. run() 执行后从 messages 中分类统计各类 token 消耗
3. 任一类别超过总数的 30% 时在 AgentResult 中标注 warning
4. context_used 接近 context_total 90% 时发出压缩建议

## 验收标准

- [ ] AgentResult.context_breakdown 包含 5 个分类
- [ ] 各类 token 之和 ≈ context_used
- [ ] 工具结果超过 30% 时标注 warning

## 测试建议

- Agent + 大文件 + 多轮工具调用 → 验证 breakdown 合理性
- 验证 warning 在工具结果过多时触发

## 分类: ready-for-agent
