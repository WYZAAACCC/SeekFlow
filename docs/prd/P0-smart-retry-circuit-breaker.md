# P0: 智能重试 + 熔断器

## Problem Statement

DeepSeek API 在生产环境中比 OpenAI 更不稳定。用户在使用 `ToolRuntime.chat()` 时频繁遇到以下故障：

- **503 Service Unavailable**：DeepSeek 服务端过载，请求被拒绝。当前直接抛异常，对话循环崩溃。
- **429 Rate Limit**：并发或高频调用触发限流。当前无等待策略，立即失败。
- **网络抖动**：TCP 超时、DNS 解析失败。当前 `timeout=60` 是唯一防护。
- **400 Bad Request**：参数错误或消息格式问题。当前和 503 一样处理，无区分。

用户需要的是一个**理解 DeepSeek 错误码语义**的重试机制，而不是裸 `try/except`。每次崩溃意味着整个对话上下文丢失，用户必须从头开始。

## Solution

在 `DeepSeekClient` 和 `ToolRuntime` 之间插入一个**智能重试层**，根据 DeepSeek 错误码执行不同的恢复策略：

- 503 / 网络错误 → 指数退避重试（1s → 2s → 4s → 8s），带随机 jitter 避免惊群
- 429 Rate Limit → 解析 `Retry-After` 响应头，精确等待后重试
- 400 / 401 / 402 → 不可重试，立即抛出明确错误
- 连续失败 5 次 → 熔断器打开，拒绝新请求 30 秒，冷却后进入半开状态试探

用户无感知使用：`ToolRuntime` 初始化时传入重试策略即可，现有 `chat()` 和 `chat_stream()` 接口不变。

## User Stories

1. 作为一个 API 调用者，当 DeepSeek 返回 503 时，我希望系统自动指数退避重试，而不是直接崩溃，这样我的对话不会因为一次服务端抖动而丢掉全部上下文。
2. 作为一个 API 调用者，当我触发 429 限流时，我希望系统读取 `Retry-After` 头并精确等待后重试，而不是盲目重试导致更严重的限流。
3. 作为一个 API 调用者，当 DeepSeek 连续不可用（如持续 5 次 503）时，我希望系统自动熔断，停止无效重试，避免浪费资源和堆积请求。
4. 作为一个 API 调用者，熔断器冷却后，我希望系统自动进入半开状态，用一个探测请求试探服务是否恢复。
5. 作为一个 API 调用者，当我发送了格式错误的请求（400）时，我希望系统立即失败并给出明确错误信息，而不是浪费时间去重试一个注定失败的请求。
6. 作为一个调试者，我希望每次重试和熔断事件都被记录到 trace 中，包括重试次数、等待时间、错误码。
7. 作为一个配置者，我希望可以自定义最大重试次数、退避倍数、熔断阈值、冷却时间，以适应不同的业务场景。
8. 作为一个批次处理用户，我希望重试策略同时适用于 `chat()` 和 `chat_stream()`，不会因为流式调用而绕过重试逻辑。

## Implementation Decisions

### 模块划分

- **新增模块：`RetryPolicy`** — 纯数据类，封装重试配置（最大重试次数、基础延迟、退避倍数、jitter 范围、熔断阈值、冷却时间）。提供几个预设（`default`, `aggressive`, `gentle`）。
- **新增模块：`CircuitBreaker`** — 状态机：`Closed → Open → HalfOpen → Closed`。Closed 状态下正常放行请求；连续失败达到阈值转 Open；Open 状态下直接拒绝请求并抛出 `CircuitBreakerOpenError`；冷却时间过后转 HalfOpen；HalfOpen 下允许一个探测请求通过，成功则转 Closed，失败则回到 Open。
- **新增模块：`RetryExecutor`** — 接收 `RetryPolicy` 和 `CircuitBreaker`，包装 `DeepSeekClient` 的 `chat()` 和 `chat_stream()` 调用。按错误码分类执行重试/熔断逻辑。
- **修改模块：`ToolRuntime`** — 接受 `RetryPolicy` 参数并传递给 `DeepSeekClient`。trace recorder 增加 `retry_attempt` 和 `circuit_breaker_state_change` 事件类型。

### 错误码分类

```
可重试：503, 502, 504, 500 (server errors), 网络超时, 连接重置
需等待重试：429 (rate limit) — 读取 Retry-After 头
不可重试：400, 401, 402, 403, 404
```

### 退避公式

```
delay = min(base_delay * (backoff_factor ** attempt) + random_jitter, max_delay)
jitter ∈ [0, base_delay)
```

### 熔断器状态机

```
        ┌─────────┐  连续失败 ≥ threshold   ┌──────┐
        │  CLOSED  │ ────────────────────────→ │ OPEN  │
        └─────────┘                           └──────┘
              ↑         探测成功                    │
              └─────────────────────────────────────┘
              │         HemiOpen                    │
              └───────── cool_down 过期 ────────────┘
```

## Testing Decisions

### 测试原则
- 只测试外部行为：给定错误码 → 断言重试次数、退避间隔范围、熔断器状态转换
- 不测试具体 `time.sleep()` 调用（用 mock 时钟或 fake sleep）
- 不测试 OpenAI SDK 内部行为

### 测试模块
- `CircuitBreaker` 状态机：独立单元测试，覆盖 Closed→Open→HalfOpen→Closed 完整循环
- `RetryExecutor`：注入 fake client（返回可控错误码），验证重试次数、退避曲线、熔断触发
- `ToolRuntime` 集成测试：真实 DeepSeek API 调用 + 极大缩短的重试参数，验证端到端不崩

### 参考先例
- `tests/test_tool_executor.py` 的 mock tool 模式
- `verify_reliability.py` 的 `unreliable_tool` 错误恢复测试

## Out of Scope

- 跨进程/跨请求的熔断器状态共享（如 Redis 存储）— 当前只做进程内
- 对非 DeepSeek API 的重试策略适配
- Rate Limit 的主动预判（如 token bucket 客户端限速）
- 用户自定义错误分类规则

## Further Notes

- `CircuitBreaker` 应该是线程安全的（`threading.Lock`），因为 `ToolRuntime` 在并发场景（如 `ThreadPoolExecutor`）下可能多线程共享 client
- 熔断器打开时的异常应该携带冷却剩余时间，让上层可以展示给用户或做 UI 反馈
- 考虑到 DeepSeek 的 `reasoning_content` 字段已经捕获但未利用，重试时是否保留 reasoning 需要决策（建议：不保留，只保留最终成功的 reasoning）
