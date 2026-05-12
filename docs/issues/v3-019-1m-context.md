# v3-019: 1M 上下文窗口 — max_context_tokens 默认 900K

**状态**: 已完成
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景
ToolRuntime 默认 max_context_tokens=64000，未适配 DeepSeek V4 的 1M 窗口。LangChain 无 DeepSeek profile（0%），CrewAI 仅 128K。

## 任务
1. Agent 默认 max_context_tokens=900000
2. 用户可自定义覆盖

## 验收标准
- [x] _make_runtime() 传递 max_context_tokens=900000
- [x] 自定义值正确传递

## 分类: ready-for-agent
