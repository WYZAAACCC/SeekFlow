# Issue #3: 余额查询端点封装

**优先级**: P0  
**状态**: 待开始（阻塞中 — 等待 #1）  
**分类**: enhancement  
**Triage**: ready-for-agent  
**Phase**: 1 — DeepSeek 核心 API  
**依赖**: #1 错误分类体系重构  
**覆盖用户故事**: #1 (查询账户余额)

---

## 背景

DeepSeek 提供 `GET https://api.deepseek.com/user/balance` 端点返回账户余额信息。这是生产环境必备功能——运维需要监控余额，避免因欠费导致线上服务中断。

当前库没有任何余额查询能力。用户必须自行拼接 HTTP 请求。该端点返回结构为：
```json
{
  "is_available": true,
  "balance_infos": [
    {"currency": "CNY", "total_balance": "...", "topped_up_balance": "...", "granted_balance": "..."}
  ]
}
```

## 任务

1. 新建 `deepseek_toolkit/balance.py`
2. 实现 `get_balance(api_key=None, timeout=30.0) -> BalanceInfo`：
   - `BalanceInfo` 数据类：`total_balance`, `topped_up_balance`, `granted_balance`, `currency`, `is_available`, `queried_at`
3. 调用 `GET https://api.deepseek.com/user/balance`（Authorization header 与 chat API 一致）
4. 利用 #1 的错误类型处理 401 等错误
5. 内置 300 秒缓存（余额不会秒级变化）
6. CLI 集成：`deepseek-toolkit balance` 命令输出余额信息

## 验收标准

- [ ] `get_balance()` 返回 `BalanceInfo` 含正确余额数据
- [ ] 无效 API Key 抛出 `AuthenticationError`（来自 #1）
- [ ] 网络超时被 `RetryExecutor` 重试
- [ ] 300 秒内重复调用返回缓存值，不发送 HTTP 请求
- [ ] CLI 命令 `deepseek-toolkit balance` 可输出余额
- [ ] 真实 API 验证通过
- [ ] 新增 ≥8 个测试

## 测试建议

- Mock HTTP 响应返回标准 balance JSON
- 测试缓存命中/过期
- 测试 API Key 无效场景
- 测试响应格式变化时的容错（缺少字段不崩溃）
- 参考真实 API 测试模式：[examples/07_real_api_test.py](../../examples/07_real_api_test.py)
