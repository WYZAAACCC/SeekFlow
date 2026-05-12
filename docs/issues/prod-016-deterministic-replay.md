# prod-016: 确定性重放 — 记录并回放 Agent 执行过程

**状态**: 待开始
**优先级**: P2
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

合规/调试场景需要重放 Agent 的完整执行过程。当前 TraceRecorder 记录事件但回放时仍需调用 LLM——结果不保证一致。需要两种模式：(1) 记录模式保存所有 API 响应 (2) 回放模式使用保存的响应而非真实 API。

## 任务

1. 创建 `RecordMode` Agent wrapper：拦截所有 API 调用，保存完整请求/响应对
2. 创建 `ReplayMode` Agent wrapper：从保存的响应中回放，不调用真实 API
3. 回放输出的 AgentResult 与原始执行完全一致
4. 支持 `agent.run_with_record(task)` 和 `agent.run_with_replay(trace_id)`
5. 记录文件保存到 output/traces/{trace_id}.jsonl

## 验收标准

- [ ] 记录模式下 3 次 API 调用 → 3 对请求/响应被保存
- [ ] 回放模式输出与原始执行一致（逐字段对比）
- [ ] 回放期间不发起真实 API 调用（可断网验证）

## 测试建议

- 端到端：记录→回放→对比 AgentResult 每个字段
- 断网环境下验证回放不依赖网络

## 分类: ready-for-agent
