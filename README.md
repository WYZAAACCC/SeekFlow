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

**Benchmark: 6 scenarios × 4 frameworks, dual-judge scoring (deepseek-v4-pro)**

*24 runs, fixture search (deterministic), blind LLM judge + programmatic compliance judge*

### Mechanical scenarios — tool-intensive, structured output

*Fast excels here: comparable quality, 1.4–1.8× faster, lower cost*

| Scenario | SeekFlow Stable | SeekFlow Fast | LangChain | CrewAI |
|----------|:--:|:--:|:--:|:--:|
| **投资分析** (19 tools) | **8.8** · 167s · ¥0.018 | 5.6 · 62s · ¥0.006 | 5.8 · 73s · ¥0.007 | 6.3 · 62s · ¥0.006 |
| **供应链风险** (10 tools) | **9.1** · 166s · ¥0.017 | 6.2 · 56s · ¥0.006 | 6.3 · 75s · ¥0.007 | 6.2 · 96s · ¥0.009 |
| **资产再平衡** (33 tools) | **8.9** · 443s · ¥0.039 | 8.8 · 246s · **¥0.027** | 8.1 · 177s · ¥0.027 | 8.4 · 225s · ¥0.028 |
| **机械场景平均** | **8.9** · 259s · ¥0.025 | 6.9 · 121s · ¥0.013 | 6.7 · 108s · ¥0.014 | 7.0 · 128s · ¥0.014 |

### Extreme reasoning scenarios — trilemma, causal forensics, negotiation deadlock

*All frameworks perform similarly on v4-pro. Thinking adds latency without quality gain at this model tier.*

| Scenario | SeekFlow Stable | SeekFlow Fast | LangChain | CrewAI |
|----------|:--:|:--:|:--:|:--:|
| **三难困境** (6 tools) | 8.9 · 223s | 8.9 · 169s | 8.9 · 96s | 8.8 · 143s |
| **因果追踪** (6 tools) | 8.9 · 166s | 8.9 · 88s | 8.9 · 73s | 8.9 · 80s |
| **谈判僵局** (9 tools) | 8.9 · 434s | 8.7 · 87s | **8.9** · **104s** | **8.9** · 124s |
| **推理场景平均** | 8.9 · 274s | 8.8 · 115s | 8.9 · 91s | 8.9 · 116s |

### 综合（6 场景加权平均）

| Framework | Final | Qual | Cmp | 延迟 | 成本/task |
|-----------|:--:|:--:|:--:|------:|------:|
| **SeekFlow Stable** | **8.9** | 8.7 | 10.0 | 267s | ¥0.024 |
| SeekFlow Fast | 7.9 | 8.3 | 7.0 | 118s | **¥0.011** |
| CrewAI | 7.9 | 8.4 | 7.3 | 122s | ¥0.016 |
| LangChain | 7.8 | 8.3 | 7.1 | 100s | ¥0.014 |

*Scoring: mechanical scenarios = 70% report quality + 30% tool compliance; reasoning scenarios = 90% quality + 10% compliance. LLM judge is blind — it never sees which framework produced the output.*

> **关于 Fast 在金融/供应链场景得分偏低**：这两个场景中，SeekFlow Fast（max_steps=6）的模型倾向于不调用工具（TC=0），导致合规分被扣。这不是框架能力问题，而是受限步数下的模型策略选择。在资产再平衡场景中，Fast 调用全部 33 次工具并拿到 8.8 分（与 Stable 的 8.9 几乎持平）。实际使用中，`max_steps` 可按需调整。

### 可复现的 Demo

```bash
git clone https://github.com/WYZAAACCC/SeekFlow.git
cd SeekFlow
pip install -e .
export DEEPSEEK_API_KEY="sk-..."
export BENCH_SEARCH_BACKEND=fixture  # deterministic, no network dependency

# 完整 6 场景 × 4 框架 (24 runs, ~60 min)
python -m benchmarks.fair_comparison_v2.runner --rounds 1

# 快速验证 — 只跑机械场景
python -m benchmarks.fair_comparison_v2.runner --rounds 1 --scenarios financial_analyst,supply_chain_analyst,portfolio_rebalance
```

### 关键发现

- **Stable 是唯一工具合规满分的框架**：6 场景全部 10.0 分，证明工具真实执行且参数正确
- **Fast 在资产再平衡中追平 Stable**：8.8 vs 8.9，快 1.8×（246s vs 443s），成本低 32%
- **v4-pro 裸推理已足够强**：三个极端推理场景中所有框架持平（8.8–8.9），thinking 模式未带来质量增益，仅增加延迟
- **CrewAI 波动最大**：同场景中 token 消耗可达其他框架的 3×（资产再平衡 97K vs Fast 25K）
- **LangChain 速度最快**：平均 100s/task，但工具合规分偏低（7.1），因其模型较少主动调用工具

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

## Security Status (v0.3.7)

SeekFlow v0.3.7 is a **Level 3 candidate**:

**Supported (Lv2, production-ready):**
- Trusted local tools under ToolPolicy
- Policy-enforced execution with runner isolation
- ProcessRunner timeout kill + ContainerRunner container isolation
- Cache restricted to read/idempotent-network only
- No-policy tools denied by default

**Experimental (Lv3 candidate):**
- Manifest-based external tool registration
- ExternalToolRunner (containerized third-party tools with JSON protocol)
- MCPGateway (zero-trust MCP with tool freeze + mutation detection)
- EgressGateway + EgressSidecar (network boundary for external tools)
- SecretBroker (explicit secret injection, no ambient env)
- DurableAuditStore (JSONL + SQLite with hash chain)

**Not yet:**
- Egress sidecar not yet production-hardened for high-throughput
- Manifest signature verification requires cryptography package
- GitHub provenance / SBOM / signed releases pending
- Full Level 3 production-ready certification pending the above

## License

MIT
