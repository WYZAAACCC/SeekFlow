# v3-018: Agent 结构化输出 — response_format + Pydantic

**状态**: 已完成
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景
runtime.py 支持 response_format 参数，但 Agent 未暴露。LangChain 的 with_structured_output() 默认 json_schema 对 DeepSeek 崩溃（DTK 默认 None 避免此问题）。

## 任务
1. Agent.__init__ 接受 response_format 参数
2. run()/stream() 自动传递给 runtime

## 验收标准
- [x] response_format="json_object" 正常工作
- [x] 默认 None（不约束输出格式）

## 分类: ready-for-agent
