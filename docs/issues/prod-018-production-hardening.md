# prod-018: 生产级硬化 — 从"聪明但业余的库"到"可信任的基础设施"

**状态**: 待开始
**优先级**: P0
**父级**: 无（独立审查驱动）

---

## 问题陈述

一名资深开发者在初次接触 SeekFlow 时，会在 5 分钟内发现以下问题：

1. `import seekflow` 之后什么都做不了 — 顶层 `__init__.py` 只有一个 docstring，公开 API 是空白
2. 需要用 `from seekflow.tools.decorator import tool` 这种五层深的路径来导入核心功能
3. `build/` 和 `dist/` 目录被提交，包含一份过时的源代码副本（缺失 `agent/`、`async_runtime.py` 等十几个新模块）
4. README 上的基准表格声称 100% 成功率，但没有任何置信区间、样本量或测试方法描述——有经验的工程师会直接判定为造假
5. `benchmarks/agents_comparison/` 里有 11 个不同名字的"最终对决"脚本（`final_showdown.py`、`no_excuses_showdown.py`、`truly_fair_comparison.py`...），看起来更像是焦虑驱动的反复验证而非严谨的基准测试
6. README 第一行说"not an agent framework"，但代码里有 `DeepSeekAgent`、`Crew`、`Task`、`StateGraph`、`Checkpoint`、`Memory`、`EventBus`——自相矛盾的定位
7. MCP 子系统有三套独立实现：`runtime.py` 内嵌一套、`mcp/executor.py` 一套（从未被调用）、`compat/mcp.py` 一套薄包装
8. `ToolRuntime` 和 `AsyncToolRuntime` 之间零代码共享——约 250 行完全重复的上下文管理、消息修复、thinking mode 应用逻辑
9. `Agent.run()` 用递归调用自身来实现超时控制——`execution_timeout=None` 参数的唯一目的是防止无限递归
10. 整个项目没有 Git 版本控制

这不是功能缺失问题，而是**工程可信度**问题。任何一个严谨的团队在引入这个库之前，都会因为这些信号而犹豫。

---

## 解决方案

四个阶段，17 个行动项，将框架从"原型质量"提升到"生产基础设施"标准。

### 阶段 0：船体补漏（7 项，阻断生产上线）
修复所有让外部开发者看一眼就丧失信任的问题。

### 阶段 1：架构手术（4 项，阻断生产扩展）
消灭重复代码、统一分歧实现、消除认知失调。

### 阶段 2：类型与测试（4 项，影响长期维护成本）
建立类型安全和安全测试基线。

### 阶段 3：API 设计回顾（2 项，影响用户体验）
解决类型不一致和命名混乱。

---

## 实现决策

### 决策 1：顶层公开 API 设计

`seekflow/__init__.py` 应暴露三个层级的 API：

**核心层**（所有用户都需要）：
- `tool` — 装饰器
- `ToolRuntime` — 同步运行时
- `AsyncToolRuntime` — 异步运行时
- `ToolRegistry` — 工具注册表
- `ToolExecutor` — 工具执行器
- `DeepSeekClient` — API 客户端
- 核心类型：`ToolDefinition`、`ToolCall`、`ToolExecutionResult`、`ChatResponse`、`ToolRuntimeResult`、`StreamEvent`
- 核心错误：`SeekFlowError`、`DeepSeekAPIError`、`AuthenticationError`、`RateLimitError`、`InsufficientBalanceError`

**Agent 层**（构建 Agent 的用户）：
- `DeepSeekAgent`、`AgentResult`
- `Task`、`TaskResult`
- `Crew`、`CrewResult`、`Process`

**高级层**（需要深度控制的用户）：
- `RetryPolicy`、`CircuitBreaker`
- `CostTracker`
- `TraceRecorder`
- `repair_json_arguments`、`JsonRepairResult`、`coerce_arguments`
- `check_consistency`
- `count_tokens`、`count_text`

用户的目标体验：
```python
# 之前
from seekflow.tools.decorator import tool
from seekflow.runtime import ToolRuntime

# 之后
from seekflow import tool, ToolRuntime
```

### 决策 2：MCP 架构统一

目标状态：**单一 MCP 实现，位于 `mcp/` package**。

```
mcp/
├── config.py          # MCPServerConfig（不变）
├── adapter.py         # mcp_tool_to_deepseek_tool（不变）
└── executor.py        # MCPToolExecutor（扩展）
    ├── connect()        # 新增：连接所有服务器，保持会话存活
    ├── disconnect()     # 新增：关闭所有会话
    ├── discover_all()   # 新增：发现工具并注册到 ToolRegistry
    ├── execute()        # 已有：执行单个工具调用（async）
    └── execute_sync()   # 已有：同步包装
```

`ToolRuntime._connect_mcp_servers()` 变为 5 行委托：
```python
def _connect_mcp_servers(self) -> None:
    if self._mcp_connected or not self._mcp_servers:
        return
    self._mcp_executor = MCPToolExecutor(self._mcp_servers)
    self._mcp_executor.discover_and_register(self._registry)
    self._mcp_connected = True
```

删除文件：
- `compat/mcp.py` — 它只是 `mcp/config.py` 的别名包装

### 决策 3：Runtime 公共逻辑提取

创建 `_runtime_base.py` 作为 Mixin 类，承载以下共享方法：

- `_estimate_tokens(messages)` — 静态方法
- `_trim_messages(messages)` — 上下文窗口管理
- `_repair_message_order(messages)` — 静态方法
- `_apply_strict_check(tools_schema, recorder)` — strict 检查
- `_process_files(messages, files)` — 文件嵌入
- `_build_assistant_msg(content, tool_calls, reasoning)` — 消息构建
- `_build_tool_result_msgs(tool_calls, results)` — 工具结果消息构建

两个 Runtime 类继承此 Mixin，仅保留各自特有的逻辑：
- `ToolRuntime`：`_make_client()`、`chat()`、`chat_stream()`、`chat_batch()`
- `AsyncToolRuntime`：`_retry_request()`、`chat_async()`、`chat_stream_async()`

### 决策 4：消除 `Agent.run()` 递归超时 hack

**当前实现**（反模式）：
```python
def _run():
    result_container.append(self.run(task, execution_timeout=None))
    # execution_timeout=None 被用来阻止无限递归
```

**目标实现**（标准模式）：
```python
def run(self, task, *, execution_timeout=None, **kwargs):
    if execution_timeout and execution_timeout > 0:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self._run_impl, task, **kwargs)
            return future.result(timeout=execution_timeout)
    return self._run_impl(task, **kwargs)

def _run_impl(self, task, **kwargs):
    # 原 run() 的全部逻辑
```

### 决策 5：类型安全基线

1. 所有延迟初始化的属性声明为 `Optional[X]`，如 `self._client: DeepSeekClient | None = None`
2. `ToolCall.arguments` 统一为 `dict`（在 `DeepSeekClient.chat()` 边界处做 `json.loads()`）
3. 内部类型 `StreamChunk` 重命名为 `_StreamChunk`（它不应出现在公开 API 中）
4. `mypy --strict` 加入 CI 检查

### 决策 6：框架定位修正

README 和 `__init__.py` 的 docstring 从"not an agent framework"改为：

> DeepSeek-native agent framework with a production-grade reliability core.
>
> Two layers, one library:
> - **Reliability core** — JSON repair, retry, circuit breaker, cache, trace
> - **Agent layer** — Agent, Crew, Task, StateGraph, Checkpoint, Memory

`docs/PRD.md` 的非目标部分需同步更新。

### 决策 7：基准测试呈现标准

- 所有百分比必须附带 ± 置信区间
- 所有指标必须附带样本量 n
- 所有对比必须注明每个框架测试了相同还是不同的场景子集
- 删除 100% 声明（给 API 变更留出容错空间）
- 单一基准测试文件替代 11 个变体

---

## 用户故事

1. 作为一名 Python 开发者，我希望用 `from seekflow import tool, ToolRuntime` 一行导入所有核心功能，无需记忆深层模块路径
2. 作为一名框架评估者，我希望 README 中的基准数据附带置信区间和样本量，以便我相信这些数字是真实的
3. 作为一名生产环境运维者，我希望框架的 README 描述和实际代码一致——如果代码里有 Agent/Crew/Task，README 里不应该说"not an agent framework"
4. 作为一名贡献者，我希望 MCP 只有一套实现，这样我不需要在三套不同的代码库之间选择从哪里开始修改
5. 作为一名异步应用开发者，我希望 `AsyncToolRuntime` 和 `ToolRuntime` 的功能完全对等，不存在同步能用但异步不能用的功能
6. 作为一名安全审计者，我希望 `calculate()` 函数有安全测试来验证它对代码注入攻击的防御能力
7. 作为一名类型检查器用户，我希望延迟初始化的属性使用 `Optional` 标注，而不是裸 `None` 赋值后直接使用
8. 作为一名 CI/CD 维护者，我希望 `build/` 和 `dist/` 不在版本控制中，源码目录和构建产物完全分离
9. 作为一名新用户，我希望 examples/ 中的示例可以在安装库后直接运行，使用顶层导入而非深层路径
10. 作为一名长期维护者，我希望 Git 历史能追溯每一次修改，没有版本控制的代码库是不可维护的
11. 作为一名工具开发者，我希望 `ToolCall.arguments` 始终是 `dict` 类型，不需要在每一层都做 `isinstance(arguments, str)` 检查
12. 作为一名 Agent 构建者，我希望 `Agent.run()` 的超时机制是标准的线程池实现，而非递归调用 hack
13. 作为一名框架用户，我希望流式重试不会在传输开始前缓冲整个响应——正常路径应保持实时流式传输

---

## 测试决策

### 测试原则
- 仅测试外部行为，不测试实现细节
- 每个安全相关变更必须有对应的攻击向量测试
- 类型测试由 mypy --strict 提供（非运行时测试）

### 测试清单
- `tests/test_json_repair.py` 扩展：嵌套引号、多代码块、空输入、10KB+ 输入、函数调用语法中的嵌套括号
- `tests/test_calculate_safety.py` 新建：10 种攻击向量（`__import__`、`__subclasses__`、推导式、lambda 等）
- `tests/test_public_api.py` 新建：验证顶层 `__init__.py` 暴露了所有预期符号
- `tests/test_mcp_unified.py` 新建：验证 MCP 连接、发现、执行、清理的完整生命周期
- `tests/test_async_parity.py` 新建：验证 `AsyncToolRuntime` 具备与 `ToolRuntime` 对等的功能集

### 测试先例
- 现有 `tests/test_json_repair.py` 使用参数化 fixture，新测试遵循相同模式
- 现有 `tests/test_strict_checker.py` 验证 checker 结果，攻击向量测试遵循相同断言风格
- 现有 `tests/test_tool_registry.py` 已覆盖注册和查重，新测试扩展覆盖 unregister 和 get_by_source

---

## 文件变更清单

### 阶段 0 — 船体补漏

| 文件 | 操作 | 说明 |
|------|------|------|
| 无（项目根目录） | 执行 `git init` | 初始化版本控制 |
| `.gitignore` | 确认 `build/` `dist/` `*.egg-info/` 在其中 | 已存在，无需修改 |
| `build/` `dist/` `*.egg-info/` | 删除 | 构建产物不应入库 |
| `src/seekflow/__init__.py` | 重写 | 暴露三层公开 API（核心/Agent/高级） |
| `src/seekflow/adapters/__init__.py` | 重写 | 暴露 `export_langchain_tool_schemas`、`to_openai_tools` |
| `src/seekflow/compat/__init__.py` | 重写 | 暴露 bridge 函数 |
| `src/seekflow/agent/__init__.py` | 扩写 | 补上 `Crew`、`Task`、`StateGraph`、`AgentMemory` |
| `src/seekflow/adapters/pydantic_ai.py` | 删除 | 死模块，从未被使用或测试 |
| `benchmarks/agents_comparison/` | 精简 | 11 个文件 → 1 个 `compare.py`，其余删除 |
| `README.md` | 重写对比表格 | 加置信区间、样本量、方法描述 |
| `docs/PRD.md` | 更新非目标 | 承认 Agent 框架身份 |
| `examples/` | 更新导入 | 改用顶层导入 |

### 阶段 1 — 架构手术

| 修改位置 | 操作 | 说明 |
|----------|------|------|
| `mcp/executor.py` | 扩展 | 添加 `connect()`、`disconnect()`、`discover_and_register()` |
| `runtime.py` | 精简 | `_connect_mcp_servers()` 改为委托 `MCPToolExecutor`；删除 ~100 行 MCP 连接代码 |
| `compat/mcp.py` | 删除 | 冗余包装 |
| `_runtime_base.py` | 新建 | Mixin 类承载共享的上下文管理和消息构建逻辑 |
| `runtime.py` | 继承 Mixin | 删除 ~125 行重复代码 |
| `async_runtime.py` | 继承 Mixin | 删除 ~125 行重复代码 |
| `agent/agent.py` | 重构 | `run()` → `_run_impl()` + `ThreadPoolExecutor` 超时 |

### 阶段 2 — 类型与测试

| 文件 | 操作 |
|------|------|
| `pyproject.toml` | 添加 `[tool.mypy]` strict 配置 |
| 全模块 | `Optional[X]` 标注延迟初始化属性 |
| `types.py` | `ToolCall.arguments` → 统一为 `dict` |
| `client.py` | `chat()` 边界处做 json.loads() |
| `tests/test_json_repair.py` | 扩展 6 个场景 |
| `tests/test_calculate_safety.py` | 新建：10 个攻击向量测试 |
| `tests/test_public_api.py` | 新建：公开 API 符号验证 |
| `tests/test_mcp_unified.py` | 新建：MCP 生命周期测试 |
| `tests/test_async_parity.py` | 新建：异步功能对等测试 |

### 阶段 3 — API 设计

| 修改位置 | 操作 | 说明 |
|----------|------|------|
| `types.py` | 定义 `ToolChoice` 类型别名 | 替代 `str \| dict \| None` |
| `types.py` | 重命名 `StreamChunk` → `_StreamChunk` | 内部类型不暴露 |

---

## 非目标

- 不重写 JSON 修复管线（这是框架最牢固的部分）
- 不新增第三方依赖
- 不改变 DeepSeek API 交互方式
- 不添加 Web UI / Dashboard
- 不添加新的 Agent 模式（ReAct/Plan-Solve/Reflect 已足够）
- 不迁移到不同的构建系统
- 不添加 Docker / 容器化

---

## 扩展笔记

### 工期估算
- 阶段 0：2 小时（机械性修改，无逻辑变更）
- 阶段 1：8 小时（涉及重构和接口设计）
- 阶段 2：16 小时（大量测试编写 + mypy 修复）
- 阶段 3：4 小时（类型系统微调）
- **总计：约 4 个工作日（一个资深工程师）**

### 风险
- 阶段 0 无风险——纯增量修改
- 阶段 1 中风险——重构 MCP 和 Runtime 继承关系，需在干净的 Git 历史上操作以支持逐 commit revert
- 阶段 2 低风险——添加测试和类型标注，不改变运行时行为
- 阶段 3 低风险——类型别名和重命名，编译器级安全

### 依赖
- 阶段 0 必须先完成（Git 初始化是所有后续操作的 pre-requisite）
- 阶段 1 必须在阶段 0 后执行（重构需要版本控制保护）
- 阶段 2 和 3 可并行

### 分类: ready-for-agent
