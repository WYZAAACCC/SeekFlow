# Issue #1: 错误分类体系重构

**优先级**: P0  
**状态**: 待开始  
**分类**: enhancement  
**Triage**: ready-for-agent  
**Phase**: 0 — 基础设施  
**依赖**: 无 — 可立即开始  
**覆盖用户故事**: #3 (精确错误分类), #5 (生产级错误不静默失败)

---

## 背景

当前 `errors.py` 仅定义了基础异常类型，所有 DeepSeek API 错误被笼统捕获。生产环境中需要精确区分：
- **402** 余额不足 → 需充值告警，不应重试
- **429** 速率限制 → 需自适应退避，解析 `X-RateLimit-Remaining` 头
- **401** 认证失败 → 需检查 API Key
- **503** 服务不可用 → 需等待恢复
- **400** 上下文超长 → 需截断或压缩

目前这些错误被 OpenAI SDK 抛出为通用 `APIError`，调用方无法针对不同类型编写降级逻辑。

## 任务

1. 在 `seekflow/errors.py` 中建立完整的错误类型层次：
   ```
   DeepSeekError (基类)
   ├── AuthenticationError (401)
   ├── InsufficientBalanceError (402)
   ├── RateLimitError (429)
   │   ├── remaining: int | None
   │   └── reset: float | None
   ├── ContextLengthExceededError (400)
   ├── ServiceUnavailableError (503)
   └── DeepSeekAPIError (其他非预期错误)
   ```
2. 每个错误类型携带 `suggestion: str` 属性，给出可操作的修复建议
3. 修改 `DeepSeekClient.chat()` 和 `chat_stream()`，捕获 OpenAI SDK 异常并映射为 DeepSeek 特定错误
4. 修改 `ToolRuntime`，在错误传播时保留错误类型（不吞没为通用异常）
5. 将 HTTP 状态码和响应体中的错误信息提取到错误对象中

## 验收标准

- [ ] 调用已欠费 API Key 抛出 `InsufficientBalanceError`，含 `suggestion`
- [ ] 触发 429 限流抛出 `RateLimitError`，含 `remaining` 和 `reset` 字段
- [ ] 无效 API Key 抛出 `AuthenticationError`
- [ ] 上下文超长抛出 `ContextLengthExceededError`
- [ ] 所有错误类型继承自 `DeepSeekError`，可统一捕获
- [ ] 现有 274 个测试不受影响
- [ ] 每个错误类型有对应的单元测试（Mock HTTP 响应）

## 测试建议

- Mock `openai.APIError` 的子类（`AuthenticationError`、`PermissionDeniedError` 等），验证映射正确
- 测试未知 HTTP 状态码映射为通用 `DeepSeekAPIError`
- 测试 `suggestion` 内容对每种错误类型非空
- 测试异常链保留（`raise DeepSeekError(...) from original`）
- 参考现有测试风格：[tests/test_files.py](../../tests/test_files.py)
