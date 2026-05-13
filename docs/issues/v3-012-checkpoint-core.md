# v3-012: Checkpoint 核心 — InMemoryStore + SqliteStore

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

---

## 背景

Agent 执行可能耗时数分钟，涉及多次 LLM 调用和工具调用。如果中途失败（网络中断、API 429、工具异常），从头重跑浪费 token 和时间。

LangGraph 的 checkpoint 系统支持中断后恢复，但其实现依赖 channel-based state（每个 graph node 有独立状态通道），复杂度高（涉及 checkpoint/base、checkpoint/serde、pregel/algo 等 42 个文件）。

DTK 的 Agent 是 LLM 驱动的——状态就是消息历史 + 工具调用记录。保存完整对话历史远比保存任意 Python 对象简单。我们可以用不到 LangGraph 1/10 的代码实现同等功能。

## 任务

1. 创建 `seekflow/agent/checkpoint.py`
2. 定义 `AgentCheckpoint` 数据结构：
   - `thread_id: str` — 会话唯一标识
   - `step: int` — 当前步骤号
   - `messages: list[dict]` — 完整消息历史（含 reasoning_content、tool_calls、tool_results）
   - `tool_calls_completed: list[str]` — 已完成的工具调用 ID 列表
   - `timestamp: str` — ISO 8601 创建时间
   - `agent_state: dict` — Agent 额外状态（如 CrewContext）
3. 定义 `CheckpointStore` 抽象基类：
   - `save(checkpoint: AgentCheckpoint) -> None`
   - `load(thread_id: str) -> AgentCheckpoint | None`
   - `delete(thread_id: str) -> None`
   - `list(limit: int = 10) -> list[AgentCheckpoint]`
4. 实现 `InMemoryStore`：基于 dict 的内存存储（默认）
5. 实现 `SqliteStore`：基于 sqlite3 的文件持久化存储（标准库，零依赖）
6. SqliteStore 使用单表设计：`checkpoints(thread_id TEXT PRIMARY KEY, step INTEGER, data JSONB, timestamp TEXT)`

## 验收标准

- [ ] InMemoryStore.save() + .load() 正确存取 checkpoint
- [ ] SqliteStore.save() + .load() 正确存取，重启进程后数据仍存在
- [ ] .list() 返回按 timestamp 倒序排列的 checkpoint
- [ ] .delete() 正确删除指定 checkpoint
- [ ] 并发 save() 同一 thread_id 时 SqliteStore 正确处理（使用 INSERT OR REPLACE）

## 测试建议

- 单元测试：InMemoryStore 完整 CRUD + list
- 单元测试：SqliteStore 完整 CRUD + 跨进程持久化验证
- 边界测试：load 不存在的 thread_id → 返回 None
- 边界测试：save 超大 message history（1000 条消息）

## 分类

**ready-for-agent** — 接口极简（4 个方法），sqlite3 是标准库，无外部依赖。阻塞 Agent checkpoint 集成（v3-013）。
