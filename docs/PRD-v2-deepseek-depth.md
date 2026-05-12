# PRD: DeepSeekToolkit v2 — 最深入、最完整的 DeepSeek 专用库

**版本**: 1.0  
**日期**: 2026-05-09  
**状态**: 待评审  
**作者**: DeepSeekToolkit Team

---

## 1. 背景

DeepSeekToolkit 已经建立了显著的技术护城河：JSON Repair 管道、Thinking 模式透传、MCP 协议适配、文件附件嵌入、Eval 框架——这些都是市面上 12+ 竞争框架中**没有任何一个**同时具备的能力。当前 274 个测试全部通过，3702 行代码，在 28 项 DeepSeek 特性上覆盖率达到 78.6%（竞争对手最高仅 30%）。

然而，当前版本存在三个结构性问题：

1. **生产环境盲区**：缺少余额查询、速率限制处理、完整错误分类等生产必备能力，直接部署会因 402/429 错误而崩溃。
2. **DeepSeek 特有 API 未封装**：FIM 补全（`/beta/completions`）、Anthropic 兼容端点（`/anthropic/v1/messages`）等 DeepSeek 独有功能未提供 SDK 级封装，用户需自行拼接 HTTP 请求。
3. **开发生态缺失**：无 async 支持、无 prompt cache 优化、无模型路由——这些是现代 LLM 应用的标配能力，缺失会直接限制库的采用场景。

本 PRD 定义了将这些短板逐一补齐的完整计划，目标是将 DeepSeekToolkit 从"最好的 DeepSeek 适配库"升级为"**使用 DeepSeek API 的唯一正确方式**"。

## 2. 目标

### 2.1 核心目标

- **P0 — 生产可用**: 补齐余额查询、速率限制处理、完整错误分类，使库可安全用于生产环境。
- **P1 — 深度特性**: 封装 FIM 补全、Anthropic 兼容端点、Prompt Cache 优化、Thinking Mode 一等参数、模型路由、1M 上下文管理。
- **P2 — 开发者体验**: 提供 async 支持、会话管理、成本追踪、结构化输出。
- **P3 — 生态补齐**: 并发工具调用、Token 计数、多 Provider 降级。

### 2.2 成功指标

| 指标 | 当前 | 目标 |
|------|------|------|
| DeepSeek 特性覆盖率（28 项） | 78.6% (22/28) | 96%+ (27/28) |
| 测试数量 | 274 | 400+ |
| 生产级错误处理 | 仅重试 | 全错误码分类 + 自适应退避 |
| 外部框架集成 | LangChain + MCP | + PydanticAI + Anthropic SDK 迁移 |
| Async 支持 | 无 | 完整 asyncio |
| 源文件数 | 36 | 50+ |

## 3. 非目标

以下内容**不在**本 PRD 范围内：

1. **新的模型 provider 适配**：不做 OpenAI/Gemini/Claude 的通用适配——本库坚持 DeepSeek-first 定位。多 Provider 降级仅限 DeepSeek 兼容 API（硅基流动、Ollama 等）。
2. **UI/可视化工具**：不做 Web Dashboard、Grafana 面板等可视化组件。
3. **自建推理服务**：不做模型部署、推理加速、量化等基础设施。
4. **Fine-tuning API**：DeepSeek 不支持微调端点，无需适配。
5. **Batch API**：DeepSeek 的 `/v1/batches` 端点返回 404，经实测确认不可用。保留现有代码但标记为"不可用"，等待官方支持。
6. **多模态（图片理解）**：DeepSeek V4 当前不支持图片输入，不做冗余封装。

## 4. 用户故事

### P0 — 生产可用性

1. 作为一名运维工程师，我希望**查询账户余额**，以便在余额不足时收到告警，避免线上服务中断。
2. 作为一名后端开发者，我希望库能**自动处理 429 限流响应**（解析 `X-RateLimit-Remaining` 头并做自适应退避），而不是收到异常后手动排查。
3. 作为一名 API 消费者，我希望**402/429/503 等错误被精确分类**为 `InsufficientBalanceError`、`RateLimitError`、`ServiceUnavailableError`，以便我能针对不同错误类型编写不同的降级逻辑。
4. 作为一名 IDE 插件开发者，我希望调用**FIM（Fill-in-the-Middle）补全 API**，以便在代码编辑器中提供智能补全功能。
5. 作为一名技术负责人，我希望所有**API 调用在生产级错误面前不会静默失败**，每个错误都有明确的类型和可操作的建议。

### P1 — DeepSeek 深度特性

6. 作为一名 AI 应用开发者，我希望通过 `thinking_mode="enabled"` 这样的**一等参数**开启深度思考模式，而不是手动拼接 `extra_body={"thinking": {"type": "enabled"}}`。
7. 作为一名成本敏感的开发者，我希望库能**自动利用 DeepSeek Prompt Cache**（≥1024 token 前缀自动缓存），将重复输入 token 的成本降低 90%。
8. 作为一名长文档处理者，我希望库能**感知 1M token 上下文窗口**，并自动对超长输入进行智能分段和摘要。
9. 作为一名 Anthropic SDK 用户，我希望通过**修改 base_url 就能将现有应用迁移到 DeepSeek**，利用 `POST /anthropic/v1/messages` 兼容端点，零代码改动完成迁移。
10. 作为一名后端架构师，我希望配置**模型路由策略**——简单任务自动使用 `deepseek-v4-flash`（¥0.14/M），复杂任务使用 `deepseek-v4-pro`（¥1.74/M），在质量和成本之间取得平衡。
11. 作为一名需要深度推理的应用开发者，我希望库能**在多轮对话中自动透传 `reasoning_content`**，避免因漏传导致 API 返回 400 错误。

### P2 — 开发者体验

12. 作为一名 FastAPI/Web 应用开发者，我希望使用**完整的 async API**（`await runtime.chat_async(...)`），以便在异步 Web 框架中高效并发处理请求。
13. 作为一名聊天应用开发者，我希望有**内置的会话管理**（消息历史、自动摘要、上下文压缩），而不是手动维护 messages 列表。
14. 作为一名财务管理者，我希望有**实时的成本追踪**——每次 API 调用后自动计算并累计 token 消耗和费用，支持按会话/按工具/按模型维度查看。
15. 作为一名数据提取应用开发者，我希望使用 `response_format={"type": "json_object"}` 的**结构化输出**功能，确保模型返回合法 JSON，无需再做 JSON repair。
16. 作为一名并发应用开发者，我希望库能**正确处理一次返回多个 tool_calls 的情况**，并行执行这些工具调用而不是串行执行。

### P3 — 生态补齐

17. 作为一名应用开发者，我希望有内置的**Token 计数工具**，在发送请求前预估输入 token 数，以控制上下文预算。
18. 作为一名 DevOps 工程师，我希望配置**多 Provider 降级链**：DeepSeek API → 硅基流动 → Ollama 本地模型，在一个 provider 不可用时自动切换到下一个。
19. 作为一名框架作者，我希望库提供**标准化的 metrics 接口**（token 消耗、延迟、成功率），以便接入 Prometheus/OpenTelemetry 等可观测性平台。

## 5. 核心功能

### 5.1 P0 模块

#### 5.1.1 余额查询 (`deepseek_toolkit.balance`)

- 接口：`get_balance(api_key=None) -> BalanceInfo`
- 返回：总余额、已用额度、货币单位、查询时间
- 调用 `GET https://api.deepseek.com/user/balance`
- 缓存：300 秒 TTL（余额不会秒级变化）

#### 5.1.2 FIM 补全 (`deepseek_toolkit.fim`)

- 接口：`fim_complete(prefix, suffix, *, model, **kwargs) -> FIMResponse`
- 使用 beta 端点：`POST https://api.deepseek.com/beta/completions`
- 支持 streaming：`fim_complete_stream(...) -> Iterator[FIMChunk]`
- 兼容 Anthropic FIM 格式，降低迁移成本

#### 5.1.3 错误分类 (`deepseek_toolkit.errors`)

- 将原始 OpenAI SDK 异常映射为 DeepSeek 特定错误类型：
  - `InsufficientBalanceError`（402）
  - `RateLimitError`（429，含 `remaining`/`reset` 字段）
  - `ServiceUnavailableError`（503）
  - `AuthenticationError`（401）
  - `ContextLengthExceededError`（400 + context 超限）
- 每个错误类型携带可操作的 `suggestion` 消息

#### 5.1.4 速率限制感知 (`deepseek_toolkit.retry`)

- 解析 `X-RateLimit-Remaining`、`X-RateLimit-Reset` 响应头
- 自适应退避：接近限流阈值时主动减速，而非被动等 429
- 与现有 `RetryExecutor` 的指数退避策略整合

### 5.2 P1 模块

#### 5.2.1 Thinking Mode 一等参数 (`deepseek_toolkit.runtime`)

- `chat(..., thinking_mode: Literal["disabled", "enabled", "max"])`
- 自动映射为 `extra_body={"thinking": {"type": ...}}`
- 自动处理 `reasoning_content` 透传

#### 5.2.2 Prompt Cache 优化 (`deepseek_toolkit.cache`)

- 自动检测可缓存前缀（≥1024 token 的 system message + 固定 prompt）
- 前缀对齐：确保后续请求的 system message 保持一致，最大化缓存命中
- 成本统计中区分 cached/uncached token

#### 5.2.3 1M 上下文管理 (`deepseek_toolkit.context`)

- 上下文预算估算（token 计数）
- 自动摘要策略：当历史消息超过阈值时触发压缩
- 滑动窗口 + 关键消息保留（system prompt、最近的 tool results）

#### 5.2.4 Anthropic 兼容端点 (`deepseek_toolkit.adapters.anthropic_compat`)

- 提供 `DeepSeekAnthropicClient`，实现 Anthropic Messages API 接口
- 接受 Anthropic SDK 格式的 `messages`，内部转换为 DeepSeek 格式
- 支持 Anthropic 风格的 tool_use/tool_result

#### 5.2.5 模型路由 (`deepseek_toolkit.router`)

- 接口：`ModelRouter.route(task_complexity: str) -> str`
- 预定义策略：
  - `"auto"` — 基于 task 关键词自动选择 Flash/Pro
  - `"cost_optimized"` — 始终 Flash，复杂场景才升级
  - `"quality_optimized"` — 始终 Pro
- 支持自定义路由规则

### 5.3 P2 模块

#### 5.3.1 Async 支持 (`deepseek_toolkit.async_runtime`)

- `AsyncToolRuntime` — `ToolRuntime` 的 async 镜像
- 接口：`await runtime.chat_async(...)`, `await runtime.chat_stream_async(...)`
- 底层使用 `openai.AsyncOpenAI`
- 所有 tool call 也支持 async（检测函数签名决定 sync/async 调用）

#### 5.3.2 会话管理 (`deepseek_toolkit.session`)

- `Session` 类：封装消息历史、配置、统计
- 自动摘要：当历史消息超过 token 预算时触发
- 持久化：可选保存/恢复会话到 JSON 文件
- `session.metrics` — 当前会话的 token/成本统计

#### 5.3.3 成本追踪 (`deepseek_toolkit.cost`)

- `CostTracker`：记录每次 API 调用的 token 消耗和费用
- 累计统计：按 session / 按 tool / 按 model 维度
- 实时回调：`on_cost_update(callback)`

#### 5.3.4 结构化输出 (`deepseek_toolkit.structured`)

- 封装 `response_format={"type": "json_object"}`
- Type hints 集成：`def extract() -> MyModel` 自动生成 JSON Schema
- 与 Pydantic 深度整合

### 5.4 P3 模块

#### 5.4.1 并行工具调用 (`deepseek_toolkit.tools.executor`)

- 当 LLM 返回多个 `tool_calls` 时，异步并行执行
- 可配置最大并行数

#### 5.4.2 Token 计数 (`deepseek_toolkit.token_counter`)

- 使用 `tiktoken` 库进行精确计数
- 接口：`count_tokens(messages, model) -> int`

#### 5.4.3 多 Provider 降级 (`deepseek_toolkit.fallback`)

- `FallbackChain`: 有序 provider 列表，遇错自动切换到下一个
- 健康检查：定期探测 provider 可用性
- 配置：YAML/JSON 定义降级链

## 6. 验收标准

### 6.1 测试原则

- **只测试外部行为**，不测试实现细节
- 每个模块必须有独立的单元测试
- 所有对外暴露的接口必须有集成测试
- 错误路径必须覆盖（Mock 异常响应）
- 参考现有测试风格：[tests/test_files.py](../tests/test_files.py)、[tests/test_chat_batch.py](../tests/test_chat_batch.py)

### 6.2 每模块验收条件

| 模块 | 验收条件 |
|------|----------|
| Balance | `get_balance()` 返回正确结构；401 抛出认证错误；网络超时重试 |
| FIM | `fim_complete()` 返回补全内容；streaming 版本逐 token 输出；空前后缀不崩溃 |
| 错误分类 | 402→`InsufficientBalanceError`；429→`RateLimitError`（含 remaining/reset）；未知错误不误分类 |
| 速率限制 | Mock 429 响应后自动等待 retry-after 时间；接近限流阈值时日志告警 |
| Thinking Mode | `thinking_mode="enabled"` 等价于 `extra_body={"thinking":{"type":"enabled"}}`；reasoning_content 自动透传 |
| Prompt Cache | 连续两次相同 system message 的请求，第二次 cost 显示 cached token；无副作用影响正常请求 |
| 1M 上下文 | 超长消息自动触发摘要；摘要后仍保留 system prompt；token 不超预算 |
| Anthropic 兼容 | Anthropic SDK 格式 messages 正确转换为 DeepSeek 格式；tool use 循环正常工作 |
| 模型路由 | `"auto"` 策略对简单任务选 Flash；对推理任务选 Pro；可自定义规则 |
| Async | `chat_async()` 返回结果与同步版一致；与 asyncio 生态兼容 |
| 会话管理 | 多轮对话正确追踪历史；摘要不丢失关键信息；session.save/load 往返无损 |
| 成本追踪 | Token 消耗实时累计；费用与 DeepSeek 官方定价一致；按维度统计准确 |
| 结构化输出 | `response_format=json_object` 正确传递；返回内容为合法 JSON |
| 并行工具 | 多个 tool_calls 并行执行时间 < 串行总和的 1.5x；错误不阻塞其他工具 |
| Token 计数 | `count_tokens()` 结果与 API 返回的 usage 误差 < 5% |
| 多 Provider | 主 provider 不可用时自动切换；恢复后自动切回；日志记录每次切换 |

### 6.3 全局验收

- 所有现有 274 个测试继续保持通过
- 每个新模块至少贡献 8 个新测试（总计新增 ≥128 测试，达 400+）
- 真实 API 集成测试全部通过（参考 [examples/07_real_api_test.py](../examples/07_real_api_test.py) 模式）

## 7. 边界情况

### 7.1 余额查询

- **API Key 无效**：返回 `AuthenticationError`，而非泛化异常
- **网络超时**：使用 `RetryExecutor` 重试 3 次
- **响应格式变化**：DeepSeek 可能修改 balance 响应结构，需做 schema 兼容检测

### 7.2 FIM 补全

- **空 prefix + 空 suffix**：等同于普通补全
- **极长上下文**：prefix + suffix 超过模型上下文窗口时截断并告警
- **Beta 端点稳定性**：beta API 可能随时变更，需保持与最新 API 文档同步

### 7.3 速率限制

- **`X-RateLimit-Remaining: 0`**：立即停止发送，等待 `X-RateLimit-Reset` 指定的时间
- **响应头缺失**：如果 DeepSeek 未返回限流头（尚未正式发布），退回到盲重试
- **多进程竞争**：多个进程共享同一 API Key 时，各自的速率感知可能不同步

### 7.4 Prompt Cache

- **前缀不够 1024 token**：不尝试缓存（DeepSeek 的最小缓存阈值）
- **System message 变化**：一旦 system message 改变，缓存失效——需要文档明确告知用户
- **跨模型缓存**：不同 model 的缓存不共享

### 7.5 1M 上下文

- **极短消息不需要摘要**：只在超过 token 预算时才触发
- **Tool result 很大的场景**：大型 tool result 可能是关键数据，压缩策略需慎重
- **Thinking content 占用**：`reasoning_content` 也计入上下文，计算预算时需包含

### 7.6 Anthropic 兼容端点

- **Content block 格式差异**：Anthropic 用 `content: [TextBlock, ToolUseBlock]`，DeepSeek 用 `content: str`——转换必须零信息丢失
- **Streaming 差异**：Anthropic SSE 事件格式与 DeepSeek 不同，需完整模拟
- **图片 content block**：DeepSeek V4 不支持图片输入，Anthropic 的 `ImageBlockSource` 需报错

### 7.7 Async 支持

- **同步工具在 async 上下文中**：需检测工具函数是 sync 还是 async，sync 工具在 async 上下文中用 `run_in_executor` 包装
- **Streaming in async**：`AsyncIterator` 的取消和清理要正确处理
- **事件循环冲突**：用户可能在已有事件循环的 Jupyter notebook 中使用

### 7.8 模型路由

- **路由决策的延迟**：路由本身不应增加显著延迟（< 100ms）
- **任务复杂度判断的准确率**：基于关键词的简单策略可能误判，需提供人工覆盖接口
- **Single request 的混合任务**：一个请求中可能同时有简单和复杂的子任务，需决定整体路由策略

### 7.9 多 Provider 降级

- **部分 Provider 不可用**：健康检查失败时标记为不可用，定时探测恢复
- **API Key 管理**：不同 provider 有不同的 API Key，需配置管理
- **Provider 行为差异**：不同 provider 的 tool calling 格式可能不同，需适配

## 8. 开发阶段

### Phase 0 — 基础设施（预计 1-2 天）

**目标**：为后续开发奠定基础，无破坏性变更。

- [ ] 错误分类体系重构（`errors.py` 扩展）
- [ ] 速率限制感知（`retry.py` 增强）
- [ ] 新增错误类型：`InsufficientBalanceError`, `RateLimitError`, `ContextLengthExceededError`

**交付物**：`errors.py` 重写，`retry.py` 增强，新增 ≥24 测试

### Phase 1 — DeepSeek 核心 API（预计 2-3 天）

**目标**：封装 DeepSeek 独有的 API 端点，建立 SDK 级封装。

- [ ] 余额查询 `balance.py`（最少代码量，最高价值）
- [ ] FIM 补全 `fim.py`（DeepSeek 独有 beta 端点）
- [ ] Thinking Mode 一等参数（`runtime.py` 接口升级）

**交付物**：3 个新模块，≥24 测试，真实 API 验证

### Phase 2 — 生产级可靠性（预计 2-3 天）

**目标**：确保库在生产环境中安全运行。

- [ ] Prompt Cache 优化 `cache.py`
- [ ] 1M 上下文管理 `context.py`
- [ ] Anthropic 兼容端点 `adapters/anthropic_compat.py`

**交付物**：3 个新模块，≥32 测试

### Phase 3 — 开发者体验（预计 2-3 天）

**目标**：补齐现代 LLM 库的标配能力。

- [ ] Async 支持 `async_runtime.py`
- [ ] 会话管理 `session.py`
- [ ] 成本追踪 `cost.py`
- [ ] 结构化输出 `structured.py`

**交付物**：4 个新模块，≥32 测试

### Phase 4 — 生态补齐（预计 1-2 天）

**目标**：扩展库的适用场景和生态集成。

- [ ] 并行工具调用增强（`tools/executor.py`）
- [ ] Token 计数 `token_counter.py`
- [ ] 多 Provider 降级 `fallback.py`

**交付物**：3 个新模块，≥24 测试

### 里程碑总结

| Phase | 时间 | 新增模块 | 新增测试 | 累计测试 |
|-------|------|----------|----------|----------|
| 0 — 基础设施 | 1-2 天 | 0（重构） | 24 | 298 |
| 1 — 核心 API | 2-3 天 | 3 | 24 | 322 |
| 2 — 生产可靠性 | 2-3 天 | 3 | 32 | 354 |
| 3 — 开发者体验 | 2-3 天 | 4 | 32 | 386 |
| 4 — 生态补齐 | 1-2 天 | 3 | 24 | 410 |
| **合计** | **8-13 天** | **13** | **136** | **410** |

## 9. 架构决策

### 9.1 模块设计原则

- **深度模块优先**：每个新模块封装丰富的功能但在简单、稳定的接口后面。测试只需验证接口行为。
- **可独立测试**：每个模块不依赖 ToolRuntime 的完整初始化即可单独测试。
- **向后兼容**：所有新参数使用 keyword-only 并给默认值，现有代码零改动。

### 9.2 API 风格

- 同步和 Async 版本使用相同的参数签名，仅调用方式不同（`chat` vs `chat_async`）
- 所有公开接口使用 keyword-only 参数（`*` 分隔符）
- 错误类型继承自统一的 `DeepSeekError` 基类

### 9.3 依赖策略

- 核心功能零额外依赖（仅 `openai` SDK）
- 可选功能使用 `try/except ImportError` 延迟导入（如 `PyPDF2` 模式）
- Token 计数引入 `tiktoken` 作为可选依赖
- Async 使用标准库 `asyncio`

## 10. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| DeepSeek API 变更 | 模块不可用 | 每个端点独立封装，故障隔离；E2E 测试定期跑 |
| Beta 端点下线（FIM） | FIM 模块作废 | 标记为 beta，文档说明风险 |
| 速率限制头未正式发布 | 限流感知退化 | 保留盲重试的 fallback 路径 |
| Anthropic 兼容端点行为差异 | 迁移不透明 | 差异文档化，提供转换层源码 |
| Async 引入复杂性 | 维护负担增加 | sync 版本保持为主版本，async 是薄包装层 |

## 11. 进一步说明

- **Batch API 弃用**：DeepSeek 的 `/v1/batches` 端点经实测返回 404，当前 `chat_batch()` 实现标记为 `ExperimentalWarning`，等待官方支持后再激活。
- **DeepSeek Chat 模型迁移**：`deepseek-chat` 模型将于 2026/07/24 弃用。库已完成向 `deepseek-v4-pro` 和 `deepseek-v4-flash` 的过渡指导，文档和示例已更新。
- **MCP 协议**：现有 MCP 适配不做变更，Phase 3 的 async 支持会自然覆盖 MCP 的 async 场景。
- **JSON Repair**：现有 JSON Repair 管道保持不变。结构化输出（Phase 3）上线后，Repair 的调用频率会自然降低，但保留作为最后的 safety net。
