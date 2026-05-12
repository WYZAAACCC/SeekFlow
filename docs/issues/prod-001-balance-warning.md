# prod-001: 余额预警 — Agent 运行前检查余额并告警

**状态**: 待开始
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

DeepSeek 是预付费模式。余额用完 → Agent 直接 402 挂掉 → 用户看到 cryptic 错误。balance.py 有 `get_balance()` 但 Agent.run() 从未调用。生产环境必须在余额不足时提前告警，而非等 402 才报错。

## 任务

1. Agent.__init__ 增加 `check_balance: bool = False` 参数
2. 为 True 时，run() 调用前执行 `get_balance(api_key)` 
3. 余额低于阈值（默认 ¥1.00）时发出 UserWarning
4. 余额为 0 时抛出 InsufficientBalanceError（阻止执行，而非 402 后才报）
5. `AgentResult` 增加 `balance_before: float | None` 字段
6. 余额查询结果缓存 60s（避免每次 run() 都查）

## 验收标准

- [ ] `Agent(check_balance=True).run(task)` 余额充足时正常执行
- [ ] 余额不足时抛出中文错误含当前余额和充值链接
- [ ] 余额为 0 时不发起 API 调用（节约一次失败请求）

## 测试建议

- Mock get_balance 返回 ¥0.50 → 验证 warning 发出
- Mock get_balance 返回 ¥0.00 → 验证阻止执行
- 缓存测试：连续 3 次 run() 只调用 1 次 get_balance

## 分类: ready-for-agent
