# prod-003: 主动速率控制 — Token bucket 限流

**状态**: 待开始
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

当前只有被动速率处理：429 → RetryAfter 退避。生产环境需要主动控制，避免触发 429。多个 Agent 并发时无全局速率预算。DeepSeek API 有 RPM/TPM 限制。

## 任务

1. 创建 `RateController` 类（token bucket 算法）
2. 支持 RPM（每分钟请求数）和 TPM（每分钟 token 数）两种限制
3. Agent.__init__ 增加 `max_rpm: int | None` 和 `max_tpm: int | None`
4. run() 调用前检查 bucket，token 不足时 sleep 等待
5. 支持全局共享 RateController（多个 Agent 共享同一 API key 的速率预算）
6. 速率状态通过 Agent.rate_limit_status 属性暴露

## 验收标准

- [ ] 设置 max_rpm=2 时连续 3 次 run() 被限速，总时间 ≥30s
- [ ] 全局共享 RateController 正确协调多个 Agent
- [ ] 速率不足时状态正确反映等待时间

## 测试建议

- 单元测试：token bucket 的 refill 逻辑
- 集成测试：2 个共享 RateController 的 Agent 并发
- 不发起真实 API 调用（mock 即可）

## 分类: ready-for-agent
