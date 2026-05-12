# P0-2: RetryExecutor 包装 DeepSeekClient

**状态**: `ready-for-agent`
**优先级**: P0
**类型**: AFK

## Parent

[P0: 智能重试 + 熔断器](../prd/P0-smart-retry-circuit-breaker.md)

## What to build

在 `DeepSeekClient` 外层包装一个 `RetryExecutor`，根据 DeepSeek 错误码执行分类重试逻辑。

核心行为：
- 包裹 `chat()` 和 `chat_stream()` 方法，保持接口签名不变
- 调用前先过熔断器 `allow_request()`，被拒直接抛 `CircuitBreakerOpenError`
- 503/502/504/500 或网络异常 → 指数退避重试，达上限后 `record_failure()` 并抛出最后一个异常
- 429 → 解析响应头 `Retry-After`，精确等待后重试，不消耗退避次数（需等待不算失败）
- 400/401/402/403/404 → 不重试，直接 `record_failure()` 并抛出
- 成功 → `record_success()`
- 每次重试尝试都记录到 trace（通过注入的 callback 或直接 log）

`RetryExecutor` 接收 `RetryPolicy` 和 `CircuitBreaker` 作为构造参数，默认使用 `RetryPolicy.default()` 和新 `CircuitBreaker`。

## Acceptance criteria

- [ ] 503 错误触发指数退避重试，最多重试 N 次（默认 4 次）
- [ ] 退避延迟符合指数公式 + jitter 范围
- [ ] 429 错误解析 `Retry-After` 头并精确等待，不计入重试次数
- [ ] 400 错误立即失败，不重试
- [ ] 连续 5 次 503 触发熔断，后续请求直接抛 `CircuitBreakerOpenError`
- [ ] 熔断冷却后一次成功调用恢复 Closed 状态
- [ ] `chat_stream()` 的流式调用同样受重试保护（流中断时重试整个流）
- [ ] 不改变 `DeepSeekClient.chat()` 和 `chat_stream()` 的返回类型

## Blocked by

- [P0-1: RetryPolicy + CircuitBreaker 状态机](./P0-1-retry-policy-circuit-breaker.md)

## Test suggestions

- 用 fake client（返回可控 HTTP 状态码）注入 RetryExecutor
- 验证重试次数、退避曲线、熔断触发、429 等待行为
- 参考 `tests/test_tool_executor.py` 的 mock 模式
