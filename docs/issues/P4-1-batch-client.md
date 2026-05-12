# P4-1: BatchClient 上传/轮询/下载

**状态**: `ready-for-agent`
**优先级**: P4
**类型**: AFK

## Parent

[P4: DeepSeek Batch API 模式](../prd/P4-batch-api-mode.md)

## What to build

在 `DeepSeekClient` 基础上扩展 Batch API 支持，封装 JSONL 构建、文件上传、Batch 创建、状态轮询、结果下载的完整流程。

核心设计：
- `BatchClient` 类，接收 `DeepSeekClient` 实例
- `submit_batch(requests: list[dict]) -> str`：构建 JSONL → 上传文件 → 创建 batch → 返回 batch_id
- `poll_batch(batch_id: str, poll_interval: float = 30.0, max_wait: float = 3600.0) -> str`：轮询 batch 状态 → 返回状态（`"completed"` / `"failed"` / `"expired"` / `"timeout"`）
- `download_results(batch_id: str) -> list[dict]`：下载输出文件 → 解析 JSONL → 按 custom_id 排序 → 返回结果列表
- JSONL 构建：每行为 `{"custom_id": f"req-{i}", "method": "POST", "url": "/v1/chat/completions", "body": {...}}`
- 错误处理：上传失败重试（3 次）、batch 过期抛出 `BatchExpiredError`、部分条目失败时对应条目标记 error 而非整批丢弃
- 结果排序：按 original request 顺序排列，使用 custom_id 映射

## Acceptance criteria

- [ ] `submit_batch()` 成功提交 10 个请求，返回 batch_id
- [ ] `poll_batch()` 轮询直到 completed，每 30 秒检查一次
- [ ] `download_results()` 返回按原始请求顺序排列的结果列表
- [ ] 3 条请求中 1 条失败，其他 2 条结果正常返回
- [ ] `max_wait` 超时抛出明确异常，含已完成数
- [ ] batch expired 抛出 `BatchExpiredError`
- [ ] JSONL 中 custom_id 正确映射回结果顺序

## Blocked by

None - can start immediately

## Test suggestions

- Mock DeepSeek Batch API HTTP 端点（`/v1/files`、`/v1/batches`）
- 测试完整生命周期：提交 → 轮询 → 下载
- 测试失败路径：上传失败、batch expired、空结果
- Mock 网络以模拟轮询超时
