# P3-2: @tool(keep_fields=) + ToolExecutor 截断集成

**状态**: `ready-for-agent`
**优先级**: P3
**类型**: AFK

## Parent

[P3: 工具结果智能截断](../prd/P3-intelligent-tool-result-truncation.md)

## What to build

将 JSON-aware 截断算法集成到 `ToolExecutor`，并新增 `@tool(keep_fields=...)` 参数支持字段优先级。

具体工作：
- `@tool` 装饰器新增 `keep_fields: list[str] | None = None` 参数，存入 `ToolDefinition.metadata["keep_fields"]`
- `ToolRuntime.__init__` 新增 `truncation_strategy: TruncationStrategy = TruncationStrategy.JSON_AWARE` 参数
- `ToolExecutor._maybe_truncate()` 根据 `truncation_strategy` 选择截断逻辑，接收 `keep_fields` 参数
- PRIORITY 模式下：先序列化 `keep_fields` 指定的字段路径（JSON path 语法，如 `"data.temperature"`），计入预算
- 剩余预算按字段顺序分配给其他字段
- 保持与当前 `max_result_chars` 参数的向后兼容

## Acceptance criteria

- [ ] `ToolRuntime(truncation_strategy=TruncationStrategy.JSON_AWARE)` 使用 JSON 感知截断
- [ ] `@tool(keep_fields=["temperature", "humidity"])` 标记的字段在截断时被优先保留
- [ ] `truncation_strategy=SIMPLE` 保持当前暴力截断行为
- [ ] 不传 `keep_fields` 时行为合理（所有字段一视同仁）
- [ ] `keep_fields` 指向不存在的字段路径时不崩溃，静默忽略
- [ ] 现有所有测试在新默认策略下通过

## Blocked by

- [P3-1: JSON-aware 截断算法 + 截断元信息](./P3-1-json-aware-truncation.md)
