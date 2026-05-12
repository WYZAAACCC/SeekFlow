# prod-010: 模型版本追踪 — 记录每次 API 调用的模型版本

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

DeepSeek 会静默更新模型版本。生产环境中如果模型行为突然变化，需要知道是哪个版本导致的。ChatResponse.raw 保留了完整的 API 响应，但模型版本（如 `x-ds-model-version` header）未被提取。

## 任务

1. DeepSeekClient.chat() 从响应头中提取模型版本信息
2. ChatResponse 增加 `model_version: str | None` 字段
3. AgentResult 增加 `model_version: str | None` 字段
4. 如果连续调用返回不同模型版本，发出 info 日志
5. CostLedger（prod-009）中记录 model_version

## 验收标准

- [ ] AgentResult.model_version 非空（如果 API 返回了版本头）
- [ ] 模型版本变化时日志可观测
- [ ] 版本信息出现在 CostLedger 导出中

## 测试建议

- Mock API 响应含版本头 → 验证提取正确
- Mock 两次调用返回不同版本 → 验证日志输出

## 分类: needs-investigation（需确认 DeepSeek API 是否真的返回模型版本头）
