# v3-003: Agent 工具注册 — `.add_tool()` / `.with_default_tools()`

**状态**: 待开始
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)
**阻塞**: v3-001

---

## 背景

DTK v2 的工具通过 ToolRuntime 的 tools 参数注入，开发者需要手动创建 ToolRuntime。v3 的 Agent 层应将工具注册简化为 Agent 的方法调用。

关键设计决策：**不做全局 Tool Registry**。每个 Agent 实例持有自己的工具列表。避免命名冲突、生命周期管理等全局 Registry 的固有问题。

## 任务

1. 在 `DeepSeekAgent` 上实现：
   - `.add_tool(tool: Callable)` — 注册单个工具
   - `.add_tools(tools: list[Callable])` — 批量注册
   - `.with_default_tools()` — 加载内置工具集（read_file、web_search、calculate、save_result、download_page）
   - `.tools` 属性 — 返回当前注册的工具列表（只读）
2. 工具可以是 DTK `@tool` 装饰的函数，也可以是任意签名为 `(args) -> str` 的 callable
3. 非 `@tool` 装饰的函数自动包装为基本 tool schema（参数名从 inspect 推导）
4. `.run()` 时自动将 Agent 的工具列表注入 ToolRuntime

## 验收标准

- [ ] `agent.add_tool(my_func)` 后 my_func 在 Agent 执行时可用
- [ ] `agent.with_default_tools()` 后 read_file/web_search/calculate/save_result/download_page 都可被模型调用
- [ ] 重复添加同名工具时给出警告但不崩溃
- [ ] 非 `@tool` 装饰的普通函数也能被正确注册

## 测试建议

- 单元测试：注册工具 → 验证 Agent.tools 列表
- E2E 测试：Agent 注册自定义工具 → 任务中使用该工具 → 验证工具被调用并返回结果
- 边界测试：注册 0 个工具、注册同名工具、注册非 callable 对象

## 分类

**ready-for-agent** — 现有 ToolRuntime 和 @tool 装饰器可直接复用，仅需包装层。
