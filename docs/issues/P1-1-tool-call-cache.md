# P1-1: ToolCallCache LRU + TTL 实现

**状态**: `ready-for-agent`
**优先级**: P1
**类型**: AFK

## Parent

[P1: 工具调用去重缓存](../prd/P1-tool-call-dedup-cache.md)

## What to build

实现一个基于 LRU + TTL 的工具调用结果缓存，纯逻辑模块，不依赖外部 API。

核心设计：
- 基于 `OrderedDict` 实现 LRU 驱逐
- 缓存键：`(tool_name, json.dumps(arguments, sort_keys=True, ensure_ascii=False))` 的 hash。对 key 排序确保 `{"a":1,"b":2}` 和 `{"b":2,"a":1}` 命中同一缓存
- 缓存值：`ToolExecutionResult`
- 容量上限可配置（默认 128），满时驱逐最久未使用项
- TTL 可选（默认 None = 对话级生命周期），传入 float 则为秒数
- `get(key)` → 命中返回结果 + 调用 `move_to_end()`，过期返回 None
- `put(key, value)` → 写入 + 满时 LRU 驱逐
- `clear()` → 清空
- 线程安全：使用 `threading.Lock`

缓存键生成独立为函数 `make_cache_key(tool_name: str, arguments: dict) -> str`，方便外部使用和测试。

## Acceptance criteria

- [ ] 相同 tool_name + 相同 arguments 命中缓存，返回缓存结果
- [ ] arguments key 顺序不同但语义相同，命中同一缓存
- [ ] 容量满时驱逐最久未使用项（非最久插入项）
- [ ] TTL 模式下，过期缓存不命中
- [ ] 多线程并发读写不出现数据错乱
- [ ] `clear()` 后所有缓存不可命中
- [ ] 缓存命中率可通过 `hits / (hits + misses)` 查询

## Blocked by

None - can start immediately
