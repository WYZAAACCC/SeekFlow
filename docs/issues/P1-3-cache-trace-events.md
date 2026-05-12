# P1-3: Trace cache_hit 事件 + ToolRuntime 缓存配置

**状态**: `ready-for-agent`
**优先级**: P1
**类型**: AFK

## Parent

[P1: 工具调用去重缓存](../prd/P1-tool-call-dedup-cache.md)

## What to build

完善缓存功能的可观测性和配置面。

具体工作：
- TraceRecorder 新增 `cache_hit` 事件类型，记录缓存命中的 tool_name、cache_key、节省的 elapsed_ms
- TraceRecorder 新增 `cache_stats` 摘要事件（在 `chat()` 结束时自动记录），包含 hits/misses/ratio
- `ToolRuntime` 暴露 `cache_stats` 属性，返回 `{"hits": N, "misses": M, "ratio": N/(N+M)}`
- `ToolRuntimeResult` 新增 `cache_stats` 字段
- 在 `verify_reliability.py` 中增加一个缓存验证场景（B12），验证多轮对话中缓存确实命中

## Acceptance criteria

- [ ] Trace JSON 中包含 `cache_hit` 事件，字段完整（tool_name, cache_key, saved_ms）
- [ ] 对话结束时 Trace 自动记录 `cache_stats` 摘要
- [ ] `result.cache_stats` 返回命中统计
- [ ] `runtime.cache_stats` 可在对话结束后查询
- [ ] B12 验证测试通过：多轮对话中第二次相同查询触发缓存命中

## Blocked by

- [P1-2: ToolExecutor 缓存集成 + @tool(cache=) 参数](./P1-2-executor-cache-integration.md)
