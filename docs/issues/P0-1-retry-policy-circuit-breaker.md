# P0-1: RetryPolicy + CircuitBreaker 状态机

**状态**: `ready-for-agent`
**优先级**: P0
**类型**: AFK

## Parent

[P0: 智能重试 + 熔断器](../prd/P0-smart-retry-circuit-breaker.md)

## What to build

实现重试策略配置类和熔断器状态机，两者均为纯逻辑模块，不依赖外部 API。

**RetryPolicy**：封装所有重试相关的可配置参数——最大重试次数、基础延迟、退避倍数、最大延迟、jitter 范围、熔断阈值、冷却时间。提供三个预设：`default`（4次重试/1s基础）、`aggressive`（8次/0.5s）、`gentle`（2次/5s）。

**CircuitBreaker**：三态状态机 —— Closed → Open → HalfOpen → Closed。Closed 下正常放行；连续失败达到阈值转入 Open（拒绝所有请求，抛出 `CircuitBreakerOpenError`）；冷却时间过后转入 HalfOpen；HalfOpen 下允许一次探测，成功转 Closed，失败回 Open。必须线程安全（`threading.Lock`）。

错误码分类常量：可重试 `[503, 502, 504, 500]` + 网络异常，需等待重试 `[429]`，不可重试 `[400, 401, 402, 403, 404]`。

退避公式：
```
delay = min(base_delay * (backoff_factor ** attempt) + random(0, base_delay), max_delay)
```

## Acceptance criteria

- [ ] RetryPolicy 提供 `default`/`aggressive`/`gentle` 三个预设，各自参数合理
- [ ] RetryPolicy 支持逐字段覆盖自定义
- [ ] CircuitBreaker 初始状态为 Closed，`allow_request()` 返回 True
- [ ] 连续调用 `record_failure()` 达阈值后 `allow_request()` 返回 False
- [ ] Open 状态经过冷却时间后，`allow_request()` 返回 True 且状态转为 HalfOpen
- [ ] HalfOpen 下一次 `record_success()` 转 Closed，一次 `record_failure()` 回 Open
- [ ] 两个线程同时操作 CircuitBreaker 不出现竞态条件
- [ ] CircuitBreakerOpenError 携带剩余冷却秒数
- [ ] 错误码分类常量与 DeepSeek API 实际行为一致

## Blocked by

None - can start immediately
