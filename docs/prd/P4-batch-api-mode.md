# P4: DeepSeek Batch API 模式

## Problem Statement

DeepSeek 提供 Batch API——提交一批请求后异步处理，24 小时内完成，**价格是实时 API 的 50%**。但 Batch API 的交互模式与实时 API 完全不同：

- 需要先上传 JSONL 格式的请求文件
- 轮询检查完成状态
- 下载结果 JSONL 文件
- 结果顺序可能与请求顺序不一致

当前 `ToolRuntime.chat()` 只支持实时 API 调用，用户无法享受 Batch API 的半价优惠。在做 benchmark、eval、批量数据处理的场景下，成本翻倍。

## Solution

新增 `ToolRuntime.chat_batch()` 方法，将多组消息一次性提交给 DeepSeek Batch API，自动处理 JSONL 构建、文件上传、状态轮询、结果下载和解析。

接口设计：

```python
results = runtime.chat_batch(
    model="deepseek-chat",
    requests=[
        {"messages": [{"role": "user", "content": "北京天气怎么样？"}]},
        {"messages": [{"role": "user", "content": "上海天气怎么样？"}]},
        {"messages": [{"role": "user", "content": "3+5等于多少？"}]},
    ],
    poll_interval=30.0,   # 轮询间隔（秒）
    max_wait=3600.0,      # 最大等待时间（秒）
)
for result in results:
    print(result.final)
```

## User Stories

1. 作为一个 benchmark 跑者，我希望一次性提交 100 个测试用例到 Batch API，支付一半费用，然后异步等待结果，而不是逐个调实时 API。
2. 作为一个数据处理者，我有一批 500 条消息需要处理（如批量翻译、批量分类），我希望用 batch 模式降低成本且不用关心并发控制。
3. 作为一个调用者，当批量请求中有部分失败时，我希望对应的 result 标记 error，而不是整批丢弃。
4. 作为一个调用者，我不需要关心 JSONL 文件格式、上传路径、状态轮询细节——这些应该被封装在 `chat_batch()` 内部。
5. 作为一个调用者，当 Batch API 任务超过 `max_wait` 仍未完成时，我希望得到一个明确的超时异常，包含已完成的任务数。
6. 作为一个流式调用者，我理解 batch 模式不支持流式（`chat_stream` 不适用于 batch），这是 DeepSeek API 的限制而非库的限制。

## Implementation Decisions

### 模块划分

- **新增模块：`BatchClient`** — 封装 DeepSeek Batch API 的三个阶段：上传（`POST /v1/files` + `POST /v1/batches`）、轮询（`GET /v1/batches/{id}`）、下载解析（`GET /v1/files/{output_file_id}/content`）。
- **修改模块：`ToolRuntime`** — 新增 `chat_batch()` 方法，复用现有的 `ToolExecutor` 处理工具调用循环。
- **修改模块：`DeepSeekClient`** — 新增 `upload_file()`, `create_batch()`, `get_batch_status()`, `download_file()` 方法。

### Batch API 流程

```
1. DeepSeekClient.upload_file(jsonl_content) → file_id
2. DeepSeekClient.create_batch(input_file_id) → batch_id
3. 轮询 DeepSeekClient.get_batch_status(batch_id)
   - validating → in_progress → completed / failed / expired
4. DeepSeekClient.download_file(output_file_id) → results JSONL
5. 解析 JSONL，处理失败条目
```

### 工具调用处理

Batch API 目前**不支持在 batch 内部的 tool calling 循环**。因此：

- 如果请求中包含 tools，`chat_batch()` 只执行**一轮**：模型返回 tool_call → 本地执行工具 → 将 tool result 拼接到消息中 → 作为单轮结果返回
- 不做多步工具循环（`max_steps=1` 硬编码）
- Trace 中记录 `batch_tool_execution` 事件，标注这是 batch 模式下的本地工具执行

### 并发安全性

- 上传 JSONL 前做本地校验（消息格式、tool schema 兼容性）
- 失败条目不阻塞成功条目的结果解析
- 结果顺序保持与 `requests` 参数一致的顺序（内部用 custom_id 映射）

## Testing Decisions

### 测试原则
- Mock DeepSeek Batch API 端点，测试上传/轮询/下载流程
- 不测试真实 Batch API 的 24 小时完成窗口（无法自动化）
- 测试失败场景：上传失败、batch 过期、部分条目失败

### 测试模块
- `BatchClient` 单元测试（mock HTTP）：上传流程、轮询状态转换、结果解析
- `BatchClient` 错误处理测试：上传失败、batch expired、空结果、格式错误的 JSONL
- `ToolRuntime.chat_batch()` 集成测试（mock）：端到端 3 条请求 + 工具调用
- 结果顺序保持测试：验证 custom_id 映射正确

### 参考先例
- `tests/test_runtime.py` 的 mock client 模式
- `benchmark/production_benchmark.py` 的并发 runner 模式

## Out of Scope

- Batch API 内的多步工具调用循环（DeepSeek API 限制）
- Batch 请求的本地排队和调度
- 跨多次 `chat_batch()` 调用的批次管理和历史记录
- Batch API 与流式模式的兼容（API 层面不支持）
- 对 OpenAI/Azure Batch API 的适配

## Further Notes

- Batch API 的 50% 折扣意味着每个 benchmark 运行的 API 成本从 ~$2 降到 ~$1——对高频 benchmark 场景有实际价值
- JSONL 构建使用 `json.dumps(..., ensure_ascii=False)` 以支持中文
- 建议 `chat_batch()` 在 CLI 中暴露为 `dstk eval run --batch` 选项
- 轮询间隔默认 30 秒，最小不应低于 10 秒（避免触发 DeepSeek 的请求频率限制）
