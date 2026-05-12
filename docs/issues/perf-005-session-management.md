# perf-005: 多轮会话管理 — 自动窗口监控 + 智能压缩 + 对话分支

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

当前 `_session_messages` 是原始列表，无主动窗口监控、无自动压缩触发、无对话分支。生产环境中多轮对话需要：(1) 窗口接近上限时自动压缩 (2) 对话分支——从历史某个点分叉 (3) 回滚到任意轮次。Claude Code 的会话管理是这方面最成熟的参考。

## 任务

1. Agent 增加 `session_monitor` 属性：实时跟踪上下文使用率
2. 上下文使用率达 80% 时自动触发 ContextCompressor
3. 上下文使用率达 95% 时发出 UserWarning + 强制压缩
4. Agent 增加 `fork_session(from_turn: int) -> str`：从指定轮次分叉新会话
5. Agent 增加 `rollback(to_turn: int)`：回滚到指定轮次
6. session 自动保存到 `~/.deepseek_toolkit/sessions/`（JSONL 格式）
7. Agent 增加 `list_sessions()` 和 `load_session(session_id)`

## 验收标准

- [ ] 多轮对话超过窗口 80% 时自动压缩
- [ ] fork_session(3) 创建新会话，包含前 3 轮历史
- [ ] rollback(2) 后 run() 使用前 2 轮历史
- [ ] 会话自动持久化到磁盘

## 测试建议

- E2E：10 轮对话 → 自动压缩触发 → 验证压缩后上下文减少
- 单元测试：fork/rollback 状态正确性
- 单元测试：会话 JSONL 序列化/反序列化

## 分类: ready-for-agent
