# Issue #9: Async 运行时支持

**优先级**: P2  
**状态**: 待开始  
**分类**: enhancement  
**Triage**: ready-for-agent  
**Phase**: 3 — 开发者体验  
**依赖**: 无 — 可立即开始  
**覆盖用户故事**: #12 (async API)

---

## 背景

当前库所有 API 调用都是同步的（`requests` → `openai.OpenAI`）。现代 Python Web 框架（FastAPI、Starlette、aiohttp）全部基于 asyncio 事件循环，同步调用会阻塞整个线程。

要接入这些框架，用户被迫使用 `asyncio.to_thread()` 或 `ThreadPoolExecutor` 包装同步调用，这引入了不必要的线程开销。库需要提供原生的 async 支持：
- `openai.AsyncOpenAI` 已内置异步能力
- 工具调用需要区分 sync/async 函数
- Streaming 在 async 下需要正确处理 `AsyncIterator` 生命周期

## 任务

1. 新建 `seekflow/async_runtime.py`
2. 实现 `AsyncToolRuntime` — `ToolRuntime` 的 async 镜像：
   - `await chat_async(model, messages, tools=None, files=None, **kwargs) -> ToolRuntimeResult`
   - `async for event in chat_stream_async(...) -> AsyncIterator[StreamEvent]`
3. 底层使用 `openai.AsyncOpenAI` 替代 `openai.OpenAI`
4. `AsyncDeepSeekClient` — `DeepSeekClient` 的 async 版本
5. 工具调用执行策略：
   - 检测工具函数签名：`asyncio.iscoroutinefunction(fn)` 判断 async/sync
   - Sync 工具在 async 上下文中用 `asyncio.to_thread()` 包装
   - Async 工具直接 `await`
6. 在 `__init__.py` 中导出 `AsyncToolRuntime`

## 验收标准

- [ ] `chat_async()` 返回结果与同步版 `chat()` 一致
- [ ] `chat_stream_async()` 逐事件产出与同步版一致
- [ ] Sync 工具在 async 上下文中正确执行（不被阻塞）
- [ ] Async 工具在 async 上下文中正确执行
- [ ] 与 asyncio 生态兼容（FastAPI 路由中可直接 await）
- [ ] 现有 274 个测试不受影响（sync 版不变）
- [ ] 新增 ≥10 个测试

## 测试建议

- 使用 `pytest-asyncio` 编写 async 测试用例
- 测试 sync 工具在 async runtime 中的行为
- 测试 async 工具在 async runtime 中的行为
- 测试 streaming async 的取消（`CancelledError`）
- 测试 thinking_mode 在 async 下正常工作
- 参考现有测试：[tests/test_files.py](../../tests/test_files.py)
