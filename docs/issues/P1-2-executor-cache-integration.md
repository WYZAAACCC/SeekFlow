# P1-2: ToolExecutor 缓存集成 + @tool(cache=) 参数

**状态**: `ready-for-agent`
**优先级**: P1
**类型**: AFK

## Parent

[P1: 工具调用去重缓存](../prd/P1-tool-call-dedup-cache.md)

## What to build

将 `ToolCallCache` 集成到 `ToolExecutor.execute()` 流程中，让缓存对调用者透明。

具体工作：
- `ToolExecutor.__init__` 新增 `cache: ToolCallCache | None = None` 参数
- `execute()` 方法中：先查缓存 → 命中直接返回（记录 `cache_hit` trace）→ 未命中则执行工具 → 写入缓存 → 返回
- `ToolDefinition.metadata` 新增 `cache: bool = True` 字段
- `@tool` 装饰器新增 `cache: bool = True` 参数，写入 `metadata["cache"]`
- 当 `metadata["cache"] == False` 时，跳过缓存查询和写入
- `ToolRuntime.__init__` 新增 `cache_size: int = 128` 和 `cache_ttl: float | None = None` 参数，自动创建 `ToolCallCache` 并传给 `ToolExecutor`

## Acceptance criteria

- [ ] 同一 `ToolRuntime.chat()` 内相同工具+参数第二次调用直接返回缓存，不执行工具函数
- [ ] `@tool(cache=False)` 标记的工具始终执行，不查缓存
- [ ] 跨 `chat()` 调用时（TTL=None 模式），新对话的首次调用不命中旧缓存
- [ ] TTL 模式下，TTL 内跨对话调用命中缓存
- [ ] 缓存命中时 `ToolExecutionResult.repair_notes` 包含 `"cache_hit"`
- [ ] `ToolRuntime(cache_size=0)` 等价于禁用缓存

## Blocked by

- [P1-1: ToolCallCache LRU + TTL 实现](./P1-1-tool-call-cache.md)

## Test suggestions

- Mock tool function 记录 `called_count`，验证缓存命中时不增长
- 测试 `@tool(cache=False)` 标记绕过缓存
- 参考 `tests/test_tool_executor.py` 的现有测试模式
