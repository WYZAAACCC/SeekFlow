# v3-017: Agent.stream() — 暴露 chat_stream()，含 reasoning 事件

**状态**: 已完成
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)
**阻塞**: 无

## 背景
runtime.py 有完整的 chat_stream() 实现，但 Agent 只暴露了 run() (sync)。SOTA 趋势要求 streaming as default，且 reasoning_content 必须在流式输出中实时可见。

## 任务
1. Agent.stream() 方法封装 rt.chat_stream()
2. 流式输出中 reasoning 事件正常产出
3. done 事件携带 usage 信息

## 验收标准
- [x] stream() yields content + done events
- [x] thinking=True 时 yields reasoning events
- [x] 工具调用时 yields tool_call_start/tool_call_result
- [x] done event 包含 usage 数据

## 分类: ready-for-agent
