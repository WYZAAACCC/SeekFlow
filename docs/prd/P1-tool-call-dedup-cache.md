# P1: 工具调用去重缓存

## Problem Statement

DeepSeek 模型在多轮对话中存在**重复工具调用**行为。例如：

```
用户: "北京天气怎么样？"
模型: 调用 get_weather(city="北京")
结果: {"city": "北京", "temp": 22}

用户: "那温度适合出门吗？"（上下文已有天气数据）
模型: 再次调用 get_weather(city="北京")  ← 重复！
```

相同工具 + 相同参数被调用两次，浪费了：
- **API Token**：tool call 的 JSON schema、arguments、tool result 都计入 prompt tokens
- **延迟**：工具执行耗时（特别是调用外部 API 的场景）
- **DeepSeek 费用**：多余的模型推理

当前 `ToolRuntime` 没有任何去重机制。每次 tool call 都无条件执行。

## Solution

在 `ToolExecutor` 层增加一个**透明的工具调用缓存层**。以 `(tool_name, frozenset(args.items()))` 为缓存键，存储最近 N 次工具调用结果。同一次 `chat()` 调用内命中缓存时直接返回，不执行 tool function。

对外接口不变：`ToolRuntime` 初始化时传入 `cache_size` 和 `cache_ttl` 即可。Trace 中记录缓存命中事件，方便调试。

核心设计决策：
- 缓存生命周期 = 单次 `chat()` 调用（不跨对话共享），避免过期数据问题
- 可选地支持跨调用缓存（TTL 模式），适用于只读工具如天气查询、知识库搜索

## User Stories

1. 作为一个多轮对话用户，当我在同一对话中两次问及同一个城市天气时（如"北京天气"→"上海呢"→"北京温度多少"），第二次调用同一个工具相同参数时应该直接返回缓存结果，而不是再调一次 DeepSeek API。
2. 作为一个使用外部 API 工具的用户（如 HTTP 请求工具），我希望相同请求不重复发送，节省第三方 API 配额和费用。
3. 作为一个调试者，我希望在 trace 中看到 `cache_hit` 事件，明确知道哪些工具调用被缓存了、哪些是真正执行的。
4. 作为一个配置者，我希望可以设置缓存容量上限（如最多缓存 128 个结果），防止内存无限制增长。
5. 作为一个配置者，对于实时性要求高的工具（如股票价格），我希望可以通过 `@tool(cache=False)` 标记跳过缓存。
6. 作为一个调用者，当工具参数中有细微差别时（如 `limit=3` vs `limit=5`），我希望它们被正确识别为不同的缓存键，不会错误命中。

## Implementation Decisions

### 模块划分

- **新增模块：`ToolCallCache`** — 基于 `OrderedDict` 的 LRU 缓存。键为 `(tool_name, frozenset(sorted(args.items())))` 的 hash，值为 `ToolExecutionResult`。支持容量上限和 TTL。
- **修改模块：`ToolExecutor.execute()`** — 执行前先查缓存。命中 → 返回缓存结果 + 记录 `cache_hit` trace。未命中 → 执行 → 写入缓存 → 返回。
- **修改模块：`@tool` 装饰器** — 增加 `cache: bool = True` 参数，`ToolDefinition.metadata` 中存储该标志。
- **修改模块：`ToolRuntime`** — 接受 `cache_size: int = 128`、`cache_ttl: float | None = None` 参数。

### 缓存键设计

```python
cache_key = (tool_name, json.dumps(arguments, sort_keys=True, ensure_ascii=False))
```

### 缓存生命周期

- **默认模式（对话级）**：`ToolRuntime.chat()` 开始时创建新缓存，结束时销毁。不跨对话。
- **可选模式（TTL）**：由 `ToolRuntime` 创建一次，在所有 `chat()` 调用间共享。适合无状态只读工具。

### LRU 驱逐

`ToolCallCache` 内部使用 `OrderedDict`，命中时 `move_to_end`，满容量时 `popitem(last=False)` 驱逐最久未使用项。

## Testing Decisions

### 测试原则
- 验证缓存命中/未命中行为，不验证具体 hash 实现
- 测试 LRU 驱逐策略（容量上限、访问时间顺序）
- 用 mock tool function 验证 `tool.called_count` 以区分缓存命中 vs 真实执行

### 测试模块
- `ToolCallCache` 单元测试：命中、未命中、LRU 驱逐、TTL 过期
- `ToolExecutor` 集成测试：注入缓存，验证 `execute()` 命中时不调 tool function
- `@tool(cache=False)` 标记测试：验证标记后跳过缓存
- `ToolRuntime` 端到端测试：多轮对话中验证缓存命中减少 API 调用

### 参考先例
- `tests/test_tool_executor.py` 的 mock 模式
- `verify_reliability.py` B6 多轮对话测试

## Out of Scope

- 跨进程缓存共享（Redis 等）
- 缓存预热策略
- 缓存持久化到磁盘
- 基于语义相似度的模糊缓存匹配（如 "北京" vs "北京市"）
- 缓存数据压缩

## Further Notes

- 缓存键排序 arguments 的 keys 确保 `{"a": 1, "b": 2}` 和 `{"b": 2, "a": 1}` 命中同一缓存
- 对于有副作用（写入类）的工具，开发者应主动标记 `@tool(cache=False)`
- 可以在 `ToolDefinition.metadata` 中扩展 `cache_ttl_override`，让工具级 TTL 覆盖全局 TTL
