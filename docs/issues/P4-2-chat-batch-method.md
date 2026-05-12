# P4-2: ToolRuntime.chat_batch() + 本地工具执行

**状态**: `ready-for-agent`
**优先级**: P4
**类型**: AFK

## Parent

[P4: DeepSeek Batch API 模式](../prd/P4-batch-api-mode.md)

## What to build

在 `ToolRuntime` 新增 `chat_batch()` 方法，将多组消息一次性提交 Batch API，自动处理工具调用的本地执行。

核心设计：
- `chat_batch()` 接口签名：
  ```python
  def chat_batch(
      self,
      *,
      model: str,
      requests: list[dict],  # 每个 dict 含 messages 和可选 tools
      poll_interval: float = 30.0,
      max_wait: float = 3600.0,
  ) -> list[ToolRuntimeResult]
  ```
- 流程：构建 JSONL（含 tools schema）→ 提交 Batch → 轮询完成 → 下载结果 → 对每条结果：如果模型返回 tool_call → 本地执行工具 → 将结果拼回消息 → 返回单轮 result（不做多步循环，`max_steps=1` 硬编码）
- 每条结果的 `ToolRuntimeResult` 包含 `batch_id` 字段
- 失败条目的 result 中 `final` 为错误描述，`tool_results` 为空
- Trace 记录 `batch_submit`、`batch_complete`、`batch_tool_execution` 事件

## Acceptance criteria

- [ ] 3 条请求的 batch 调用成功返回 3 个 result
- [ ] 含工具调用的请求在 batch 完成后本地执行工具
- [ ] 5 条请求中 1 条 API 调用失败时，对应 result 标记错误，其余 4 条正常
- [ ] `poll_interval=5.0, max_wait=10.0` 超时抛出异常
- [ ] 结果顺序与请求顺序一致
- [ ] 不支持 batch 的模型（如某些 beta 模型）给出清晰错误提示

## Blocked by

- [P4-1: BatchClient 上传/轮询/下载](./P4-1-batch-client.md)

## Test suggestions

- Mock BatchClient，验证 `chat_batch()` 的结果组装逻辑
- 测试工具调用本地执行路径（mock ToolExecutor）
- 参考 `benchmark/production_benchmark.py` 的并发 runner 模式
