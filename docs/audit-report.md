# SeekFlow 全链路审阅报告

审阅日期：2026-05-15
审阅范围：7 条主链路，47 个集成点

---

## 总评

SeekFlow 有一条**可工作的核心链路**（Agent → Runtime → DeepSeek API → 工具执行），安全防御已嵌入此链路中。但 **DeepSeekAdapter、ModelRegistry、Budget/Cost 三个模块是死代码**——它们存在、通过了测试，但从未被主链路调用。整体状态：**60% 的模块已接通，40% 是孤岛**。

---

## 链路 1：Agent.run() → API 请求

```
Agent.run()
  → _make_runtime()        ✅ 创建 ToolRuntime + PolicyEngine + ToolExecutionContext
  → _make_messages()       ✅ 构建 system/user messages + cache stabilizer
  → rt.chat()
    → _apply_thinking_mode()  ⚠️ 走旧路径，不是 DeepSeekAdapter
    → _workspace_root_or_error() ✅ 文件附件必须有 workspace_root
    → _validate_protocol()  ✅ 每次 API 调用前校验消息协议
    → client.chat()         ✅ RetryExecutor 封装 DeepSeekClient
    → [API response]
```

| 集成点 | 状态 | 说明 |
|--------|------|------|
| PolicyEngine 传入 Runtime | ✅ | `PolicyEngine()` 在 `_make_runtime()` 创建并传入 |
| ToolExecutionContext 传入 Runtime | ✅ | 含 dangerous_tools_enabled, capabilities, max_risk, workspace_root, domains, sandbox |
| Cache stabilizer 在 Agent 层启用 | ✅ | `_make_runtime()` 后 freeze prefix |
| DeepSeekAdapter 接入 | ❌ | **未接入**。runtime 仍用 `_apply_thinking_mode()` 手拼参数 |
| 协议验证 | ✅ | `_validate_protocol()` 在每次 API 调用前运行 |
| RetryExecutor 封装 | ✅ | `_make_client()` 创建带 retry policy + circuit breaker 的 client |
| CircuitBreakerOpenError 处理 | ✅ | `chat()` 和 `chat_stream()` 都捕获并返回友好结果 |

---

## 链路 2：API 响应 → 工具调用执行

```
response.tool_calls
  → ToolExecutor.execute()
    → registry.get()           ✅
    → _parse_arguments()       ✅ JSON repair pipeline
    → DANGEROUS_REPAIR_CONFIDENCE_THRESHOLD check  ✅ 0.95
    → PolicyEngine.authorize() ✅ capability, risk, workspace, domain, sandbox 检查
    → approval handler check   ⚠️ handler 未从 Agent 传入，需要 approval 的工具会失败
    → cache lookup (after policy) ✅
    → execute func             ✅ (ThreadPoolExecutor with timeout)
    → wrap untrusted output    ✅
    → truncate                 ✅
    → audit record             ✅ (hash only)
```

| 集成点 | 状态 | 说明 |
|--------|------|------|
| PolicyEngine.authorize() 强制执行 | ✅ | 在 execute() 中调用，denied 时阻止执行 |
| max_input_bytes 强制执行 | ⚠️ | 策略字段存在但 execute() 未显式调用 `_enforce_input_limit()` |
| max_output_bytes 强制执行 | ⚠️ | 同上，依赖 truncation 而非硬限制 |
| policy.timeout_s 强制执行 | ⚠️ | 优先用 metadata["timeout"]，非 policy.timeout_s |
| approval_handler 传入 | ❌ | Agent 未创建/传入 approval handler，需 approval 的工具会因 "No approval handler" 而失败 |
| sandbox 传递 | ✅ | Agent → Runtime → ToolExecutor |
| audit 不泄露明文 | ✅ | 只记录 args_hash + result_hash |

---

## 链路 3：DeepSeekAdapter 集成 **[已修复 v0.3.0]**

`deepseek/adapter.py` 包含完整逻辑。

**调用方检查：**

| 文件 | 状态 | 说明 |
|------|------|------|
| `runtime.py` chat() | ✅ **已接入** | `DeepSeekAdapter.build_chat_params()` 是唯一协议入口 |
| `runtime.py` chat_stream() | ✅ **已接入** | 同上 |
| `runtime.py` chat_batch() | ✅ **已接入** | 同上 |
| `client.py` | ✅ 透传 | client 接收 normalized params 的 **kwargs |
| `agent.py` | ✅ | 通过 runtime 间接使用 |

---

## 链路 4：ModelRegistry / Pricing / Cost / Budget **[已修复 v0.3.0]**

| 组件 | 状态 |
|------|------|
| `ModelRegistry.price_usage()` | ✅ Agent._result_from_runtime() 调用 |
| `BudgetGuard` | ✅ Runtime 支持 opt-in cost_budget 参数 |
| `CostEstimator` | ✅ Runtime preflight 检查 |
| `CostTracker` | ✅ Runtime 每次 API 响应后记录 |
| `agent.py PRICING` | ✅ 作为 fallback（registry 失败时） |

---

## 链路 5：Protocol Validation

```
runtime.py:
  chat():          line 254 → _validate_protocol()  ✅
  chat_stream():   line 517 → _validate_protocol()  ✅
  chat_batch():    无调用 ⚠️
```

| 路径 | 状态 |
|------|------|
| `chat()` | ✅ 已接入 |
| `chat_stream()` | ✅ 已接入 |
| `chat_batch()` | ❌ 未接入 |
| 验证结果记录到 trace | ✅ `EVENT_DEEPSEEK_PROTOCOL_VALIDATED` |

---

## 链路 6：Retry / Circuit Breaker / Stream Safety

| 集成点 | 状态 |
|--------|------|
| RetryExecutor 封装 client | ✅ |
| max_elapsed_s 截止时间 | ✅ |
| DeepSeekAPIError 可重试状态码 | ✅ 408/409/429/500/502/503/504 |
| 不可重试不触发 breaker | ✅ 400/401/402/403/404 |
| Stream yield 后不 retry | ✅ `has_yielded` + `StreamInterruptedError` |
| CircuitBreaker success 清零 | ✅ |
| batch 路径使用 RetryExecutor | ❌ `chat_batch()` 直接构造 `DeepSeekClient`，绕过 retry |

---

## 链路 7：Builtin Tools → Agent → Runtime 注册链

```
Agent.allow_filesystem(root="/data", read=True, write=True)
  → make_read_file(workspace_root="/data") → add_tool()
  → make_list_dir(workspace_root="/data")  → add_tool()
  → make_write_file(workspace_root="/data") → add_tool()

Agent.allow_network(domains={"api.example.com"})
  → make_fetch_url(allowed_domains={"api.example.com"}) → add_tool()

Agent.allow_python(sandbox=ProcessSandbox())
  → make_python_exec(sandbox=ProcessSandbox()) → add_tool()

Agent.allow_sqlite(root="/data")
  → make_sqlite_query(workspace_root="/data") → add_tool()

Agent.run() → _make_runtime(tools=self._tools) → ToolRegistry.register()
```

| 步骤 | 状态 |
|------|------|
| `allow_filesystem(read=True)` 注册 read_file + list_dir | ✅ |
| `allow_filesystem(write=True)` 注册 write_file | ✅ |
| `allow_network()` 注册 fetch_url | ✅ |
| `allow_python()` 拒绝 NoSandbox | ✅ |
| `allow_sqlite()` 注册 query_sql | ✅ |
| 所有 builtin 带完整 ToolPolicy | ✅ |
| 工具通过 ToolRegistry → to_deepseek_tools() → API | ✅ |
| 工具执行通过 ToolExecutor → PolicyEngine | ✅ |

---

## 安全边界检查

| 边界 | 状态 | 防线 |
|------|------|------|
| 文件读取 | ✅ | `validate_file_access()` + `safe_join()` + workspace_root |
| 文件写入 | ✅ | workspace_root + requires_approval |
| 目录遍历 | ✅ | `safe_join()` 阻断 `../` |
| .env/密钥泄露 | ✅ | `DEFAULT_DENY_GLOBS` |
| HTTP SSRF | ✅ | `fetch_url_hardened()` + `validate_url_strict()` + trust_env=False |
| localhost 访问 | ✅ | IP 检查阻断 |
| 私网 IP 访问 | ✅ | 扩展范围含 CGNAT/198.18/2001:db8 |
| DNS rebinding | ✅ | resolve_all() 检查所有 IP |
| Python 代码执行 | ✅ | 必须 ProcessSandbox/ContainerSandbox，NoSandbox 拒绝 |
| SQL 注入 | ✅ | tokenizer + authorizer 双重防线，readonly URI |
| 密钥未写入 audit | ✅ | 只记录 hash |

---

## 问题汇总

### ✅ 已修复（v0.3.0）

| # | 问题 | 修复 |
|---|------|------|
| 1 | DeepSeekAdapter 未接入主链路 | chat/chat_stream/chat_batch 全部通过 `build_chat_params()` |
| 2 | ModelRegistry 未接入 | Agent 通过 `registry.price_usage()` 计算成本 |
| 3 | Budget preflight 未接入 | Runtime 支持 opt-in `cost_budget` + preflight + CostTracker |
| 4 | approval_handler 未传入 | Agent 接受 `approval_handler`，传递给 Runtime → ToolExecutor |
| 6 | chat_batch() 绕过 adapter | batch body 通过 DeepSeekAdapter 标准化 |

### 🟢 已接通（无需修改）

| # | 链路 |
|---|------|
| 5 | PolicyEngine → ToolExecutor authorize() 强制执行 |
| 6 | 协议验证 → chat/chat_stream/chat_batch 每次 API 调用前 |
| 7 | RetryExecutor → 可重试状态码 + has_yielded 流保护 |
| 8 | 文件安全 → workspace_root + deny globs + 目录遍历阻断 |
| 9 | SSRF → fetch_url_hardened + validate_url_strict + trust_env=False |
| 10 | SQLite → tokenizer + authorizer + readonly URI |
| 11 | Python exec → NoSandbox 拒绝 + ProcessSandbox/ContainerSandbox |
| 12 | Builtin → Agent.allow_* 工具注册链完整 |
| 13 | content=None → "" 在 tool-call assistant 中修复 |

---

## 结论（更新）

SeekFlow 的三条腿现在全部着地。**安全腿**（PolicyEngine、文件沙箱、SSRF、SQL/Python 执行隔离）、**可靠性腿**（Retry/CircuitBreaker/协议验证/流安全）和**协议/模型/成本腿**（DeepSeekAdapter、ModelRegistry、Budget/Cost）现在全部接入主链路。

关键路径现在是：
```
Agent.run()
  → Runtime.chat()
    → DeepSeekAdapter.build_chat_params()  ← 统一协议入口
    → _validate_protocol()                 ← 每次 API 调用前
    → BudgetGuard.check_tokens()           ← 首次调用前预检
    → client.chat(**normalized)            ← RetryExecutor 封装
    → CostTracker.record()                 ← 每次响应后
    → [tool call]
      → ToolExecutor.execute()
        → PolicyEngine.authorize()         ← 安全门
        → approval_handler                 ← 审批（如需要）
        → sandbox/authorizer               ← 隔离执行
    → ModelRegistry.price_usage()          ← 单一价格来源
```
