# v3-029: ContextCompressor

**状态**: 已完成
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景
PRD 承诺上下文接近 1M 上限时自动触发压缩。LangChain 有 SummarizationMiddleware，DTK 需基础版本。

## 任务
1. 实现 ContextCompressor 类
2. should_compress() 检测 + compress() 压缩：保留 system message + 最近 N 条，中间摘要

## 验收标准
- [x] 超限消息触发压缩
- [x] 压缩后保留 system + 最近消息
- [x] 中间消息被摘要替代

## 分类: ready-for-agent
