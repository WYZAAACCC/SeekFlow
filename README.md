# SeekFlow v0.3.7

**DeepSeek-native zero-trust tool gateway — run DeepSeek agents in production without leaking secrets, escaping sandboxes, or blowing budgets.**

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/seekflow.svg)](https://pypi.org/project/seekflow/)

---

## What is SeekFlow?

**You want to give a DeepSeek agent access to files, network, and code execution — but safely.** LangChain and CrewAI are great multi-model orchestrators, but they weren't built with DeepSeek's thinking mode, prompt caching, or production security in mind. SeekFlow is the thinnest possible runtime that turns DeepSeek into a safe, cache-efficient, production-grade agent.

**Who is this for?** Developers deploying DeepSeek agents where mistakes cost money: reading customer files, calling internal APIs, running data pipelines, executing generated code.

```python
from seekflow import DeepSeekAgent

agent = DeepSeekAgent(role="analyst", goal="analyze data and give advice",
                       backstory="experienced data analyst",
                       api_key="sk-...", model="deepseek-v4-pro")
agent.with_default_tools()
result = agent.run("Calculate ROI: investment $500k, revenue $870k")
# → 3 lines. Safe by default. Cache-aware. Fail-closed.
```

> 🎬 **[30-second demo →](https://github.com/WYZAAACCC/SeekFlow#quick-start)** &nbsp; *(GIF coming soon)*

---

## Why SeekFlow?

| | SeekFlow | LangChain / CrewAI |
|---|---|---|
| **Design philosophy** | DeepSeek-native, thin runtime | Multi-model orchestration platform |
| **Thinking mode** | Auto-detect + budget | Manual `extra_body` config |
| **Prompt cache** | 90%+ hit rate (built-in stabilizer) | No cache stabilization |
| **Security model** | Zero-trust, fail-closed, deny-by-default | Reactive patches (6+ CVEs in 2026) |
| **Tool sandbox** | Path sandbox + SSRF protection + secret redaction | None built-in |
| **Code execution** | ProcessRunner (hard kill) + ContainerRunner (Docker) | Varies by integration |

**We don't compete on "better agents."** We compete on "agents you can actually deploy to production." SeekFlow is the security layer that LangChain/CrewAI agents need third-party add-ons to get.

> **LangChain CVE-2026-34070** (CVSS 7.5): path traversal in `load_prompt()`, can read arbitrary files.
> **CrewAI CVE-2026-2287** (CVSS 9.8): Docker sandbox silently falls back to insecure mode, enabling RCE.
> SeekFlow was built from day one to prevent exactly these classes of vulnerabilities — not patch them after disclosure.

---

## Quick Start

```bash
pip install seekflow
export DEEPSEEK_API_KEY="sk-..."
```

### 3-line agent

```python
from seekflow import DeepSeekAgent

agent = DeepSeekAgent(
    role="analyst", goal="analyze data and give advice", backstory="experienced data analyst",
    api_key="sk-...", model="deepseek-v4-pro",
)
agent.with_default_tools()  # loads calculate, parse_csv, extract_entities, classify_text

result = agent.run("Calculate the ROI: investment $500k, revenue $870k")
print(result.final_output)
```

### Add file, network, and code tools

```python
from seekflow import DeepSeekAgent
from seekflow.sandbox import ProcessSandbox

agent = DeepSeekAgent(
    role="researcher", goal="search and analyze information", backstory="senior researcher",
    api_key="sk-...", model="deepseek-v4-pro",
    dangerous_tools=True,  # explicit opt-in for file/network/code tools
)
agent.with_default_tools()                        # 4 safe tools
agent.allow_filesystem(root="/workspace")          # 3 file tools
agent.allow_network(domains={"api.example.com"})   # 1 network tool
agent.allow_python(sandbox=ProcessSandbox())       # 1 code tool
agent.allow_sqlite(root="/data", readonly=True)    # 1 SQL tool
# Total: 10 tools, all policy-enforced

result = agent.run("Search for recent news about AI and save the summary to workspace/report.md")
```

### Tool-level security with ToolPolicy

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

### Preflight cost control

```python
agent = DeepSeekAgent(..., thinking=True, mode="stable")
result = agent.run("Analyze Q3 financial performance", max_cost=0.20)  # hard stop at Y0.20
```

### More examples

| Example | What it shows |
|---------|---------------|
| [`examples/basic_deepseek_agent.py`](examples/basic_deepseek_agent.py) | 3-line agent, tool loading, cost tracking |
| [`examples/prompt_cache_demo.py`](examples/prompt_cache_demo.py) | 90%+ cache hit rate, cost savings |
| [`examples/safe_tool_calling_demo.py`](examples/safe_tool_calling_demo.py) | Path sandbox, SSRF protection, secret redaction |

---

## Features

### Security

| Feature | Description |
|---------|-------------|
| **Policy Engine** | Centralized authorization for every tool call |
| **ToolPolicy** | Capability, risk level, timeout, parallel-safety per tool |
| **Path Sandbox** | `safe_join()` blocks directory traversal |
| **SSRF Protection** | `validate_url()` blocks private IPs, localhost, metadata endpoints |
| **Secret Redaction** | API keys, JWTs, connection strings redacted from logs/traces |
| **Untrusted Content** | Tool outputs wrapped as data, not instructions |
| **Dangerous Tools Off** | File/network/code tools require `dangerous_tools=True` |
| **Per-Tool Timeout** | Hard timeout via ProcessRunner (terminate → kill) |
| **Audit Trail** | ToolAuditRecord with args/result hashes per execution |

### DeepSeek Thinking Mode

```python
agent = DeepSeekAgent(thinking=True, mode="stable")
```

| Component | v0.3.7 Status |
|-----------|---------------|
| Thinking auto-detection | Detects model support, sets budget |
| Reasoning consistency check | Detects tool/reasoning mismatches |
| Reasoning harvest | Extracts subgoals, hypotheses, uncertainties |
| Thinking budget control | Per-call token budget via ThinkingRouter |

### JSON Repair Pipeline (confidence-gated)

| Level | Method | Confidence | Dangerous tools |
|-------|--------|-----------|-----------------|
| 0 | `json.loads` native | 1.0 | Allowed |
| 1 | Syntactic repair | 0.60–0.99 | Denied if < 0.85 |
| 2 | Fail-closed | 0.0 | Denied |

### Prompt Cache Compiler

```python
from seekflow.cache import CacheCompiler

compiler = CacheCompiler()
compiled = compiler.compile(system_prompt, tools_schema)
prediction = compiler.predict_cache_hit(compiled, messages)
# → {"hit": True, "confidence": 1.0, "matched_bytes": 1247}
```

CacheCompiler keeps DeepSeek's prefix-based cache stable — 90%+ hit rate on repeated agent runs with the same system prompt and tool schema.

### Production Reliability

| Component | v0.3.7 Status |
|-----------|---------------|
| Tool Runners | InProcessRunner / ProcessRunner (hard kill) / ContainerRunner (Docker) |
| Schema Validation | Draft202012Validator + close_object_schema (hallucination defense) |
| Resource Limits | max_input_bytes / max_output_bytes enforced pre/post execution |
| Retry Control | Read + idempotent-only retry; side-effect tools execute once |
| Circuit Breaker | 3-state. Non-retryable errors excluded from upstream CB |
| Cost Budget | Preflight estimation with hard stops |
| Context Window | Deep-copied messages, append-only compression |
| Trace Recorder | Full execution timeline with JSON export |

### Sandbox (code execution isolation)

```python
from seekflow.sandbox import NoSandbox, ProcessSandbox, ContainerSandbox

# Development: subprocess with basic isolation
sandbox = ProcessSandbox()

# Production: Docker container with full isolation
sandbox = ContainerSandbox(image="python:3.11-slim")
# --network none, --memory 256m, --read-only, non-root user
```

---

## Benchmark

**6 scenarios × 4 frameworks, dual-judge scoring (deepseek-v4-pro)** — [full results →](benchmarks/fair_comparison_v2/)

| Framework | Final Score | Quality | Compliance | Latency | Cost/task |
|-----------|:--:|:--:|:--:|------:|------:|
| **SeekFlow Stable** | **8.9** | 8.7 | 10.0 | 267s | Y0.024 |
| SeekFlow Fast | 7.9 | 8.3 | 7.0 | 118s | Y0.011 |
| CrewAI | 7.9 | 8.4 | 7.3 | 122s | Y0.016 |
| LangChain | 7.8 | 8.3 | 7.1 | 100s | Y0.014 |

### Key findings

- **Stable is the only framework with perfect tool compliance** (10.0 across all 6 scenarios)
- **v4-pro raw reasoning is already strong** — thinking mode adds latency without quality gain on report-writing tasks
- **Thinking proves its value in code repair tasks** — our [Thinking Stress Benchmark](benchmarks/thinking_stress_v1/) shows +3% hidden test pass rate improvement
- **Fast mode is 1.8× faster** than Stable with comparable quality on mechanical tasks

```bash
# Reproduce the benchmark
git clone https://github.com/WYZAAACCC/SeekFlow.git
cd SeekFlow && pip install -e .
export DEEPSEEK_API_KEY="sk-..."
export BENCH_SEARCH_BACKEND=fixture
python -m benchmarks.fair_comparison_v2.runner --rounds 1
```

---

## Security Architecture

```
┌─────────────────────────────────────────────────┐
│  Agent Layer     Agent / Crew / Task / Graph    │
│                  Memory / Checkpoint             │
├─────────────────────────────────────────────────┤
│  Policy Layer    PolicyEngine.authorize()        │
│                  ToolPolicy (capability/risk)    │
├─────────────────────────────────────────────────┤
│  Runtime         chat() / chat_stream()          │
│                  Thinking mode / Cache           │
├─────────────────────────────────────────────────┤
│  Security        safe_join() / validate_url()    │
│                  redact_secrets()                │
│                  UntrustedContent wrapper        │
├─────────────────────────────────────────────────┤
│  Runners         InProcessRunner (trusted reads) │
│                  ProcessRunner (hard timeout)     │
│                  ContainerRunner (Docker)        │
├─────────────────────────────────────────────────┤
│  Tool System     @tool → Schema → Registry       │
│                  Executor (repair + coerce)      │
│                  Audit trail                     │
├─────────────────────────────────────────────────┤
│  Sandbox         NoSandbox / ProcessSandbox      │
│                  ContainerSandbox                │
├─────────────────────────────────────────────────┤
│  DeepSeek API    DeepSeekClient                  │
│                  Thinking / FIM / Batch / Balance │
└─────────────────────────────────────────────────┘
```

---

## Roadmap

| Version | Focus | Key Deliverables |
|---------|-------|-----------------|
| **v0.4** | Stable runtime | Cache stabilization GA, ProcessRunner hardening, FIM production support |
| **v0.5** | MCP sandbox | MCPGateway tool freeze + mutation detection, EgressGateway hardening, external tool attestation |
| **v0.6** | Production security | DurableAuditStore (JSONL + SQLite hash chain), manifest signature verification, SBOM, signed releases |

See [issues/](docs/issues/) for detailed tracer-bullet issues with acceptance criteria.

---

## Documentation

- [Why SeekFlow?](docs/why-seekflow.md) — design philosophy and comparison
- [Security Levels](docs/security/levels.md) — Lv2 production-ready vs Lv3 candidate
- [Changelog v0.2.0](docs/CHANGELOG-v020.md) — full release notes
- [Security Policy](docs/SECURITY.md) — vulnerability reporting
- [Tests](tests/) — 620+ tests covering security, retry, policy, tools, agent

## License

MIT
