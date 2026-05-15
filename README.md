# SeekFlow v0.3.7 — Level 3 Candidate

**DeepSeek-native &nbsp;|&nbsp; Zero-trust tool gateway &nbsp;|&nbsp; Runner-isolated &nbsp;|&nbsp; Fail-closed**

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/seekflow.svg)](https://pypi.org/project/seekflow/)

SeekFlow is a DeepSeek-native **zero-trust tool gateway** with policy-enforced execution, process isolation, and manifest-based external tool sandboxing. Purpose-built around DeepSeek's thinking mode, prompt caching, JSON repair, and FIM. **Not** a generic OpenAI wrapper.

> **Status**: main branch is **Level 3 candidate** (early production-grade untrusted tool runtime). Level 2 fully supported. Not yet full Level 3 production-ready — see [docs/security/levels.md](docs/security/levels.md).

**v0.3.7** introduces **Lv3 zero-trust architecture**: ToolManifest v1, ExternalToolRunner (containerized third-party tools), MCPGateway (zero-trust MCP), EgressGateway, SecretBroker, and DurableAuditStore. Lv2 security baseline is fully hardened with runner minimum isolation, ContainerRunner codegen-trusted gate, ProcessRunner output bounding, cache policy restrictions, and no-policy deny-by-default.

**Why SeekFlow over LangChain or CrewAI for DeepSeek?**

| | SeekFlow | LangChain | CrewAI |
|---|:--:|:--:|:--:|
| DeepSeek thinking management | Auto-detect + budget | Manual `extra_body` | Not supported |
| JSON repair (confidence-gated) | 8-rule + 4-level | None | None |
| Prompt cache stabilization | CacheCompiler (90%+ hit) | None | None |
| Circuit breaker (3-state) | ✅ | None | None |
| Policy Engine + ToolPolicy | ✅ | None | None |
| Path sandbox + SSRF protection | ✅ | None | None |
| Secret redaction pipeline | ✅ | None | None |
| Preflight cost budgeting | ✅ | Manual | Manual |
| FIM (Fill-in-the-Middle) | Built-in | None | None |
| Balance/cost tracking | Real-time cache-aware | Manual | Manual |

**Benchmark: 48 runs, 3 rounds × 4 scenarios, blind judge (deepseek-v4-pro)**

| Framework | Quality | Tokens/task | Cost/task | Time | Cache |
|-----------|:--:|------:|------|------|:--:|
| **SeekFlow Fast** | 8.7 | **8,688** | **CNY0.00108** | **49s** | **91%** |
| **SeekFlow Stable** | **8.8** | 12,945 | CNY0.00167 | 72s | 64% |
| LangChain | 8.8 | 10,231 | CNY0.00120 | 59s | 90% |
| CrewAI | 8.7 | 17,414 | CNY0.00149 | 72s | 90% |

---

## Quick Start

```bash
pip install seekflow
export DEEPSEEK_API_KEY="sk-..."
```

**Safe by default** — dangerous tools require explicit opt-in:

```python
from seekflow import DeepSeekAgent
from seekflow.types import ToolPolicy

agent = DeepSeekAgent(
    role="分析师",
    goal="分析数据并给出建议",
    backstory="经验丰富的数据分析师",
    model="deepseek-v4-pro",  # primary model for complex reasoning
)
agent.with_default_tools()  # only 'calculate' is loaded by default

# For file/network/code tools, opt in explicitly:
agent2 = DeepSeekAgent(
    role="研究员",
    goal="搜索并分析信息",
    backstory="资深研究员",
    dangerous_tools=True,  # explicit opt-in
)
agent2.with_default_tools()  # all 11 tools available
```

**Tool-level security with ToolPolicy:**

```python
from seekflow import tool
from seekflow.types import ToolPolicy

@tool(trusted=True)
def read_file(path: str) -> str:
    """Read a file within the workspace."""
    ...

td = read_file.with_policy(ToolPolicy(
    capabilities={"filesystem.read"},
    risk="read",
    workspace_root="/workspace",
    timeout_s=2.0,
    parallel_safe=True,
))
```

**Preflight cost control:**

```python
from seekflow.budget import CostBudget

budget = CostBudget(max_cny=0.20, max_prompt_tokens=200_000)
result = agent.run("Analyze Q3 financials", max_cost=budget.max_cny)
```

---

## Security Architecture (v0.3.7)

```
┌─────────────────────────────────────────────────┐
│  Agent Layer     Agent / Crew / Task / Graph    │
│                  Presets / Memory / Checkpoint   │
├─────────────────────────────────────────────────┤
│  Policy Layer    PolicyEngine.authorize()        │
│                  ToolPolicy (capability/risk)    │
│                  Normalized context (PR-4)       │
├─────────────────────────────────────────────────┤
│  Runtime         chat() / chat_stream()          │
│                  Thinking mode / Cache           │
│                  State machine (StepKind)        │
├─────────────────────────────────────────────────┤
│  Security        safe_join() / validate_url()    │
│                  redact_secrets()                │
│                  UntrustedContent wrapper        │
│                  close_object_schema (PR-5)      │
├─────────────────────────────────────────────────┤
│  Runners         InProcessRunner (trusted reads) │
│                  ProcessRunner (hard timeout)     │
│                  ContainerRunner (Docker, PR-2)  │
├─────────────────────────────────────────────────┤
│  Tool System     @tool → Schema → Registry       │
│                  Executor (repair + coerce)      │
│                  limits.py (PR-6)               │
│                  Audit trail + runner_name       │
├─────────────────────────────────────────────────┤
│  Sandbox         NoSandbox / LocalThread         │
│                  ProcessSandbox / Container      │
├─────────────────────────────────────────────────┤
│  DeepSeek API    DeepSeekClient                  │
│                  Thinking / FIM / Batch / Balance │
└─────────────────────────────────────────────────┘
```

---

## Features

### Security (new in v0.2.0)

| Feature | Description |
|---------|-------------|
| **Policy Engine** | Centralized authorization for every tool call |
| **ToolPolicy** | Capability, risk level, timeout, parallel-safety per tool |
| **Path Sandbox** | `safe_join()` blocks directory traversal |
| **SSRF Protection** | `validate_url()` blocks private IPs, localhost, metadata endpoints |
| **Secret Redaction** | API keys, JWTs, connection strings redacted from logs/traces |
| **Untrusted Content** | Tool outputs wrapped as data, not instructions |
| **Dangerous Tools Off** | File/network/code tools require `dangerous_tools=True` |
| **Per-Tool Timeout** | Hard timeout via ProcessRunner (terminate → kill); ContainerRunner for code_exec |
| **Audit Trail** | ToolAuditRecord with args/result hashes per execution |

### DeepSeek Thinking Mode — Fully Leveraged

```python
agent = DeepSeekAgent(thinking=True, mode="stable")

# New in v0.2.0: ThinkingRouter dynamically selects budget
from seekflow.reasoning import ThinkingRouter
router = ThinkingRouter()
decision = router.route(task="complex analysis", tools_count=5, max_risk="read")
# → ThinkingDecision(enable_thinking=True, budget_tokens=2048)
```

### JSON Repair Pipeline (confidence-gated)

4-level repair with dangerous-tool protection:

| Level | Method | Confidence | Dangerous tools |
|-------|--------|-----------|-----------------|
| 0 | `json.loads` native | 1.0 | ✅ Allowed |
| 1 | Syntactic repair | 0.60–0.99 | ❌ Denied if < 0.85 |
| 2 | Model re-emission | N/A | ✅ Allowed (expensive) |
| 3 | Fail-closed | 0.0 | ❌ Denied |

### Prompt Cache Compiler

```python
from seekflow.cache import CacheCompiler

compiler = CacheCompiler()
compiled = compiler.compile(system_prompt, tools_schema)
# → prefix_bytes, cacheable_byte_range, tools_schema_hash
prediction = compiler.predict_cache_hit(compiled, messages)
# → {"hit": True, "confidence": 1.0, "matched_bytes": 1247}
```

### Production Reliability

| Component | v0.3.7 Status |
|-----------|---------------|
| Tool Runners | InProcessRunner / ProcessRunner (hard kill) / ContainerRunner (Docker) |
| Schema Validation | Draft202012Validator + close_object_schema (hallucination defense) |
| Resource Limits | max_input_bytes / max_output_bytes enforced pre/post execution |
| Retry Control | Read tools + idempotent-only retry; side-effect tools execute once |
| Circuit Breaker | 3-state. Non-retryable errors excluded from upstream CB |
| Retry Executor | 429 bounded (attempt + deadline + Retry-After cap) |
| Cost Budget | Preflight estimation with hard stops |
| Context Window | Deep-copied messages, append-only compression |
| Trace Recorder | Full execution timeline with JSON export |
| State Machine | `RunState` + `StepKind` typed phases |

### Sandbox (code execution isolation)

```python
from seekflow.sandbox import NoSandbox, ProcessSandbox, ContainerSandbox

# Default: code execution denied
sandbox = NoSandbox()

# Development: subprocess with basic isolation
sandbox = ProcessSandbox()  # no inherited env, temp dir

# Production: Docker container with full isolation
sandbox = ContainerSandbox(image="python:3.11-slim")
# --network none, --memory 256m, --read-only, non-root user
```

---

## Breaking Changes (v0.2.0)

| Change | Migration |
|--------|-----------|
| `Agent.with_default_tools()` loads only `calculate` | Use `Agent(dangerous_tools=True)` for old behavior |
| `ToolCall.arguments` type: `dict` → `dict \| str` | Handle `isinstance(args, str)` for repair |
| `repair_message_order()` no semantic injection | No action — purely internal |
| `embed_files_into_message()` returns new dict | Assign return value instead of relying on mutation |
| `_sanitize_tool_output()` removed | Use `UntrustedContent` / `wrap_untrusted()` |

---

## Documentation

- [Changelog v0.2.0](docs/CHANGELOG-v020.md) — full release notes
- [Security Policy](docs/SECURITY.md) — vulnerability reporting + security model
- [PRD: Security Hardening](docs/PRD-security-production-hardening.md) — design decisions
- [Issues](docs/issues/) — 30 tracer-bullet issues with acceptance criteria
- [Tests](tests/) — 620+ tests covering security, retry, policy, tools, agent

## Security Status (v0.3.x)

SeekFlow v0.3.x supports **Level 2 semi-production** under these conditions:

- All tools must have ToolPolicy.
- `code_exec` and `destructive` require ContainerRunner / ContainerSandbox.
- Policy.runner cannot decrease the required isolation level (minimum isolation enforced).
- ContainerRunner only accepts tools with `ToolPolicy(trusted=True, container_codegen_trusted=True)`.
- ProcessRunner provides **timeout isolation**, not a full security sandbox.
- All ProcessRunner outputs are size-bounded in the child process.
- Tool outputs are untrusted by default (`trusted_output=False`).
- Cache is restricted to read tools or idempotent network with explicit opt-in.
- No-policy tools are denied by default (`allow_unsafe_no_policy_execution` opt-in).
- Network tools require allowed_domains.
- Filesystem tools require workspace_root.
- Untrusted third-party tools and arbitrary MCP servers are not supported.

## License

MIT
