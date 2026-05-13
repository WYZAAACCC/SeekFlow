# DeepSeek Tool Reliability Kit — PRD

## 背景

DeepSeek 已支持 function calling / tool calling 能力，但 Python 开发者在实际接入时会遇到一系列工程稳定性问题：

1. Python 函数转 DeepSeek tools schema 过程繁琐，类型映射容易出错
2. strict 模式下 schema 不兼容时 API 直接报错，缺乏前置检查手段
3. 模型生成的 tool arguments 可能不是合法 JSON（单引号、尾随逗号、markdown 包裹等）
4. 工具参数类型可能错误（字符串 `"123"` 应为整数 `123`）
5. 工具调用失败时缺少统一的错误格式和处理流程
6. MCP 工具转 DeepSeek tools schema 需要适配层
7. 工具调用全过程难以追踪和调试
8. 缺少轻量级的 DeepSeek 工具调用评测工具来量化可靠性

当前生态中，LangChain / LlamaIndex 等框架提供了完整的 Agent 能力，但对于只想让 DeepSeek 稳定调用工具的开发者来说过于臃肿。Reasonix 作为 DeepSeek 原生终端编程 Agent 解决了另一个问题，但不是开发者构建自己工具调用应用的基础设施。

## 目标

**一句话：让 DeepSeek 工具调用更稳定。**

具体目标：

- 提供 `@tool` 装饰器，自动将 Python 函数转换为 DeepSeek-compatible tools schema
- 在请求发送前检查 schema 的 strict 模式兼容性，提前暴露问题
- 自动修复模型返回的非标准 JSON 参数，降低工具调用失败率
- 对参数进行类型纠正（coercion），容忍模型的小错误
- 统一工具执行流程，标准化错误格式、超时处理、结果截断
- 适配 MCP stdio server，让 DeepSeek 能调用 MCP 生态工具
- 记录完整的工具调用 trace，支持 JSON 导出
- 提供 YAML 驱动的轻量级评测框架，量化工具调用准确率

## 非目标

本项目**不是**：

- 不是 DeepSeek 版 LangChain / LlamaIndex（不做 700+ 集成）
- 不是 DeepSeek 版 Claude Code
- 不是终端编程 Agent（那是 Reasonix 的领域）
- 不是通用多 Provider 框架（专注 DeepSeek）
- 不是聊天前端 / Web Dashboard
- 不是 RAG 知识库系统
- 不提供 TypeScript SDK

本项目**是**：

- DeepSeek 原生 Agent 框架（Agent/Crew/Task/StateGraph）
- 生产级工具调用可靠性层（JSON修复/重试/熔断/缓存/追踪）
- 两个层可独立使用：可靠性核心 11 行代码即可调用工具，Agent 层处理复杂多 Agent 工作流
- 流式 tool calling
- 多轮对话记忆管理
- 工具调用的权限控制 / 审批流

## 用户故事

### 工具定义与 Schema 生成

1. 作为一个 Python 开发者，我希望用 `@tool` 装饰器标记函数，自动生成 DeepSeek tools schema，这样我不需要手写 JSON schema。
2. 作为一个 Python 开发者，我希望支持 `str`、`int`、`float`、`bool`、`list`、`dict`、`Literal`、`Optional` 等常见 Python 类型，覆盖日常工具定义需求。
3. 作为一个 Python 开发者，我希望可以自定义工具名称和描述（`@tool(name=..., description=...)`），不受限于函数名和 docstring。
4. 作为一个 Python 开发者，我希望 Pydantic Model 能自动转换为 object schema，复用自己的数据模型。
5. 作为一个 Python 开发者，我希望通过 `ToolRegistry` 注册、查找、导出工具，支持本地工具和 MCP 工具的混合管理。

### Strict 模式兼容

6. 作为一个使用 DeepSeek strict 模式的开发者，我希望在请求前检查 tools schema 是否兼容，避免 API 直接报错。
7. 作为一个使用 DeepSeek strict 模式的开发者，我希望检查结果能指出具体的不兼容路径和建议修复方案。
8. 作为一个使用 DeepSeek strict 模式的开发者，我希望 strict 检查失败时可以自动降级为非 strict 模式（strict_fallback），并在 trace 中记录降级事件。

### 参数修复

9. 作为一个集成 DeepSeek 的开发者，当模型返回单引号 JSON 时，我希望能自动修复为双引号 JSON。
10. 作为一个集成 DeepSeek 的开发者，当模型返回尾随逗号的 JSON 时，我希望自动去除。
11. 作为一个集成 DeepSeek 的开发者，当模型在 JSON 外包裹 markdown code block 或解释文本时，希望自动提取 JSON 对象。
12. 作为一个集成 DeepSeek 的开发者，当模型输出 Python 的 `True`/`False`/`None` 时，希望自动转为 JSON 的 `true`/`false`/`null`。
13. 作为一个集成 DeepSeek 的开发者，当参数类型不完全匹配时（如字符串 `"123"` 应为整数），希望能按 schema 自动纠正。

### 工具执行

14. 作为一个集成 DeepSeek 的开发者，我希望统一执行本地工具，并自动处理 JSON 解析、参数修复、异常、超时和结果截断。
15. 作为一个集成 DeepSeek 的开发者，当工具返回结果过长时，希望能自动截断并标注，避免 context 溢出。
16. 作为一个集成 DeepSeek 的开发者，当工具不存在时，希望得到清晰的 `ToolNotFoundError` 而非模糊的异常。

### MCP 适配

17. 作为一个想扩展 DeepSeek 工具能力的开发者，我希望能通过 `MCPServerConfig.stdio()` 连接 MCP stdio server，自动发现和调用其工具。
18. 作为一个使用多个 MCP server 的开发者，我希望 MCP 工具自动加上 server namespace 前缀（如 `filesystem.read_file`），避免工具重名冲突。
19. 作为一个集成 MCP 的开发者，我希望 MCP 工具调用失败时有标准化的错误格式。

### Trace 追踪

20. 作为一个调试 DeepSeek 工具调用的开发者，我希望记录每一次请求-响应、工具调用、参数修复和错误事件。
21. 作为一个调试 DeepSeek 工具调用的开发者，我希望 trace 能导出为 JSON 文件，方便人工分析或工具处理。
22. 作为一个调试 DeepSeek 工具调用的开发者，我希望在 trace 中看到每个事件的精确时间戳和耗时。

### Eval 评测

23. 作为一个需要验证 DeepSeek 工具调用稳定性的开发者，我希望用 YAML 定义测试用例，批量运行并计算准确率。
24. 作为一个需要验证 DeepSeek 工具调用稳定性的开发者，我希望评测报告包含工具名准确率、参数准确率、最终回答准确率和平均延迟。
25. 作为一个需要对比不同配置的开发者，我希望评测支持切换 strict 模式、repair 开关等变量，对比结果。

### CLI 与适配

26. 作为一个喜欢命令行的开发者，我希望用 `seekflow eval` 运行评测，用 `seekflow trace view` 查看 trace。
27. 作为一个同时使用 OpenAI SDK 的开发者，我希望能导出 OpenAI-compatible 格式的 tools schema。
28. 作为一个 LangChain / PydanticAI 用户，我希望有最小化的适配器导出工具 schema。

### 安全与边界

29. 作为一个安全意识的开发者，我希望 README 中明确提示 MCP server 可能访问本地文件、网络和系统资源。
30. 作为一个新用户，我希望 README 第一屏就清楚说明项目定位和边界，不与 Agent 框架混淆。

## 核心功能

### 模块一：Tool Schema 生成

- `@tool` 装饰器将 Python 函数转为 `ToolDefinition`
- 支持 `str` / `int` / `float` / `bool` / `list` / `dict` / `Literal` / `Optional` / Pydantic Model 类型映射
- 支持自定义 `name` 和 `description`
- `ToolRegistry` 注册、去重、查找、导出 DeepSeek tools schema
- 区分 local 工具和 MCP 工具

### 模块二：Strict Schema 兼容检查

- 检查 function name 合法性、description 非空、parameters 为 object
- 检查 anyOf / oneOf / allOf、过深嵌套、空 enum 等不兼容项
- 返回 `StrictCheckResult`，含 `ok` 状态和 `issues` 列表（warning / error）
- `strict_fallback=True` 时自动降级并在 trace 中记录

### 模块三：Tool Call Arguments 修复

- JSON 修复（`repair_json_arguments`）：去 markdown code block、提取 JSON 对象、单引号转双引号、去尾随逗号、Python 字面量转 JSON
- 类型纠正（`coerce_arguments`）：按 schema 将字符串转为 integer / number / boolean，单值转数组
- 修复结果包含 `applied_rules` 列表，可追溯每步修复

### 模块四：Tool Executor

- 统一执行本地工具：解析 arguments → repair → coercion → 执行 → 序列化结果 → 截断
- 处理：工具不存在、参数 JSON 错误、类型错误、函数异常、超时、结果不可序列化、结果过长
- 返回 `ToolExecutionResult`（含 `ok`、`error`、`elapsed_ms`、`repaired`、`repair_notes`）

### 模块五：DeepSeek Client

- 基于 `openai` Python SDK 的轻量封装
- 支持 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` 环境变量
- 返回 `ChatResponse`，解析 content、reasoning_content、tool_calls、usage

### 模块六：ToolRuntime（最小 Tool Loop）

- 不是完整 Agent 框架，是最小的 tool calling loop
- 流程：发送 messages → 收到 tool_calls → 执行工具 → 写回结果 → 再次请求 → 直到最终回答或达到 max_steps
- 集成 strict checker、JSON repair、trace recorder、MCP executor
- 返回 `ToolRuntimeResult`（final、messages、tool_results、trace、usage）

### 模块七：MCP stdio 适配

- `MCPServerConfig.stdio()` 配置 MCP server
- 连接 MCP stdio server，发现工具，转为 DeepSeek tools schema
- MCP 工具命名：`{server_name}.{tool_name}`
- `MCPToolExecutor` 执行 MCP tool call，标准化错误

### 模块八：Trace 执行记录

- `TraceEvent` 定义 14 种事件类型（runtime_start、strict_check、model_request、tool_call_result 等）
- `TraceRecorder` 记录事件、`finish()` 结束、`to_json()` / `save()` 导出
- 支持 JSON 导出格式

### 模块九：Eval 评测

- YAML 格式定义 benchmark（cases：input、expected_tools、expected_final_contains）
- `EvalRunner` 批量执行，计算：success_rate、tool_name_accuracy、argument_accuracy、final_contains_accuracy、avg_steps、avg_latency_ms
- CLI：`seekflow eval benchmarks/basic_tools.yaml`

### 模块十：Adapters

- OpenAI-compatible adapter：导出标准 tools schema
- LangChain adapter：最小 schema 导出（不强依赖 LangChain）
- PydanticAI adapter：最小 schema 导出

## 验收标准

1. **本地工具调用可运行**：使用 `@tool` 装饰函数，`ToolRuntime.chat()` 能完成基本 tool calling loop 并返回最终回答
2. **Schema 可导出**：`ToolRegistry.to_deepseek_tools(strict=True)` 返回合法的 DeepSeek tools schema
3. **JSON repair 可用**：`repair_json_arguments("{'city': '杭州'}")` 返回 `ok=true`，`value={"city": "杭州"}`
4. **Trace 可保存**：`result.trace.save("trace.json")` 生成合法的 JSON 文件
5. **Eval 可运行**：`seekflow eval benchmarks/basic_tools.yaml` 输出含 success_rate 的评测报告
6. **MCP 文件系统示例可运行**：连接 `@modelcontextprotocol/server-filesystem`，完成基本文件操作
7. **所有测试通过**：`pytest` 全部通过，覆盖 tool schema、strict checker、json repair、tool executor、trace、eval runner、runtime（mock）
8. **README 边界清晰**：第一屏清楚说明项目定位和与 Reasonix 的区别

## 边界情况

- **工具名冲突**：同一 registry 内工具名必须唯一，注册重名工具应报错
- **MCP 命名空间**：MCP 工具以 `{server_name}.{tool_name}` 命名，避免与本地工具冲突
- **JSON 修复失败**：如果所有修复规则都无法恢复合法 JSON，返回 `ok=false` 并保留原始输入
- **工具不存在**：执行不存在的工具时返回 `ToolExecutionResult(ok=false, error="Tool not found: xxx")`，不抛异常
- **函数执行异常**：工具内部抛出的异常被捕获，返回 `ToolExecutionResult(ok=false, error=...)`,不中断整个 loop
- **结果过长**：超过 `max_result_chars`（默认 12000）自动截断，标注原始长度和保留长度
- **max_steps 耗尽**：达到 max_steps 仍未获得最终回答时，返回 `final="ToolRuntime stopped because max_steps was reached."` 并附带 trace
- **strict 自动降级**：`strict=True` + `strict_fallback=True` 时，如 schema 不兼容则自动降级为非 strict，trace 中记录 `strict_fallback` 事件 — 不静默降级
- **MCP 连接失败**：MCP server 启动失败或通信异常时，抛出 `MCPConnectionError`
- **MCP 工具调用失败**：MCP 工具执行失败时返回标准化的 `ToolExecutionResult`，不抛异常
- **空工具列表**：`ToolRuntime` 无工具时，退化为普通聊天模式
- **Python 版本**：要求 Python 3.10+，低版本安装时 pyproject.toml 应阻止
- **LangChain 未安装**：使用 LangChain adapter 时如果 LangChain 未安装，不应报错，给出提示即可
- **环境变量缺失**：未设置 `DEEPSEEK_API_KEY` 时，客户端初始化应给出清晰错误提示
- **非 JSON 序列化返回值**：工具返回不可 JSON 序列化的对象时，尝试 `str()` 转换，失败则记录错误

## 开发阶段

### Phase 1：项目骨架
- 创建 `pyproject.toml`（含依赖和 CLI 入口）
- 创建 `src/seekflow/` 源码目录结构
- 创建 `tests/` 目录
- 添加 `README.md`、`LICENSE`（MIT）、`.gitignore`
- 配置 pytest、ruff

### Phase 2：基础类型和错误
- 实现 `types.py`：`ToolDefinition`、`ToolCall`、`ToolExecutionResult`、`ChatResponse`、`ToolRuntimeResult`
- 实现 `errors.py`：`SeekFlowError` 及其子类

### Phase 3：工具装饰器和 Schema 生成
- 实现 `tools/decorator.py`：`@tool` 装饰器
- 实现 `tools/schema.py`：Python 类型 → JSON Schema 映射
- 实现 `tools/registry.py`：`ToolRegistry` 注册和导出

### Phase 4：Strict Checker
- 实现 `tools/strict.py`：`check_strict_compatibility()`
- 在 `ToolRuntime` 中集成 strict 检查和 fallback 逻辑

### Phase 5：JSON Repair 和参数 Coercion
- 实现 `repair/json_repair.py`：7 条修复规则
- 实现 `repair/coercion.py`：5 种类型纠正

### Phase 6：Tool Executor
- 实现 `tools/executor.py`：统一工具执行流程

### Phase 7：DeepSeek Client
- 实现 `client.py`：基于 openai SDK 的 DeepSeek API 封装

### Phase 8：Trace
- 实现 `trace/events.py`、`trace/recorder.py`、`trace/exporters.py`

### Phase 9：ToolRuntime
- 实现 `runtime.py`：最小 tool loop，集成所有模块

### Phase 10：MCP stdio Adapter
- 实现 `mcp/config.py`、`mcp/client.py`、`mcp/adapter.py`、`mcp/executor.py`

### Phase 11：Eval
- 实现 `evals/loader.py`、`evals/runner.py`、`evals/metrics.py`、`evals/report.py`

### Phase 12：CLI
- 实现 `cli.py`：`seekflow eval`、`seekflow trace view`

### Phase 13：Examples 和 Tests
- 实现 5 个 example 文件
- 实现 8 个测试文件，确保 `pytest` 全部通过

## 技术决策

- **语言**：Python 3.10+，利用 `|` 联合类型语法
- **API 层**：基于 `openai` SDK 而非自建 HTTP 客户端，确保与 DeepSeek API 的兼容性
- **数据模型**：Pydantic v2 作为类型基础，所有公共数据类使用 `BaseModel`
- **架构模式**：遵循工程文档中定义的精简模块划分，每个模块有清晰边界和可测试接口
- **命名**：运行时核心类名为 `ToolRuntime` 而非 `Agent`，刻意与 Agent 框架保持距离
- **MCP 传输**：第一版仅支持 stdio，因为这是最通用且无外部依赖的方式
- **Trace 格式**：第一版支持 JSON，JSONL 预留接口
- **不静默降级**：strict fallback 必须在 trace 中记录，确保开发者可感知
- **CLI 框架**：使用 Typer + Rich，提供友好的终端体验
- **评测格式**：YAML 作为基准格式，平衡可读性和结构化

## 测试策略

- **测试原则**：只测试外部行为，不测试实现细节
- **模块级测试**：每个核心模块都有独立测试文件，使用 mock 隔离外部依赖
- **Runtime 测试**：用 mock client 模拟 DeepSeek 响应，验证 tool loop 逻辑，不真实请求 API
- **Eval 测试**：测试 YAML 加载、单 case 执行、各指标计算、报告输出
- **测试框架**：pytest + pytest-asyncio
- **代码质量**：ruff 做 linting，mypy 做类型检查
