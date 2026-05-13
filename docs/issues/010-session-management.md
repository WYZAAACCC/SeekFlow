# Issue #10: 会话管理

**优先级**: P2  
**状态**: 待开始（阻塞中 — 等待 #9）  
**分类**: enhancement  
**Triage**: ready-for-agent  
**Phase**: 3 — 开发者体验  
**依赖**: #9 Async 运行时支持  
**覆盖用户故事**: #13 (内置会话管理)

---

## 背景

当前库中，用户需要手动维护 `messages` 列表进行多轮对话：

```python
messages = [{"role": "system", "content": "..."}]
while True:
    user_input = input()
    messages.append({"role": "user", "content": user_input})
    result = rt.chat(model=..., messages=messages)
    messages.append({"role": "assistant", "content": result.final})
```

这个模式有三个问题：
1. **容易出错**：忘记追加 assistant message、reasoning_content 等
2. **无法持久化**：会话不能保存和恢复
3. **无自动压缩**：长对话会不断膨胀直到超出上下文窗口

## 任务

1. 新建 `seekflow/session.py`
2. 实现 `Session` 类：
   - `add_message(role, content)` — 追加消息
   - `messages` 属性 — 返回完整消息列表（含 reasoning_content）
   - `save(path)` / `Session.load(path)` — 持久化到 JSON
   - `metrics` — 当前会话的 token/成本统计
3. 自动摘要集成（依赖 #7 上下文管理上线后）：
   - 当 `messages` token 预算超限时自动触发压缩
   - 保留 system prompt 和最近 N 轮对话
4. 集成 `ToolRuntime.chat()` 和 `chat_async()`：
   - `rt.chat(model=..., session=session)` — 自动使用 session.messages
   - 返回后自动追加 assistant message 到 session

## 验收标准

- [ ] `Session` 正确追踪消息历史
- [ ] `session.save()` + `Session.load()` 往返无损
- [ ] `reasoning_content` 在会话中正确保留
- [ ] 集成 #7 后超长会话自动摘要
- [ ] 与 `chat()` 和 `chat_async()` 集成后自动追加消息
- [ ] 新增 ≥8 个测试

## 测试建议

- 测试 save/load 往返（含 tool results、reasoning_content）
- 测试空会话、单轮、多轮场景
- 测试 load 不存在的文件
- 测试 load 损坏的 JSON
- 测试与 #7 压缩的集成
- 参考现有消息管理：[src/seekflow/runtime.py](../../src/seekflow/runtime.py)
