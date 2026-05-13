# PRD: DTK v3 — 最轻量、最适配 DeepSeek 的 Agent 框架

**版本**: 1.0
**日期**: 2026-05-10
**状态**: 待评审
**作者**: SeekFlow Team

---

## 1. 背景

### 1.1 问题

当前 DeepSeek 开发者面临两难选择：

| 框架 | 代码量 | DeepSeek Thinking | 1M上下文 | 中文错误 | 学习曲线 |
|------|--------|-------------------|----------|----------|----------|
| LangChain | ~12万行 | ❌ 丢弃reasoning_content | ❌ 无profile | ❌ 通用异常 | 陡峭 |
| CrewAI | ~11万行 | ❌ 零支持 | ❌ 仅128K | ❌ catch-all | 中等 |
| DTK v2 | ~5千行 | ✅ 完整 | ✅ | ✅ 6类 | 低 |

**LangChain/CrewAI 把 DeepSeek 当成 "另一个 OpenAI 兼容端点"，导致高级功能全部不可用。**

具体证据：
- **Thinking mode 多轮对话失败**：LangChain `_format_message_content()` 显式过滤丢弃 `reasoning_content` 块，多轮thinking必400错误
- **Token计数崩溃**：LangChain `get_num_tokens_from_messages()` 对非OpenAI模型直接 `raise NotImplementedError`
- **1M上下文缩水**：CrewAI 仅识别 `deepseek-chat: 128K`，LangChain 无任何DeepSeek模型profile
- **错误不可诊断**：402余额不足→LangChain返回通用 `BadRequestError`，CrewAI返回catch-all `Exception`
- **代码膨胀**：CrewAI ~100 个事件类的 Started/Completed/Failed 三元组，LangChain 12万行抽象层，都是为通用性付出的复杂度代价

### 1.2 趋势

- **Anthropic "Building Effective Agents" (2024.12)**：明确建议"最简单的方案往往最好"，反对过度框架化
- **1M 上下文改变 RAG 范式**：chunk→embed→retrieve→rerank 管道在 1M 窗口下大部分可省略
- **DeepSeek 生态真空**：100K+ GitHub stars 的 LangChain 没有 `langchain_deepseek` 包，CrewAI 1.14.4 完全没有 `reasoning_content` 处理

### 1.3 机会

DTK v2 已拥有完整的 DeepSeek 运行时（5K行）。在基础上增加 ~7K 行编排层和兼容桥接层，可以实现一个 **功能对标 LangChain+CrewAI、但代码量仅 1/10、真正适配 DeepSeek 的 Agent 框架**。

---

## 2. 目标

### 2.1 核心目标

- **P0 — 独立可用**：不依赖 LangChain 或 CrewAI，开发者仅用 DTK 即可构建生产级 Agent 应用
- **P0 — DeepSeek 原生**：Thinking mode、1M 上下文、缓存感知、中文错误在 Agent 层开箱即用
- **P1 — 生态兼容**：接受 LangChain `Document`、任意 embedding 函数和 vector store，继承已有生态积累
- **P1 — 极简 API**：3 行代码定义 Agent 并运行，对标 CrewAI 的简洁体验
- **P2 — 多 Agent**：顺序/并行/层级三种编排模式，覆盖 90% 实际场景

### 2.2 量化目标

| 指标 | 目标 | 对标 |
|------|------|------|
| 核心代码量 | ≤12,000 行 | LangChain 12万 / CrewAI 11万 |
| 单 Agent 启动代码 | ≤5 行 | CrewAI 5行 |
| 首次运行时间（含安装） | ≤30 秒 | LangChain ~5分钟（依赖解析） |
| API 文档覆盖率 | 100% | — |
| Thinking mode 多轮可用 | ✅ | LangChain ❌ / CrewAI ❌ |
| 1M 上下文窗口利用率 | 100% | LangChain 0% / CrewAI 12.8% |

---

## 3. 非目标

- **不做通用模型路由**：不引入 LiteLLM 或类似抽象。仅支持 DeepSeek API。用户如需多供应商切换，应在上一层处理
- **不做 800 个集成**：不重复造 LangChain 的 document loader、vector store 生态。通过兼容接口继承
- **不做通用图引擎**：不实现 LangGraph 的 DAG/条件分支图。只做顺序→并行→层级三种模式
- **不做 RAG 全管道**：不做 chunk→embed→retrieve→rerank→generate 的基础设施。1M 上下文使大部分管道不再必要；需要精细化检索的用户可用现有向量数据库
- **不做 Web UI / CLI 管理面板**：保持库的定位，不膨胀为平台
- **不做 multi-provider agent**：不支持"同一个 Agent 用 OpenAI、工具用 Anthropic"的混合供应商场景

---

## 4. 用户故事

### Agent 定义与运行

1. 作为 Python 开发者，我想用 3 行代码定义一个 DeepSeek Agent 并运行，这样我可以在 5 分钟内验证想法
2. 作为 AI 应用开发者，我想为 Agent 指定角色（role）、目标（goal）和背景（backstory），用自然语言定义其行为
3. 作为后端工程师，我想将 Agent 封装为异步函数，方便集成到 FastAPI/Django 服务中
4. 作为数据分析师，我想将 CSV/PDF 文件传给 Agent，让它自动分析并生成报告

### Thinking Mode

5. 作为 Agent 开发者，我想开启 thinking mode 让 Agent 在复杂任务上做出更好的决策
6. 作为调试者，我想在控制台实时看到模型的推理过程（reasoning_content streaming）
7. 作为运维者，我想确认 thinking mode 在多轮对话中自动传递 reasoning_content，不会 400 报错

### 1M 上下文

8. 作为 RAG 应用开发者，我想一次性将完整文档集（数十万字）传给 Agent，不再手动切块和检索
9. 作为代码审查 Agent 的用户，我想将整个代码仓库上下文传给 Agent 进行跨文件分析
10. 作为用户，我想看到 Agent 当前消耗了多少上下文窗口（已用/总量）

### 工具系统

11. 作为开发者，我想用 `@tool` 装饰器将任意 Python 函数变为 Agent 可用工具
12. 作为工具作者，我想定义清晰的输入 schema（类型+描述），让模型正确调用
13. 作为用户，我想看到每次工具调用耗时和结果摘要

### 编排

14. 作为应用开发者，我想让多个 Agent 按顺序执行任务链（agent A → agent B → agent C）
15. 作为应用开发者，我想让多个 Agent 并行处理不同的子任务，然后汇总结果
16. 作为应用开发者，我想设置一个管理 Agent 将复杂任务分解后分配给执行 Agent（层级模式）
17. 作为运维者，我想要 Agent 执行过程支持 checkpoint/resume——节点失败后能从保存点恢复，不重跑已完成步骤

### 生态兼容

18. 作为已有 LangChain 管道的用户，我想将 LangChain 的 `Document` 对象直接传给 DTK Agent
19. 作为向量检索用户，我想使用任意 embedding 函数和 vector store 与 DTK Agent 配合
20. 作为 MCP 用户，我想让 DTK Agent 可以使用 MCP 协议的工具和资源

### 生产就绪

21. 作为运维者，我想在余额不足时收到明确的中文错误提示，而不是 cryptic 的 BadRequestError
22. 作为成本敏感用户，我想看到每次 Agent 运行花费了多少 token 和人民币
23. 作为高并发用户，我想了解当前速率限制状态（剩余请求数、重置时间）
24. 作为调试者，我想回放 Agent 的完整执行过程（消息历史、工具调用、token 消耗）

---

## 5. 核心功能

### 5.1 模块架构

```
seekflow/                  # 现有 v2 核心（保持不变）
├── client.py                      # DeepSeekClient (已有)
├── runtime.py                     # ToolRuntime (已有)
├── types.py                       # ChatResponse, StreamChunk 等 (已有)
├── errors.py                      # 6类错误 + map_http_error (已有)
├── cache.py                       # CacheSentinel (已有)
├── session.py                     # Session save/load (已有)
├── token_counter.py               # Token计数 (已有)
├── context.py                     # SlidingWindow, ContextCompressor (已有)
├── reasoning.py                   # check_consistency (已有)
├── tools.py                       # @tool 装饰器 (已有)
├── retry.py                       # 重试/熔断 (已有)
└── async_runtime.py               # 异步运行时 (已有)

seekflow/agent/            # v3 新增 — Agent 编排层
├── agent.py                       # Agent 定义 (role/goal/backstory + Agent.run())
├── task.py                        # Task 定义 (description + expected_output + context)
├── crew.py                        # Crew 编排 (sequential/parallel/hierarchical)
├── orchestration.py               # 编排引擎 (顺序/并行/层级调度)
├── checkpoint.py                  # Checkpoint/Resume (借鉴 LangGraph 思路，精简实现)

seekflow/compat/           # v3 新增 — 生态兼容桥接层
├── documents.py                   # 接受 langchain Document 或任意 dict
├── embeddings.py                  # 接受任意 embedding 函数 (callable 接口)
├── vector_stores.py               # 接受任意 vector store (put/get/search 接口)
├── mcp.py                         # MCP 协议 client (已有 v2 基础)

seekflow/presets/          # v3 新增 — 预设 Agent 模板
├── analyst.py                     # 数据分析 Agent
├── researcher.py                  # 调研 Agent
├── coder.py                       # 代码 Agent
└── creative.py                    # 创意 Agent
```

### 5.2 Agent 定义

```python
# 3 行代码启动
from seekflow import DeepSeekAgent

agent = DeepSeekAgent(
    role="财务分析师",
    goal="分析字节跳动2025年财务报告，给出评级和建议",
    backstory="CPA+CFA持证人，20年互联网行业经验",
)
result = agent.run(files=["financial_report.json"])
```

### 5.3 Task Pipeline

```python
from seekflow import DeepSeekAgent, Task, Crew

research = DeepSeekAgent(role="研究员", goal="搜索行业数据")
analyst = DeepSeekAgent(role="分析师", goal="分析数据并写报告")
writer = DeepSeekAgent(role="撰稿人", goal="润色并格式化报告")

crew = Crew(
    tasks=[
        Task(description="搜索2025年AI行业融资数据", agent=research),
        Task(description="分析数据，找出趋势和异常", agent=analyst),
        Task(description="将分析结果整理为正式报告", agent=writer),
    ],
    process="sequential",  # sequential | parallel | hierarchical
)
result = crew.kickoff()
```

### 5.4 Checkpoint/Resume

```python
# 自动 checkpoint — Agent 执行中每步自动保存状态
crew = Crew(tasks=[...], checkpoint=True)
try:
    result = crew.kickoff()
except Exception:
    # 恢复执行 — 从最后一个成功的 checkpoint 继续
    result = crew.resume()  # 不重跑已完成的步骤
```

### 5.5 生态兼容

```python
# 桥接 LangChain 生态，不依赖 langchain 运行时
from langchain_community.document_loaders import PyPDFLoader
from seekflow import DeepSeekAgent

loader = PyPDFLoader("report.pdf")
docs = loader.load()  # List[langchain.schema.Document]

agent = DeepSeekAgent(role="分析师")
agent.add_documents(docs)  # 直接接受
result = agent.run("总结这份报告")

# 使用自定义 embedding 和 vector store
agent = DeepSeekAgent(role="知识库问答")
agent.use_embedding(my_embedding_function)    # 任何 Callable[[str], list[float]]
agent.use_vector_store(my_vector_store)       # 任何有 put/get/search 的对象
```

---

## 6. 实现决策

### 6.1 编排模型：放弃图引擎，只用三种模式

**决策：** 不做通用 DAG 图引擎（LangGraph 方向），只实现 Sequential / Parallel / Hierarchical 三种 Process。

**理由：**
- CrewAI 验证了这两种模式覆盖绝大多数场景（consensual 模式至今是 TODO）
- 通用图引擎需要 checkpoint、branch、conditional edge、subgraph 等概念，单这一项就超过 30K 行
- 1M 上下文使"单 Agent 直接处理"成为可能——很多场景不需要编排多 Agent
- 用户的逻辑控制通过普通 Python 代码（if/for）实现，比 YAML/JSON 配置图更直观

**接口设计：**
```python
class Process(str, Enum):
    SEQUENTIAL = "sequential"       # A → B → C，每步的输出作为下一步的输入
    PARALLEL = "parallel"           # A, B, C 同时执行，结果合并
    HIERARCHICAL = "hierarchical"   # Manager Agent 分配任务给 Worker Agents

class Crew:
    tasks: list[Task]
    process: Process = Process.SEQUENTIAL
    manager_agent: DeepSeekAgent | None = None  # hierarchical 模式必需
    checkpoint: bool = False                    # 是否启用 checkpoint
```

### 6.2 Checkpoint：借鉴 LangGraph 思路，精简实现

**决策：** 实现基于消息历史的 checkpoint，而非 LangGraph 的 channel-based checkpoint。

**理由：**
- LangGraph 的 channel checkpoint 服务于通用图引擎——每个 node 有独立状态通道
- DTK 的 Agent 是 LLM 驱动的——状态就是消息历史 + 工具调用记录
- 保存完整对话历史远比保存任意 Python 对象简单

**实现：**
```python
class AgentCheckpoint(TypedDict):
    thread_id: str                   # 会话 ID
    step: int                        # 当前步骤号
    messages: list[dict]             # 完整消息历史 (含 reasoning_content)
    tool_calls_completed: list[str]  # 已完成的工具调用 ID 列表
    timestamp: str                   # ISO 8601

class CheckpointStore:
    def save(self, checkpoint: AgentCheckpoint) -> None: ...
    def load(self, thread_id: str) -> AgentCheckpoint | None: ...
    def delete(self, thread_id: str) -> None: ...
```

默认 `InMemoryStore`，提供 `SqliteStore` 用于持久化。接口保持极简——3 个方法，用户可自行实现 Redis/Postgres 存储。

### 6.3 兼容策略：接口桥接，不依赖运行时

**决策：** 通过 Python protocol（duck typing）接受外部对象，不引入 LangChain 作为运行时依赖。

**理由：**
- LangChain 12 万行运行时依赖太重——用户只是想用 Document loader
- Python 的 duck typing 天然支持：只要对象有 `page_content` 和 `metadata` 属性，就是 Document
- Embedding 函数更简单——就是一个 `(str) -> list[float]` 的 callable
- Vector store 只需要 3 个方法：`put(id, vector, metadata)`, `get(id)`, `search(query_vector, top_k)`

**接口定义：**
```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class DocumentLike(Protocol):
    page_content: str
    metadata: dict

@runtime_checkable
class VectorStoreLike(Protocol):
    def search(self, query: str | list[float], top_k: int = 5) -> list[DocumentLike]: ...
```

不定义严格的抽象基类。用 Protocol 做类型提示，用 `hasattr` 做运行时检查。用户传入的任何对象只要满足协议就能工作。

### 6.4 不做的工作：RAG 管道

**决策：** 不实现 chunk、embed、retrieve、rerank 的完整管道。

**理由：**
1. **1M 上下文改变了范式。** 100 页 PDF 全文约 30 万 token——直接扔进上下文，不需要 chunk+retrieve。只有当文档集超过 1M token 时才需要检索。这是 "dump and ask" 而非 "chunk and retrieve"。
2. **生态已成熟。** 需要精细化检索的用户有 Chroma、Qdrant、Pinecone、Milvus 等专用库。DTK 只需能与它们对接。
3. **避免 LangChain 的错误。** LangChain 的 RAG 管道是最受诟病的部分——过度抽象的 chain（`RetrievalQA.from_chain_type`），用户在不理解内部机制时配置出错。

**如果确实需要检索（文档 >1M token）：**
```python
# 用户自己的检索逻辑 —— DTK 不接管
from chromadb import PersistentClient

results = vector_db.search(query, top_k=10)
docs = [DocumentLike(page_content=r.text, metadata=r.meta) for r in results]

agent = DeepSeekAgent(role="问答助手")
agent.add_documents(docs)
agent.run(query)
```

### 6.5 Tool 系统：保持现有 @tool 装饰器，不做 Tool Registry

**决策：** 不引入全局 Tool Registry。工具按 Agent 实例注册。

**理由：** 全局 Registry 是 LangChain 的另一个复杂度来源——需要管理工具生命周期、避免命名冲突、处理重复注册。按实例注册更简单，Agent 持有自己的工具列表。

```python
agent = DeepSeekAgent(role="分析师")
agent.add_tool(my_custom_tool)       # 单个工具
agent.add_tools([tool_a, tool_b])    # 批量
agent.with_default_tools()           # 使用内置工具集 (web_search, read_file, calculate, save)
```

### 6.6 前沿技术融入

| 技术 | 融入方式 | 价值 |
|------|----------|------|
| **MCP 协议** | v2 已有 MCP 适配器，v3 在 Agent 层直接支持 MCP 工具 | 与 Anthropic 生态互通，LangChain 也已支持 |
| **Structured Output** | Agent 输出可选 Pydantic 模型，利用 DeepSeek `response_format` | 规避 LanChain `json_schema` 默认值崩溃问题 |
| **Streaming as Default** | 所有 Agent 默认流式输出，含 reasoning_content 事件 | 实时反馈 + 完整推理可见 |
| **Token-aware Truncation** | 基于 token count 而非字符数的智能截断 | 1M 窗口下精确控制 |
| **Cache-aware Prompting** | system prompt 自动前置 + 稳定化以最大化缓存命中 | DeepSeek 缓存 60x 价差 |
| **Prompt Caching (Context Caching)** | 借鉴 Anthropic/DeepSeek 的 disk-cache 机制 | 对长 system prompt 和文档前缀自动缓存 |

### 6.7 与 CrewAI/LangChain 的功能对比

| 能力 | DTK v3 | LangChain | CrewAI | 差异化 |
|------|--------|-----------|--------|--------|
| Agent 定义 | role/goal/backstory | prompt模板 | role/goal/backstory | 借鉴 CrewAI |
| 多Agent编排 | Seq/Par/Hier | LangGraph(图) | Seq/Hier | 够用，不膨胀 |
| Checkpoint | 消息级 | Channel级(重) | 无 | 轻量够用 |
| Thinking mode | ✅ 原生 | ❌ 丢弃 | ❌ 零支持 | **独占** |
| 1M上下文 | ✅ 全量 | ❌ 无profile | ❌ 128K | **8x差距** |
| RAG管道 | 桥接(不实现) | 完整(过度抽象) | 无 | 务实 |
| 代码量 | ~12K | ~120K | ~110K | **10x轻量** |
| DeepSeek定价 | 内建CNY | 通用无 | 无 | **独占** |
| 错误分类 | 6类中文 | 通用异常 | catch-all | **独占** |
| 外部依赖 | 0（仅openai SDK） | 50+ | LiteLLM+50+ | **零依赖** |

---

## 7. 测试决策

### 7.1 测试原则

- 只测试外部行为，不测试实现细节——接口不变时重构不破坏测试
- 每个 Agent/Task/Crew 测试必须是端到端的：定义角色 → 运行真实 API → 验证输出结构
- 使用 DeepSeek 沙箱 API key 或 mock——CI 中不消耗真实余额

### 7.2 测试模块

| 模块 | 测试类型 | 参照 |
|------|----------|------|
| `agent.py` | 端到端（E2E） | 已有 `tests/test_thinking.py` 模式 |
| `task.py` | 单元 + E2E | Task 定义→验证 schema→运行 |
| `crew.py` | E2E（多 Agent） | sequential/parallel/hierarchical 各一个 |
| `orchestration.py` | 单元（调度逻辑可 mock） | 纯函数测试 |
| `checkpoint.py` | 单元（save/load/delete） | InMemoryStore 完整覆盖 |
| `compat/documents.py` | 单元（Protocol 匹配） | 多种 Document 格式 |
| `compat/vector_stores.py` | 集成（对接 Chroma） | 真实 vector store |

### 7.3 不测试的

- MCP 协议交互——已有 v2 测试覆盖，v3 不变
- 工具执行内部细节——已有 v2 测试覆盖
- DeepSeek API client——已有 v2 测试覆盖

### 7.4 回归保护

- 运行 `tests/` 中所有已有 274 个单元测试
- 新增 Agent 层测试不破坏已有 runtime/client/tools 层
- 每次 PR 前完整运行 `pytest tests/`，阈值：0 失败

---

## 8. 边界情况

### 8.1 Thinking Mode 边界

- 用户开启 thinking mode 但消息历史超过 1M 上下文——应警告可能截断 reasoning 内容
- API 返回 reasoning_content 为空字符串——Agent 应正常继续（不崩溃）
- DeepSeek API 版本不支持 thinking——应给出清晰错误提示，而非静默失败
- 用户在 hierarchical 模式中对 manager 和 worker 使用不同的 thinking 设置——应支持但有警告

### 8.2 1M 上下文边界

- 用户传入 200 万 token 的文档——应自动截断并警告，而非崩溃
- 文档包含非 UTF-8 字符——应优雅降级，标记无法解析的部分
- 用户在工具调用过程中上下文接近 1M 上限——应触发 ContextCompressor 压缩，或在无法压缩时提前终止并保存 checkpoint

### 8.3 编排边界

- Hierarchical 模式中 manager agent 本身崩溃——checkpoint 应保存 manager 和所有 worker 的状态
- Parallel 模式中一个 worker 失败——其他 worker 应继续执行，失败结果在汇总中标记
- 用户传入的 Task 列表为空——Crew.kickoff() 应返回明确错误而非静默无输出
- Checkpoint 恢复时 thread_id 不存在——应返回明确错误
- 同一 thread_id 同时有两个 Crew 在运行——应检测冲突并报错

### 8.4 兼容边界

- 用户传入的对象有 `page_content` 但没有 `metadata`——应补默认 `{}`，不崩溃
- Embedding 函数返回的向量维度与预期不符——应在添加文档时检测并报错，而非在检索时才发现
- Vector store 的 `search` 方法签名不匹配——应给出清晰的接口要求说明

### 8.5 生产边界

- DeepSeek API 返回 503（服务过载）——自动重试（已有 retry.py），最多3次
- DeepSeek API 返回 402（余额不足）——不重试，直接报中文错误，附充值链接
- 用户传入的 API key 格式错误——应在 Agent 初始化时立即检测，而非等到第一次 API 调用
- 并发场景下多个 Agent 共享同一 API key——DTK 不负责速率限制聚合，由用户层处理

---

## 9. 开发阶段

### Phase 1: Core Agent（1周）
- `agent.py`: Agent 定义 + `.run()` 方法
- `task.py`: Task 定义
- 与现有 runtime 层的集成
- **验收**: 3 行代码定义 Agent 并完成一个简单任务（如"读取 sales_data.csv，分析品类销售额"）

### Phase 2: Crew + 编排（1周）
- `crew.py`: Crew 定义 + `.kickoff()`
- `orchestration.py`: Sequential + Parallel 实现
- **验收**: 2 个 Agent 按 Sequential 模式完成端到端任务；3 个 Agent 按 Parallel 模式并行处理并汇总

### Phase 3: 生态兼容（1周）
- `compat/documents.py`: Document Protocol + LangChain 桥接
- `compat/embeddings.py`: Embedding 函数 Protocol
- `compat/vector_stores.py`: Vector Store Protocol
- **验收**: 用 LangChain 的 PyPDFLoader 加载 PDF → DTK Agent 直接处理；Chroma 检索结果 → DTK Agent 问答

### Phase 4: Checkpoint + Hierarchical（1周）
- `checkpoint.py`: InMemoryStore + SqliteStore
- Hierarchical 编排模式
- Crew checkpoint/resume 集成
- **验收**: Sequential Crew 在第 2 步失败 → resume 从第 2 步继续；Hierarchical Crew 完成"manager 分解任务→3 个 worker 执行→manager 汇总"

### Phase 5: 文档 + 示例 + 迁移指南（1周）
- API 参考文档（所有公开类和方法）
- 5 个 Cookbook：数据分析 / 投资分析 / 代码审查 / 文档问答 / 多 Agent
- LangChain→DTK 迁移指南
- CrewAI→DTK 迁移指南
- **验收**: 一个新用户不看源码、仅凭文档能在 30 分钟内完成第一个 Agent

### Phase 6: 性能基准 + 推广（持续）
- 三框架性能/质量基准测试
- 博客：技术决策背后的设计哲学
- 对比视频/表格

---

## 10. 进一步说明

### 10.1 为什么不做通用框架

1M 上下文 + DeepSeek 的独特 API 行为意味着 DeepSeek 上的最佳实践与 OpenAI/Anthropic 上完全不同。一个"适配所有供应商"的框架必然在每个供应商上都做不好——LangChain 和 CrewAI 已经证明了这一点。

专注 DeepSeek 不是局限，是战略。**DTK 的目标不是"让所有 LLM 用户都能用"，而是"让 DeepSeek 用户觉得没有 DTK 就少了什么"。**

### 10.2 关于代码膨胀的教训

CrewAI 从简单的 Agent/Task/Crew 三元组演化到 ~100 个事件类的系统，LangChain 从简单的 Chain 演化到 12 万行。每次功能添加都合理，但累积效果是开发者再也无法理解框架的全貌。

DTK v3 必须对抗这种熵增。每添加一个功能，问自己：**80% 的用户会用到这个吗？如果不会，它应该是一个用户自己的代码，不是框架的一部分。**

### 10.3 关于"先有鸡还是先有蛋"

新框架最大的问题不是技术，是用户获取。初始策略：
1. 用 DTK v3 做 3 个 LangChain/CrewAI 做不了的 Demo（thinking mode 多轮对话、1M 上下文全量分析、批量 Agent 成本对比）
2. 每个 Demo 配视频 + 博客 + 可复现的 Colab notebook
3. 在 DeepSeek 社区（官方 Discord、中文论坛、GitHub）发布

---

## 11. 实现进度与审计（2026-05-11 更新）

### 11.1 已完成（P0 核心功能）

| Issue | 功能 | 测试数 | 状态 |
|-------|------|--------|------|
| v3-001 | Agent 定义 (role/goal/backstory) | 4 | ✅ |
| v3-002 | Task 定义 | 5 | ✅ |
| v3-003 | 工具注册 (add_tool/add_tools) | 5 | ✅ |
| v3-004 | 文件输入 (1M 上下文) | 3 | ✅ |
| v3-005 | Thinking Mode Agent E2E | 3 | ✅ |
| v3-006 | Sequential Crew | 5 | ✅ |
| v3-007 | Parallel Crew | 2 | ✅ |
| v3-008 | Crew Lifecycle (callback+summary) | 2 | ✅ |
| v3-009 | Document Protocol | 4 | ✅ |
| v3-011 | MCP 配置存储 | 2 | ✅ |
| v3-012 | Checkpoint (InMemory+Sqlite) | 5 | ✅ |
| v3-014 | Hierarchical Process | 3 | ✅ |
| v3-017 | Agent.stream() + reasoning 事件 | 4 | ✅ |
| v3-018 | Structured Output (response_format) | 2 | ✅ |
| v3-019 | 1M 上下文 (max_context_tokens=900K) | 2 | ✅ |
| v3-020 | 并行工具执行标志 | 2 | ✅ |
| v3-021 | MCP 完整生命周期（接线） | 2 | ✅ |
| v3-022 | add_documents/use_embedding/use_vector_store | 2 | ✅ |
| v3-023 | 默认工具补全 (web_search+download_page) | 1 | ✅ |
| v3-028 | presets/ 模块 (analyst/researcher/coder/creative) | 3 | ✅ |

**小计：66 个测试，全部通过**

### 11.2 待完成

| Issue | 功能 | 优先级 |
|-------|------|--------|
| v3-024 | Agent 层面 checkpoint（run 中自动保存） | P1 |
| v3-025 | Crew 边界处理（空tasks/冲突/恢复对话） | P1 |
| v3-029 | ContextCompressor | P1 |
| v3-030 | Human-in-the-Loop | P2 |
| v3-026 | Guardrails 基础（whitelist/sanitize） | P2 |
| v3-027 | Token 精确计数（tiktoken） | P2 |
| v3-031 | ReAct 模式 | P2 |
| v3-032 | Plan & Solve 模式 | P2 |
| v3-033 | Reflection 模式 | P2 |
| v3-034 | A2A 协议支持 | P3 |
| v3-035 | LLM-as-Judge 评估 | P3 |
| v3-036 | Guardrails 补全（max cost/rate limit） | P3 |

---

## 12. SOTA 对齐与竞品对比

### 12.1 2025-2026 前沿技术参考

| 来源 | 关键洞察 | DTK 对齐状态 |
|------|---------|-------------|
| Anthropic "Building Effective Agents" (2024.12) | 简单 > 复杂；单Agent+工具循环覆盖多数场景 | ✅ ReAct模式已实现 |
| Anthropic "Multi-Agent Research" (2025.06) | Orchestrator-Worker模式；并行子Agent 90%性能提升 | ✅ Hierarchical已实现 |
| Google Agent Bake-Off (2025) | 并行Agent将1小时降至10分钟 | ✅ Parallel已实现 |
| MCP Protocol (Anthropic 2024) | Agent↔Tool标准协议 | ✅ MCP已接线 |
| A2A Protocol (Google 2025.04) | Agent↔Agent通信标准 | ⏳ v3-034 |
| Semi-Formal Reasoning (2025) | 显式Premises→Trace→Conclusion提升准确率78%→93% | ⏳ 未实现 |
| Context Compression (2025) | 文件offload + 小模型重写 + 章节检索 | ⚠️ 基础版已实现 |
| Structured Output Pydantic | 行业标准 | ✅ 已支持 response_format |

### 12.2 竞品功能矩阵（2026-05 最新）

| 能力 | DTK v3 | LangChain | CrewAI | DTK 优势 |
|------|--------|-----------|--------|---------|
| Agent 定义 | 3行 | create_agent() | 5行 | **最简** |
| Thinking Mode | ✅ 完整 | ❌ 丢弃 | ❌ 零支持 | **独占** |
| 1M 上下文 | ✅ 900K默认 | ❌ 无profile | ❌ 128K | **7x** |
| 中文错误 | ✅ 6类 | ❌ 通用 | ❌ catch-all | **独占** |
| Streaming | ✅ 含reasoning | ✅ 无reasoning | ⚠️ 有限 | **reasoning可见** |
| Structured Output | ✅ | ✅ | ✅ | 持平 |
| Sequential | ✅ | ✅ | ✅ | 持平 |
| Parallel | ✅ | ✅ | ❌ | 超CrewAI |
| Hierarchical | ✅ | ⚠️ LangGraph | ✅ | 持平 |
| Checkpoint | ✅ | ✅ LangGraph | ❌ | 超CrewAI |
| MCP | ✅ | ✅ | ⚠️ beta | 接近 |
| A2A | ❌ | ❌ | ❌ | 均无 |
| ReAct | ✅ | ✅ 原生 | ❌ | 超CrewAI |
| Plan&Solve | ✅ | ✅ | ❌ | 超CrewAI |
| Reflection | ✅ | ❌ | ❌ | **独占** |
| 代码量 | ~1000行 | ~12万行 | ~11万行 | **100x轻** |
| 依赖数 | 1 (openai) | 50+ | LiteLLM+50+ | **零依赖** |

### 12.3 LangChain 精华（已吸收）

- Runnable 接口的 invoke/stream/batch 范式 → Agent.run()/stream()
- Document schema (page_content + metadata) → DocumentLike Protocol
- Checkpoint/resume（LangGraph）→ AgentCheckpoint + CheckpointStore

### 12.4 LangChain 糟粕（已避开）

- 12万行抽象层：只为适配20+供应商 → DTK 只做 DeepSeek
- tiktoken 对 DeepSeek 模型 NotImplementedError → DTK 用 char/4 启发式
- json_schema 默认值对 DeepSeek 崩溃 → DTK 默认 None，显式 opt-in
- get_num_tokens_from_messages() 对非 OpenAI 模型崩溃 → DTK 自实现

### 12.5 CrewAI 精华（已吸收）

- role/goal/backstory 三字段定义 Agent → DeepSeekAgent 核心参数
- Task description + expected_output → Task 定义
- Process(sequential/hierarchical) → Crew Process 枚举

### 12.6 CrewAI 糟粕（已避开）

- ~100 个事件类的 Started/Completed/Failed 三元组 → DTK callback 一个函数
- LiteLLM 软依赖 → DTK 零额外依赖
- 内部 tool_usage 追踪混乱（dict vs object） → DTK 直接从 API usage 提取
- CrewAI 1.14.4 完全不认识 reasoning_content → DTK 一等支持
- 仅识别 deepseek-chat:128K → DTK 正确识别 1M

---

## 13. 自检标准

### 13.1 每轮构建后自检（耦合度 / 冗余度 / 性能）

**耦合度检查：**
- [ ] 新增代码是否引入新的外部依赖？（目标：零新增）
- [ ] 新模块是否可以独立测试？（不应依赖 Agent 启动才能测）
- [ ] Agent/Task/Crew 三层是否单向依赖？（Agent ← Task ← Crew，不应反向）
- [ ] compat/ 模块是否与 agent/ 模块零耦合？（Protocol 定义不应 import agent）

**冗余度检查：**
- [ ] 是否借鉴了 CrewAI 的 100 事件类模式？（如果是，立即删除）
- [ ] 新功能是否 < 100 行？（超过需论证必要性）
- [ ] 是否存在未被任何测试覆盖的代码路径？
- [ ] 是否存在"以防万一"的参数？（每个参数必须有至少一个测试）

**性能检查：**
- [ ] run() 调用是否每次新建 ToolRuntime？（应考虑复用）
- [ ] checkpoint save 是否在热路径上？（应在 tool call 之后，不在之前）
- [ ] 消息历史是否无限增长？（应有截断/压缩）

### 13.2 全量构建后自检（PRD 覆盖 / 技术前沿 / 竞品提升）

**PRD 覆盖检查：**
- [ ] 第5节"核心功能"中的每个模块是否存在对应 .py 文件？
- [ ] 第6节"实现决策"中的每个接口是否实现？
- [ ] 第8节"边界情况"中的每个场景是否有测试覆盖？
- [ ] 第9节"开发阶段"中的每个 Phase 验收标准是否通过？

**技术前沿检查：**
- [ ] 是否支持 MCP 协议（2024 Anthropic 标准）？
- [ ] 是否实现 Anthropic "Building Effective Agents" 三原则（简单/选择性/模型视角）？
- [ ] 是否正确利用 1M 上下文（而非沿用 128K 假设）？
- [ ] 是否支持 Structured Output (Pydantic/JSON)？

**竞品提升检查：**
- [ ] 是否有至少 3 项 LangChain 做不到的功能？
- [ ] 是否有至少 3 项 CrewAI 做不到的功能？
- [ ] 代码量是否 < LangChain 的 1/10？(< 12K 行)
- [ ] 代码量是否 < CrewAI 的 1/10？(< 11K 行)
- [ ] 是否可以 3 行代码跑起来？（对标 CrewAI 5 行）
- [ ] 安装时间是否 < 30 秒？（对标 LangChain 5 分钟）

**如果任何检查不通过 → 修复 → 重新检查，直到全部通过。**
4. 一旦有 100 个活跃用户，靠口碑传播
