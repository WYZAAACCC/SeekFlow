# Issue #2: 速率限制感知与自适应退避

**优先级**: P0  
**状态**: 待开始（阻塞中 — 等待 #1）  
**分类**: enhancement  
**Triage**: ready-for-agent  
**Phase**: 0 — 基础设施  
**依赖**: #1 错误分类体系重构  
**覆盖用户故事**: #2 (自动处理 429 限流), #3 (自适应退避)

---

## 背景

DeepSeek API 使用动态速率限制，通过响应头返回当前状态：
- `X-RateLimit-Remaining` — 剩余配额
- `X-RateLimit-Reset` — 配额重置时间

当前 `RetryExecutor` 只有盲重试（指数退避），不感知速率限制状态。在高并发场景下这会导致：
1. 已达到限流阈值仍持续发送请求，全部失败
2. 不等待 `X-RateLimit-Reset` 指定的时间就重试
3. 无法做主动减速（在接近阈值时降低发送速率）

## 任务

1. 在 `retry.py` 中新增 `RateLimitAwareExecutor` 类
2. 解析 DeepSeek 响应头中的 `X-RateLimit-Remaining`、`X-RateLimit-Reset`
3. 实现自适应退避策略：
   - `remaining > 20%`：正常速度，退避 1s 起
   - `remaining <= 20%`：主动减速，请求间隔增加
   - `remaining == 0`：停止发送，等待 `reset` 时间
4. 响应头缺失时退回到现有盲重试逻辑
5. 提供 `RateLimitState` 对象供调用方监控当前限流状态
6. 与现有 `RetryExecutor` 的指数退避策略整合（非替换）

## 验收标准

- [ ] Mock 429 + `X-RateLimit-Remaining: 0` 后，后续请求等待 `reset` 时间再发送
- [ ] `remaining` 低于 20% 阈值时日志输出警告
- [ ] 响应头缺失时回退到盲重试（不崩溃）
- [ ] 与 #1 的 `RateLimitError` 类型正确联动
- [ ] 现有 274 个测试不受影响
- [ ] 新增 ≥8 个测试覆盖限流场景

## 测试建议

- Mock HTTP 响应注入不同的 `X-RateLimit-*` 头值
- 测试阈值边界：20% 恰好、0%、100%
- 测试头缺失时的退化路径
- 测试 `RateLimitState` 的状态转换
- 使用 `time.sleep` mock 验证等待时间正确
- 参考现有测试：[tests/test_chat_batch.py](../../tests/test_chat_batch.py)
