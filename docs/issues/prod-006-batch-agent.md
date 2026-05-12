# prod-006: Batch Agent 模式 — 利用 DeepSeek Batch API 节省 50% 成本

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

DeepSeek Batch API 价格是实时 API 的 50%。runtime.py 有 BatchClient（提交+轮询+下载），但 Agent.run() 不走 Batch 路径。批量分析 1000 份财报，实时模式 ¥500 vs Batch ¥250——差距 ¥250。

## 任务

1. Agent 增加 `run_batch(tasks: list[str]) -> list[AgentResult]` 方法
2. 内部调用 BatchClient：提交所有任务 → 轮询直到完成 → 下载结果
3. 支持 `poll_interval: int = 30` 和 `max_wait: int = 86400`（24小时）
4. 返回每个任务的 AgentResult 列表，保持原始顺序
5. 进度回调：`on_batch_progress(completed, total)`
6. 成本对比：结果中显示 "Batch 模式节省了 ¥X.XX"

## 验收标准

- [ ] `agent.run_batch([task1, task2, task3])` 返回 3 个 AgentResult
- [ ] Batch 模式成本约为实时模式的 50%
- [ ] 进度回调正常触发
- [ ] 单个任务失败不影响其他任务

## 测试建议

- Mock BatchClient 返回预设结果
- 验证 submit → poll → download 完整流程
- 超时测试：max_wait 到达后优雅退出

## 分类: ready-for-agent
