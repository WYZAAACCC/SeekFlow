# v3-024: Agent 层面 checkpoint

**状态**: 已完成
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景
Crew 层面有 checkpoint，但 Agent.run() 中没有。PRD 承诺 Agent 每个 tool_call 后自动保存状态。

## 任务
1. Agent.run() 接受 checkpoint_store 和 thread_id
2. 执行完成后自动保存 checkpoint

## 验收标准
- [x] 传入 checkpoint_store 时 run() 自动保存
- [x] checkpoint 包含完整消息历史

## 分类: ready-for-agent
