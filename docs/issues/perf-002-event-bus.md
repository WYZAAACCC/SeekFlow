# perf-002: 事件总线 — EventBus + subscribe/unsubscribe + 生命周期事件

**状态**: 待开始
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

当前 TraceRecorder 是内存内 JSON 日志，无发布/订阅机制。CrewAI 有完整的 EventBus（CrewAIEventBus）支持 ~100 个事件类型。LangChain 有 callback 系统（BaseCallbackHandler，20 个钩子）。DTK 需要一个轻量但完整的事件总线来支撑：可观测性、UI 实时更新、插件系统。

## 任务

1. 创建 `EventBus` 类（单例或实例化）
2. 核心方法：`subscribe(event_type, handler)`、`unsubscribe(handler)`、`emit(event)`
3. 事件类型（10个核心事件）：
   - `agent.start` / `agent.end` / `agent.error`
   - `llm.request` / `llm.response` / `llm.stream_token`
   - `tool.start` / `tool.end` / `tool.error`
   - `step.complete`
4. Agent.run()、ToolRuntime.chat() 中发射事件
5. 支持同步和异步 handler
6. 默认 handler：控制台输出（verbose 模式）

## 验收标准

- [ ] `event_bus.subscribe("tool.start", my_handler)` 注册成功
- [ ] Agent.run() 执行时触发 agent.start/end 事件
- [ ] 工具调用时触发 tool.start/end 事件
- [ ] unsubscribe 后不再收到事件
- [ ] 异步 handler 不阻塞 Agent 执行

## 测试建议

- 单元测试：subscribe/emit/unsubscribe 完整流程
- 集成测试：Agent.run() → 验证事件序列
- 边界测试：handler 抛异常不影响其他 handler

## 分类: ready-for-agent
