# polish-002: Parallel Crew 线程安全压力测试

**状态**: 待开始
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

`_make_runtime()` 有 `threading.Lock` 保护，但 Agent 的其他共享状态（`_session_messages`、`_cache_stats`、`memory`）在 Parallel Crew 中可能被多个线程同时修改。Parallel Crew 使用 `ThreadPoolExecutor` 将同一个 Agent 实例分配给多个线程执行——这是最高风险的竞态场景。

## 任务

1. 构造共享 Agent 的 Parallel Crew 场景：
   - 1 个 Agent 实例 + 3 个 Task → Parallel Crew
   - Agent 启用 memory（`enable_memory()`）
   - 每个 Task 调用 `agent.chat()`（会写 `_session_messages`）
   - 连续跑 50 次

2. 每次运行后检查：
   - `_session_messages` 长度是否与并发 Task 数一致（无丢失/重复）
   - `cache_stats` 的 total_requests 是否等于实际执行次数
   - `memory.stats()` 的 long_term_items 是否合理
   - 无异常堆栈

3. 构造共享工具冲突场景：
   - 2 个 Agent 共享同一个可变工具（如一个写文件的工具）
   - Parallel Crew 执行，验证工具调用的结果正确且无竞争

## 验收标准

- [ ] 50 次 Parallel Crew 执行零崩溃
- [ ] `_session_messages` 无数据竞争（长度一致性检查）
- [ ] `cache_stats` 计数精确
- [ ] 共享工具无数据损坏

## 测试建议

- 前 10 次用真实 API 验证功能正确
- 后 40 次可 mock API 加速（只测竞态，不测 API）
- 如果发现竞态，在对应字段加 `threading.Lock` 保护
- 结果写入 `output/polish/race/` 目录

## 分类: ready-for-agent
