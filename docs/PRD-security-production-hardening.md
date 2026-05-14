# SeekFlow v0.2.0 — 安全加固与生产化 PRD

## Problem Statement

SeekFlow 当前声称 "Production-grade reliability" 但存在 10 个 P0 级生产阻断缺陷，包括：重试逻辑无限循环、CircuitBreaker 错误累积、默认危险工具无权限模型、JSON 参数在 Client 层被静默丢弃为 `{}`、Prompt Injection 防护仅为正则黑名单、工具执行无超时与隔离、文件读取无路径沙箱、成本控制仅做事后统计、SSRF 攻击面暴露、全链路缺 secret redaction。

同时，README 宣称的 "6 deps" 与实际 9 个核心依赖不符；mypy strict 设置下大量核心模块被 `ignore_errors`；项目 classifier 标为 Beta 但 README 标榜 Production-grade。SeekFlow 在 DeepSeek 专属优化（thinking mode、prompt cache、JSON repair、FIM、batch、balance）方向上有真实价值，但必须完成安全与工程化补课才能支撑生产级定位。

## Solution

分三个阶段将 SeekFlow 从当前 Beta 状态提升至可内部生产使用（v0.2.0），并规划极致方向（v0.3.0+）。P0 阶段修复 10 个生产阻断缺陷，补全回归测试；P1 阶段构建安全工具系统（Policy Engine、ToolPolicy、沙箱），重构 Runtime 为显式状态机；P2 阶段打造 DeepSeek 专属竞争力（Prompt Cache Compiler、Thinking Budget Router、安全 Tool Sandbox、可信 Search 层、StateGraph Agent）。

## User Stories

### P0 — 生产阻断修复

1. As a production operator, I want retry logic to respect max_retries even when receiving continuous 429 responses, so that my service threads are not permanently occupied.
2. As a reliability engineer, I want the CircuitBreaker to reset failure_count on any successful request (not only in half_open), so that occasional intermittent failures don't cause false-positive circuit opens.
3. As a security-conscious developer, I want non-retryable errors (400/401/403) to NOT count against the upstream circuit breaker, so that my own auth/config mistakes don't trip the breaker for the DeepSeek service.
4. As a security engineer, I want dangerous tools (file read, web fetch, Python exec, SQL query) to be disabled by default and require explicit opt-in with a scoped policy, so that prompt injection cannot trivially exfiltrate secrets or execute code.
5. As a developer, I want malformed JSON in tool call arguments to be preserved (not dropped to `{}`), so that the downstream repair pipeline can attempt to salvage them.
6. As a security engineer, I want tool outputs to be wrapped as untrusted data with provenance metadata, rather than relying on regex blocklists that still leak the first 200 characters of malicious content.
7. As a cost-conscious user, I want a preflight cost estimate that blocks or downgrades requests exceeding my budget BEFORE the API call is made, rather than only warning after the fact.
8. As a platform operator, I want every tool to have an independent timeout, so that a single hung tool doesn't block the entire agent run.
9. As a compliance officer, I want secrets, tokens, and connection strings to be automatically redacted from error messages, logs, traces, and tool results before they enter the model's context.
10. As a security auditor, I want file reads sandboxed to a configurable workspace root with extension allowlisting and sensitive-file blocking, so that read_file cannot read `.env` or SSH keys.

### P1 — 安全工具系统 + Runtime 重构

11. As a framework user, I want every tool to declare its capabilities, risk level, timeout, parallel-safety, and approval requirement via a ToolPolicy, so that the runtime can enforce safety automatically.
12. As a security reviewer, I want a centralized Policy Engine that authorizes every tool call before execution, so that access decisions are consistent and auditable.
13. As a developer building multi-turn agents, I want the runtime to deep-copy user-provided messages instead of mutating them in place, so that my caller can safely reuse message objects.
14. As a framework user, I want the runtime to have an explicit state machine (PREPARE → MODEL_CALL → PARSE → VALIDATE → EXECUTE → APPEND → FINALIZE) instead of a raw while-loop, so that each phase is independently traceable, testable, and swappable.
15. As a developer, I want the runtime to force `tool_choice=none` on the penultimate step (when max_steps is approaching), so that the model synthesizes a final answer instead of returning "stopped."
16. As a framework user, I want `repair_message_order` to only perform protocol-required fixes (orphaned tool messages, role ordering) and never inject semantic instructions like "Please continue."
17. As a developer, I want tool execution to respect dependency ordering — side-effect tools execute serially by default, while pure/idempotent tools can be parallelized.
18. As a security engineer, I want URL fetching to block all private/internal IP ranges, localhost, metadata endpoints, and non-http/https schemes by default.
19. As a security engineer, I want Python code execution to be disabled by default and only available with sandbox isolation (container/jail, no network, no inherited env, resource limits).
20. As an operator, I want comprehensive tool audit trails: tool name, args hash, result hash, latency, policy decision, and approval record for every execution.
21. As a developer, I want JSON repair to produce a confidence score, and dangerous tools to REQUIRE model re-emission or human approval when repair confidence is below threshold (0.85).
22. As a framework user, I want MCP server connections to have explicit trust levels, capability allowlists, startup timeouts, and schema validation — with failures surfaced as observable errors rather than silently swallowed.
23. As a developer, I want the search module to provide provenance metadata (source URL, fetched_at, content hash, trust level, freshness) for every result, rather than raw regex-scraped text.
24. As a user, I want files embedded into messages to have per-file size caps, total size caps, page count limits, and token count limits — with binary/image content never blindly base64-encoded into text prompts.

### P2 — 极致方向

25. As a cost-sensitive user, I want a Prompt Cache Compiler that byte-level analyzes my system prompt + tools to maximize cache prefix stability, shows me cache ROI, and warns me what will invalidate the cache.
26. As a power user, I want a Thinking Budget Router that dynamically decides whether to enable thinking, the thinking budget, whether to self-consistency sample, and whether to compress reasoning — based on task complexity, tool risk, expected cost, and latency SLA.
27. As a platform operator, I want tool execution in isolated sandbox workers with no inherited environment, read-only workspace mounts, seccomp/container/jail, network policy, and resource caps (CPU, memory, file size, process count).
28. As a developer building RAG applications, I want a trusted search pipeline (search → fetch → clean → chunk → rank → cite → verify → answer) with citation spans and content hashes, replacing the current regex-scraping approach.
29. As a developer building complex multi-step agents, I want a StateGraph execution model with typed state, checkpoint/resume, deterministic replay, budget-aware scheduling, per-node retry/fallback, and node-level tracing.
30. As a DevOps engineer, I want `seekflow serve`, `seekflow eval`, `seekflow trace view`, `seekflow cache inspect`, and `seekflow harden` CLI commands for operating SeekFlow in production.

## Implementation Decisions

### Module Architecture

The hardening work is organized into these new or significantly modified modules:

**New modules:**
- `seekflow.policy` — Policy Engine, ToolPolicy, authorization decision pipeline
- `seekflow.security` — Path sandbox (`safe_join`), URL allowlist/SSRF blocker, secret redaction, input validation
- `seekflow.sandbox` — Tool process worker abstraction (local thread fallback, container target)
- `seekflow.budget` — Preflight cost estimator, CostBudget with hard stops
- `seekflow.state` — RunState, StepKind enum, explicit state machine transitions

**Significantly modified modules:**
- `seekflow.client` — Preserve raw tool arguments, add RequestContext, unified error taxonomy
- `seekflow.retry_executor` — Fix 429 infinite loop, fix circuit breaker, filter non-retryable from upstream CB
- `seekflow.retry` — `record_success()` resets failure_count in ALL states
- `seekflow.runtime` — Extract state machine, deep-copy messages, force final synthesis, remove semantic message injection
- `seekflow.tools.executor` — Per-tool timeout, policy gate integration, side-effect awareness, audit trail
- `seekflow.tools.schema` — Pydantic-first schema, `additionalProperties: false`, canonical JSON sort
- `seekflow.agent.agent` — Default tools OFF, `dangerous_tools` flag, ToolPolicy integration
- `seekflow.agent.builtins` — All tools require explicit policy; run_python disabled by default
- `seekflow.repair.json_repair` — Add confidence scoring, repair levels (0-3), dangerous-tool gating
- `seekflow.files` — Workspace root, extension allowlist, size/page/token limits, deep-copy messages
- `seekflow.mcp.executor` — Trust levels, capability allowlists, startup timeout, schema validation, error observability
- `seekflow.cache` — Prefix compiler, cache ROI stats, invalidation reason tracking
- `seekflow.trace.recorder` — OpenTelemetry spans, metrics, structured logs, PII redaction, trace sampling

### Key Design Decisions

**D-1: RetryExecutor 修复**
429 响应必须计入 attempt 并受 total_deadline 约束；CircuitBreaker.record_success() 在所有状态下重置 failure_count 为 0；非重试型 HTTP 状态码（400/401/402/403/404）不计入 upstream circuit breaker。

**D-2: ToolArguments 保留原始值**
目前 `DeepSeekClient.chat()` 在 `json.JSONDecodeError` 时将 `parsed_args = {}`，导致下游 repair 机制无法工作。改为保留 `raw_args` 字符串传给 `ToolCall.arguments`（支持 `str | dict`），由 `ToolExecutor._parse_arguments` 统一处理 repair。

**D-3: 默认工具安全模型**
`Agent.with_default_tools()` 改为默认仅加载 `calculate`（AST 安全计算器）。其他工具通过 `dangerous_tools=True` 显式开启，且每个危险工具必须携带 `ToolPolicy`。提供 `safe_read_file(root=...)`, `safe_fetch_url(allow_domains=...)` 等安全变体。

**D-4: Policy Engine 设计**
每一次工具调用在执行前必须通过 Policy Engine 授权：

```
decision = policy_engine.authorize(tool_def, args, run_context)
# → Allowed | Denied(reason) | ApprovalRequired(decision)
```

Policy Engine 检查：capability 匹配、workspace root 边界、URL domain/IP allowlist、参数大小、timeout、并发安全性、是否需要 human approval。

**D-5: Runtime 状态机**
将当前的 `while step < max_steps` 循环分解为显式状态：

```
PREPARE → MODEL_CALL → PARSE_RESPONSE → [TOOL_CALLS | FINALIZE]
TOOL_CALLS → VALIDATE → POLICY_GATE → EXECUTE → APPEND_RESULTS → PREPARE
```

每个状态可独立 trace、测试、替换。RunState 是 typed pydantic model，支持 checkpoint/resume。

**D-6: JSON Repair 分级**
```
Level 0: json.loads — 原生解析成功，confidence=1.0
Level 1: Safe syntactic repair — 仅修复引号/尾逗号/括号，confidence 0.85-0.99
Level 2: Model re-emission — 请求模型重新输出合法 JSON
Level 3: Human approval / fail-closed
```

危险工具（write/network/code_exec/destructive）只允许 Level 0 或 Level 2，不允许静默 Level 1 repair。

**D-7: 成本前置预算**
```python
@dataclass
class CostBudget:
    max_cny: float
    max_prompt_tokens: int
    max_completion_tokens: int
    max_tool_calls: int
    max_wall_time_s: int

class CostEstimator:
    def estimate(messages, model, thinking_budget, max_steps) -> PreflightEstimate
    # Returns: lower_bound_cost, upper_bound_cost, estimated_tokens
```

在每次 API 调用前执行 estimate；若 `upper_bound_cost > budget.max_cny`，根据策略选择：拒绝请求、降级模型、减少上下文、或请求 human approval。

**D-8: 文件处理安全化**
- `safe_join(root, user_path)` 使用 `Path.resolve()` + `is_relative_to()` 防路径遍历
- 默认禁止读取 `.env`, `*.key`, `*.pem`, `*.sqlite`, `*.db`, `*.log`, binary 文件
- 单文件大小上限（默认 5MB）、总文件大小上限（默认 20MB）、PDF 页数上限（默认 50 页）、token 上限
- `embed_files_into_message` 必须 deep-copy 输入 message，不修改原始对象
- PDF 解析加入 zip bomb / malformed PDF 防护

**D-9: SSRF 防护**
URL fetch 默认阻断以下目标：
- localhost / 127.0.0.0/8
- 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
- 169.254.0.0/16 (link-local)
- IPv6 loopback / link-local
- file://, gopher://, ftp:// schemes
- DNS rebinding 检测（resolve → 再次验证 IP）

**D-10: Secret Redaction**
在 error/result/log/trace 全链路自动脱敏：
- API key 模式 (`sk-*`, `Bearer *`)
- 环境变量值（匹配已知 secret key 名）
- 数据库连接字符串
- AWS/GCP/Azure credential 模式
- JWT token 模式

### Schema Changes

**ToolDefinition 扩展:**

```python
class ToolPolicy(BaseModel):
    capabilities: set[str] = Field(default_factory=set)
    risk: Literal["read", "write", "network", "code_exec", "destructive"] = "read"
    timeout_s: float = 30.0
    max_input_bytes: int = 1_000_000
    max_output_bytes: int = 100_000
    parallel_safe: bool = False
    requires_approval: bool = False
    allowed_domains: set[str] = Field(default_factory=set)
    workspace_root: Path | None = None

class ToolDefinition(BaseModel):
    # ... existing fields ...
    policy: ToolPolicy | None = None  # NEW: None = use default restrictive policy
```

**RunState 引入:**

```python
class StepKind(Enum):
    PREPARE = "prepare"
    MODEL_CALL = "model_call"
    PARSE_RESPONSE = "parse_response"
    VALIDATE_TOOL_CALLS = "validate_tool_calls"
    POLICY_GATE = "policy_gate"
    EXECUTE_TOOLS = "execute_tools"
    APPEND_RESULTS = "append_results"
    FINALIZE = "finalize"

class RunState(BaseModel):
    run_id: str
    step: int
    current_phase: StepKind
    messages: list[Message]
    budget: BudgetState
    tool_results: list[ToolExecutionResult]
    errors: list[RuntimeErrorRecord]
    trace_id: str
    checkpoint_data: dict = Field(default_factory=dict)
```

### API Contracts

**Breaking changes (v0.2.0):**
- `Agent.with_default_tools()` 默认不再加载 read_file/web_search/download_page/save_result/fetch_url/run_python/query_sql
- `ToolCall.arguments` 从 `dict` 改为 `dict | str`（保留 raw JSON 字符串）
- `repair_message_order` 不再注入 "Please continue." 语义消息
- `embed_files_into_message` 不再原地修改传入的 message dict，改为返回新 dict
- MCP `connect_and_register` 失败时不再静默 `continue`，改为记录错误并允许配置 fail-fast

**New public APIs:**
- `seekflow.policy.PolicyEngine.authorize(tool_def, args, context) -> PolicyDecision`
- `seekflow.security.safe_join(root, user_path) -> Path`
- `seekflow.security.validate_url(url, allow_domains, allow_ips) -> bool`
- `seekflow.security.redact_secrets(text) -> str`
- `seekflow.budget.CostEstimator.estimate(messages, model, ...) -> PreflightEstimate`
- `seekflow.cache.CacheCompiler.compile(system, tools, strategy) -> CompiledPrefix`
- `Agent(dangerous_tools=True)` 参数
- `ToolDefinition.with_policy(policy)` builder method

## Testing Decisions

### What makes a good test

- Tests verify external behavior (the contract), not implementation details
- Security tests must test negative cases: path traversal attempts, SSRF payloads, prompt injection strings
- Retry tests must verify timing invariants (max attempts, max delay, deadline) with controlled error injection
- Each P0 fix must have at least one regression test that fails before the fix and passes after
- Use the existing `tests/` directory structure: `tests/test_retry.py`, `tests/test_security.py`, `tests/test_tools.py`, etc.

### Modules to test

| Module | Test file | Test focus |
|--------|-----------|------------|
| `seekflow.retry_executor` | `tests/test_retry.py` | 429 bounded retry, CB success reset, non-retryable exclusion |
| `seekflow.client` | `tests/test_client.py` | Raw args preservation, error taxonomy |
| `seekflow.security` | `tests/test_security.py` | Path traversal, SSRF blocking, secret redaction |
| `seekflow.policy` | `tests/test_policy.py` | Authorization decisions, capability checks |
| `seekflow.tools.executor` | `tests/test_tools.py` | Per-tool timeout, policy gate, repair gating |
| `seekflow.repair.json_repair` | `tests/test_repair.py` | Confidence scoring, repair levels |
| `seekflow.runtime` | `tests/test_runtime.py` | State machine transitions, deep copy, final synthesis |
| `seekflow.files` | `tests/test_files.py` | Workspace boundary, size limits, deep copy |
| `seekflow.budget` | `tests/test_budget.py` | Preflight estimation, hard stops |
| `seekflow.cache` | `tests/test_cache.py` | Prefix compilation, invalidation detection |

Specific regression tests required:
- 持续 429 不超过 max_retries + total_deadline
- `record_success()` 在 CLOSED 状态清空 failure_count
- malformed JSON arguments 能进入 repair pipeline（不被 client 层丢弃为 {}）
- `../` 路径遍历被 `safe_join` 拒绝
- localhost/private IP URL 被 `validate_url` 拒绝
- `dangerous_tools=False`（默认）时危险工具不可用
- 工具执行超时能终止并返回错误
- `embed_files_into_message` 不修改原始 message dict
- secret 模式在 trace/log/error 中被替换为 `[REDACTED]`

### Prior art

现有测试文件 `tests/test_retry.py`, `tests/test_tool_registry.py`, `tests/test_strict_checker.py`, `tests/test_trace.py`, `tests/test_mcp_*.py` 使用标准 pytest + 内存 mock 模式，新测试延续此风格。

## Out of Scope

以下内容不在本次 PRD 范围内：

1. **Docker 镜像 / Helm Chart / K8s 部署** — P1 部署自动化在本文档仅做架构预留，不实现。
2. **OpenAI-compatible 服务端点 (`seekflow serve`)** — P2 服务化内容，仅做接口预留。
3. **Tenant/project/API key 多租户管理** — 超出当前单用户框架定位。
4. **Admin UI / Trace Viewer 前端** — P2 内容，仅预留 CLI 骨架。
5. **Vector store / Embedding 生产实现** — 当前 `compat/` 下的向量存储仅保留兼容接口，不做生产级实现。
6. **LangChain / CrewAI 深度集成** — `compat/` 兼容层维护现状，不新增功能。
7. **Memory 生产后端（SQLite/Postgres/TTL/加密）** — 当前 memory 足够 demo 使用，生产化在后续 PRD。
8. **SBOM / 依赖签名 / SLSA 供应链证明** — P1 CI/CD 完成后单独评估。
9. **Graph/Crew/Task 完整实现** — 仅 StateGraph 进入 P2 设计范围，Crew 和 Task DSL 不做。
10. **Async 运行时的安全与状态机** — AsyncToolRuntime 在 sync 版本稳定后再同步改造。

## Further Notes

### 执行路线图

| 周次 | 阶段 | 关键交付 |
|------|------|---------|
| 第 1 周 | P0 修复 | 10 个 P0 bug 修复 + 回归测试，mypy 通过核心模块 |
| 第 2-3 周 | P1 安全工具系统 | Policy Engine, ToolPolicy, SSRF 防护, Path 沙箱, Secret Redaction, dangerous_tools flag |
| 第 4-5 周 | P1 Runtime 重构 | 状态机, deep copy, message repair 修复, 工具并发感知, tool timeout |
| 第 6-7 周 | P1-P2 观测性+缓存+预算 | OpenTelemetry, structured logs, preflight cost, Prompt Cache Compiler, trace viewer |
| 第 8 周 | 发布准备 | v0.2.0 release, CHANGELOG, security policy, threat model, hardening guide, CI badges |

### 验收标准

**P0 验收（第 1 周末）：**
- `pytest tests/test_retry.py tests/test_security.py tests/test_tools.py tests/test_client.py` 全绿
- `mypy src/seekflow/retry.py src/seekflow/client.py src/seekflow/tools/ --strict` 零错误
- 10 个新回归测试全部覆盖审计报告指出的 P0 缺陷

**P1 验收（第 5 周末）：**
- 所有工具带 ToolPolicy，PolicyEngine 覆盖全部工具执行路径
- Runtime 状态机可 trace、可单步调试
- `mypy src/seekflow/ --strict` 移除所有核心模块 ignore_errors
- CI matrix: Python 3.10-3.13, ruff, mypy, pytest, coverage >= 80%

**发布前验收（第 8 周末）：**
- v0.2.0 changelog 完整记录所有 breaking changes
- Security policy (SECURITY.md) 发布
- Threat model 文档完成
- Hardening guide 覆盖所有 P0-P1 安全措施
- Benchmark 可复现，公开数据集和统计方法
- CI badges (tests, coverage, mypy, ruff) 全绿
- 所有 examples 更新至安全 API
