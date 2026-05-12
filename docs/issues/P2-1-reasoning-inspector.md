# P2-1: ReasoningInspector 工具名提取 + 一致性校验

**状态**: `ready-for-agent`
**优先级**: P2
**类型**: AFK

## Parent

[P2: Reasoning Content 利用](../prd/P2-reasoning-content-utilization.md)

## What to build

实现从 DeepSeek `reasoning_content` 中提取工具名称并进行一致性校验的纯函数模块。

核心设计：
- `extract_tool_names(reasoning: str, registered_names: list[str]) -> set[str]`：用正则 `\b(name1|name2|...)\b` 从 reasoning 文本中匹配已注册的工具名。注意需 `re.escape` 每个工具名避免特殊字符问题
- `check_consistency(reasoning: str | None, actual_tool_names: list[str], registered_names: list[str]) -> ConsistencyResult`：
  - reasoning 为 None 或空 → `ConsistencyResult.NO_REASONING`
  - 提取的工具名集合与实际调用集合一致 → `ConsistencyResult.CONSISTENT`
  - 不一致 → `ConsistencyResult.MISMATCH`，附带 reasoning 提到的名称和实际调用的名称
- `ConsistencyResult` 为枚举或 dataclass，包含 `status`、`reasoning_mentions`、`actual_calls` 字段
- 纯函数，不抛异常——匹配失败返回 `NO_REASONING` 而非崩溃

## Acceptance criteria

- [ ] 中文 reasoning 文本中正确提取英文工具名
- [ ] 空 reasoning 返回 `NO_REASONING`，不抛异常
- [ ] reasoning 提到 "get_weather" 但实际调了 "get_time" → `MISMATCH`
- [ ] reasoning 未提到任何工具名但实际有调用 → `CONSISTENT`（不误报）
- [ ] 工具名是另一个工具名的子串时不误匹配（如 `get_weather` 和 `get_weather_v2`）
- [ ] 性能：单次 `extract_tool_names` 调用耗时 < 1ms（对常规长度 reasoning）

## Blocked by

None - can start immediately
