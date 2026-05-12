# prod-011: DeepSeek 特定错误恢复 — 空content/幻觉工具名检测与纠正

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

DeepSeek 有时会返回空 content（content=None 或 ""），或在 tool_calls 中引用不存在的工具名（幻觉）。当前框架将空 content 视为正常完成，将幻觉工具名视为普通工具错误——不重试、不纠正。生产环境需要检测并自动恢复。

## 任务

1. chat() 中检测空 content + 无 tool_calls → 自动重试（最多 1 次）
2. ToolExecutor.execute() 检测 "Tool 'xxx' not found" 错误 → 自动重试（让模型重新选择工具）
3. 连续 3 次空 content 或幻觉工具名 → 返回明确错误，不无限重试
4. AgentResult 增加 `empty_content_retries: int` 和 `hallucinated_tool_retries: int` 字段

## 验收标准

- [ ] 空 content 自动重试 1 次后恢复或报错
- [ ] 幻觉工具名自动重试 1 次后恢复或报错
- [ ] 连续失败 3 次停止重试并返回明确错误
- [ ] 重试统计在 AgentResult 中可见

## 测试建议

- Mock API 返回空 content → 验证自动重试
- Mock API 返回不存在的工具名 → 验证自动重试

## 分类: ready-for-agent
