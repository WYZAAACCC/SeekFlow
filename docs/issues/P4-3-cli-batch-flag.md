# P4-3: CLI `seekflow eval run --batch`

**状态**: `ready-for-agent`
**优先级**: P4
**类型**: AFK

## Parent

[P4: DeepSeek Batch API 模式](../prd/P4-batch-api-mode.md)

## What to build

在 CLI 中新增 `--batch` 选项，让 `seekflow eval run` 可以用 Batch API 运行 benchmark。

具体工作：
- CLI `eval run` 命令新增 `--batch` flag 和 `--batch-poll-interval`、`--batch-max-wait` 选项
- `--batch` 模式下，benchmark runner 收集所有 eval 用例后用 `chat_batch()` 一次性提交
- 输出进度：提交中 → 等待中（显示轮询次数和预估剩余时间）→ 下载结果中 → 完成
- 无 `--batch` 时行为不变
- 帮助文本中注明 batch 模式价格为实时 API 的 50%，但不支持多步工具循环

## Acceptance criteria

- [ ] `seekflow eval run benchmarks/basic_tools.yaml --batch` 成功运行并输出结果
- [ ] 控制台显示 batch 进度（提交/等待/下载）
- [ ] 无 `--batch` 时行为完全不变
- [ ] `--help` 中 batch 选项有完整说明

## Blocked by

- [P4-2: ToolRuntime.chat_batch() + 本地工具执行](./P4-2-chat-batch-method.md)
