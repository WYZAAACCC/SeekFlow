# P0-3: ToolRuntime 重试集成 + Trace 事件

**状态**: `ready-for-agent`
**优先级**: P0
**类型**: AFK

## Parent

[P0: 智能重试 + 熔断器](../prd/P0-smart-retry-circuit-breaker.md)

## What to build

将 `RetryExecutor` 集成到 `ToolRuntime`，让现有 `chat()` 和 `chat_stream()` 调用自动享受重试保护，无需用户修改调用代码。

具体工作：
- `ToolRuntime.__init__` 新增 `retry_policy: RetryPolicy | None = None` 参数，默认使用 `RetryPolicy.default()`
- 内部用 `RetryExecutor` 包裹 `DeepSeekClient`（替代直接使用裸 client）
- TraceRecorder 新增两种事件类型：`retry_attempt`（重试尝试，含重试次数、等待秒数、错误码）和 `circuit_breaker_change`（熔断器状态变化，含旧状态→新状态、触发原因）
- 熔断器打开时，`ToolRuntime.chat()` 不崩溃——返回 `ToolRuntimeResult` 带明确错误信息和 `circuit_breaker_open: True` 标志
- 暴露 `runtime.circuit_breaker_state` 属性让外部可查询当前熔断状态

## Acceptance criteria

- [ ] `ToolRuntime(retry_policy=RetryPolicy.default())` 开箱即用重试保护
- [ ] 现有 `verify_reliability.py` 所有测试在新代码下通过
- [ ] Trace JSON 包含 `retry_attempt` 事件（当有重试发生时）
- [ ] Trace JSON 包含 `circuit_breaker_change` 事件（当熔断器状态变化时）
- [ ] 熔断打开时 `chat()` 返回带 `circuit_breaker_open=True` 的 result，不抛异常
- [ ] `runtime.circuit_breaker_state` 返回 `"closed"` / `"open"` / `"half_open"` 字符串
- [ ] 不传 `retry_policy` 时行为与当前版本完全兼容

## Blocked by

- [P0-2: RetryExecutor 包装 DeepSeekClient](./P0-2-retry-executor.md)

## Test suggestions

- 用真实 DeepSeek API + 极短重试参数做端到端测试
- Mock client 返回 503 → 验证 trace 中记录了重试
- 参考 `verify_reliability.py` B3 错误恢复测试模式
