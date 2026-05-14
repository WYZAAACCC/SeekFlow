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

## 链路 3：DeepSeekAdapter 集成

`deepseek/adapter.py` 包含完整逻辑：
- `build_chat_params()` — thinking params, tool_choice removal, sampling params, developer role, max_tokens
- `normalize_messages()` — developer→system
- `normalize_usage()` — cache hit/miss token parsing
- `resolve_model()` — legacy alias mapping

**调用方检查：**

| 文件 | 是否导入 DeepSeekAdapter | 如何构造 API 参数 |
|------|--------------------------|-------------------|
| `runtime.py` | ❌ 无 | `_apply_thinking_mode()` 手拼 |
| `client.py` | ❌ 无 | 直接透传 kwargs 到 OpenAI SDK |
| `agent.py` | ❌ 无 | 用 `_thinking_mode()` 传 thinking_mode 字符串 |

**结论：DeepSeekAdapter 是孤岛模块。所有主路径均绕过它。**

---

## 链路 4：ModelRegistry / Pricing / Cost / Budget

| 组件 | 定义位置 | 是否被主链路调用 |
|------|---------|-----------------|
| `ModelRegistry` | `deepseek/models.py` | ❌ 从未被 runtime/agent/client 调用 |
| `Pricing` | `deepseek/models.py` | ❌ 从未被调用 |
| `ModelSpec` | `deepseek/models.py` | ❌ 从未被调用 |
| `CostTracker` | `cost.py` | ❌ 未在 runtime 中使用 |
| `BudgetGuard` | `budget.py` | ❌ 未在 runtime 中使用 |
| `CostEstimator` | `budget.py` | ❌ 未在 runtime 中使用 |
| `PRICING` (agent) | `agent/agent.py` | ✅ `_result_from_runtime()` 使用硬编码价格 |
| `PRICING` (cost) | `cost.py` | 独立使用 |
| `_PRICING` (budget) | `budget.py` | 独立使用 |

**结论：ModelRegistry/Pricing/Budget 是孤岛。实际使用中的价格来自 `agent.py` 的硬编码字典（`PRICING`），与 `cost.py` 和 `budget.py` 各有自己的定价表，三处互不一致。**

具体不一致：
- `agent.py PRICING`: `deepseek-v4-flash.cached_input = 0.014`
- `cost.py PRICING`: `deepseek-v4-flash.cached_input = 0.002`
- `budget.py _PRICING`: `deepseek-v4-flash.cached_input = 0.014`

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

### 🔴 阻塞级（主链路断裂）

| # | 问题 | 影响 |
|---|------|------|
| 1 | **DeepSeekAdapter 未接入主链路** | 所有 DeepSeek 协议兼容逻辑沉在 adapter 中无人调用；runtime 仍手拼参数。thinking 参数、tool_choice 移除、developer role 转换全靠 `_apply_thinking_mode()` 和 adapter 的重复实现 |
| 2 | **ModelRegistry 未接入** | 三处独立定价表（agent/cost/budget），无单一来源 |
| 3 | **Budget preflight 未接入** | 没有请求前成本检查，可能意外超支 |

### 🟡 警告级（功能断裂）

| # | 问题 | 影响 |
|---|------|------|
| 4 | **approval_handler 未从 Agent 传入** | 需要审批的工具（write_file, python_exec）会因"无 handler"而失败，而非触发审批流程 |
| 5 | **ToolExecutor 未强制 max_input_bytes/max_output_bytes** | 策略字段定义了但 execute() 未检查；依赖隐式的 truncation |
| 6 | **chat_batch() 绕过 RetryExecutor** | batch 请求无重试/熔断保护 |
| 7 | **chat_batch() 不走 adapter + protocol validation** | batch 请求无协议校验 + 无 DeepSeek 兼容处理 |

### 🟢 已接通（无需修改）

| # | 链路 |
|---|------|
| 8 | PolicyEngine → ToolExecutor authorize() 强制执行 |
| 9 | 协议验证 → chat/chat_stream 每次 API 调用前 |
| 10 | RetryExecutor → 可重试状态码 + has_yielded 流保护 |
| 11 | 文件安全 → workspace_root + deny globs + 目录遍历阻断 |
| 12 | SSRF → fetch_url_hardened + validate_url_strict + trust_env=False |
| 13 | SQLite → tokenizer + authorizer + readonly URI |
| 14 | Python exec → NoSandbox 拒绝 + ProcessSandbox/ContainerSandbox |
| 15 | Builtin → Agent.allow_* 工具注册链完整 |
| 16 | content=None → "" 在 tool-call assistant 中修复 |

---

## 结论

SeekFlow **不是空架子**——核心请求链路和工具执行链路是贯通的，安全边界已嵌入正确位置。但它是**一只脚走路**：安全这条腿踩实了，协议/模型/成本这条腿悬空——DeepSeekAdapter、ModelRegistry、Budget/Cost 三个模块写了完整代码却从未接入主链路，属于"写好了没用"的孤岛代码。

如果现在接入真实 DeepSeek API，核心功能可以工作（Agent 发起请求 → 调用工具 → 返回结果），thinking mode 协议因 `_apply_thinking_mode()` 的辅助逻辑尚可维持正确性。但缺少成本保护和统一协议入口意味着：

- 价格不一致会给出错误的成本估算
- DeepSeek API 升级时需同时修改 `_apply_thinking_mode()` 和 `DeepSeekAdapter` 两处
- 没有请求前预算检查
