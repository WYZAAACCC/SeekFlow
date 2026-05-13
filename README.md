# SeekFlow

**🔥 DeepSeek-native &nbsp;|&nbsp; ⚡ Lightweight (6 deps) &nbsp;|&nbsp; 🛡️ Production-grade reliability**

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-418%20passed-brightgreen.svg)](tests/)
[![DeepSeek](https://img.shields.io/badge/DeepSeek-Native-536DFE.svg)](https://platform.deepseek.com/)

SeekFlow is the only agent framework architected around DeepSeek's actual behavior — thinking mode, prompt caching, JSON repair, FIM. Not a generic OpenAI wrapper with DeepSeek as an afterthought.

**Why SeekFlow over LangChain or CrewAI for DeepSeek?**

| | SeekFlow | LangChain | CrewAI |
|---|:--:|:--:|:--:|
| DeepSeek thinking management | Auto-detect + budget | Manual `extra_body` | Not supported |
| JSON repair | 8-rule state machine | None | None |
| Prompt cache stabilization | CacheStabilizer (90%+ hit) | None | None |
| Circuit breaker | 3-state | None | None |
| FIM (Fill-in-the-Middle) | Built-in | None | None |
| Balance/cost tracking | Real-time cache-aware | Manual | Manual |
| Dependencies | **6** | 40+ | 30+ |

**Benchmark: 48 runs, 3 rounds × 4 scenarios, blind judge (deepseek-v4-pro)**

| Framework | Quality | Tokens/task | Cost/task | Time | Cache |
|-----------|:--:|------:|------|------|:--:|
| **SeekFlow Fast** | 8.7 | **8,688** | **CNY0.00108** | **49s** | **91%** |
| **SeekFlow Stable** | **8.8** | 12,945 | CNY0.00167 | 72s | 64% |
| LangChain | 8.8 | 10,231 | CNY0.00120 | 59s | 90% |
| CrewAI | 8.7 | 17,414 | CNY0.00149 | 72s | 90% |

SeekFlow Fast: **15% fewer tokens, 10% lower cost** than LangChain. SeekFlow Stable: **tied for #1 quality** with deep reasoning throughout.

| Scenario | DTK Fast | DTK Stable | LangChain | DTK优势 |
|------|:--:|:--:|:--:|------|
| 金融分析 | 8.4 | 8.5 | 8.8 | LangChain微弱领先 |
| 供应链 | 8.4 | 8.7 | 9.1 | LangChain web_search优势 |
| **代码审计** | **9.1** | 8.9 | 8.7 | **DTK 2x token效率** |
| **研究综合** | 8.9 | **9.2** | 8.6 | **DTK Stable显著领先** |

---

## Quick Start

```bash
pip install seekflow
export DEEPSEEK_API_KEY="sk-..."
```

```python
from seekflow import tool, ToolRuntime

@tool
def get_weather(city: str) -> dict:
    """Get current weather for a city."""
    return {"city": city, "temperature": 22, "condition": "sunny"}

@tool
def calculate(expression: str) -> str:
    """Safely evaluate a math expression using AST whitelist."""
    ...

runtime = ToolRuntime(tools=[get_weather, calculate])
result = runtime.chat(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "北京天气？算一下 (8630-3120)/8630"}],
)
print(result.final)
```

**Agent mode** (role/goal/backstory + autonomous tool use):

```python
from seekflow import DeepSeekAgent
from seekflow.agent.presets import financial_analyst

agent = financial_analyst(api_key="sk-...")
agent.add_tool(get_weather)
result = agent.run("分析北京天气对投资的影响")
print(result.final_output)  # structured investment memo
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Agent Layer     Agent / Crew / Task / Graph    │
│                  Presets / Memory / Checkpoint   │
├─────────────────────────────────────────────────┤
│  Runtime         chat() / chat_stream()          │
│                  Hybrid thinking / Cache         │
├─────────────────────────────────────────────────┤
│  Reliability     Retry + CircuitBreaker          │
│                  ToolCache (LRU+TTL)             │
│                  Context window management        │
├─────────────────────────────────────────────────┤
│  Tool System     @tool → Schema → Registry       │
│                  Executor (repair + coerce)      │
│                  Strict mode checker             │
├─────────────────────────────────────────────────┤
│  Repair          JSON repair (8 rules)           │
│                  Type coercion (int/float/bool)  │
│                  Prompt injection filter          │
├─────────────────────────────────────────────────┤
│  DeepSeek API    DeepSeekClient                  │
│                  Thinking / FIM / Batch / Balance │
└─────────────────────────────────────────────────┘
```

---

## Features

### DeepSeek Thinking Mode — Fully Leveraged

Thinking stays enabled throughout the conversation for deep reasoning. `budget_tokens=2048` caps per-step cost. Reasoning content is compressed for efficient passback. Stable mode achieves top quality (8.8) across all scenarios.

```python
agent = DeepSeekAgent(thinking=True, mode="stable")  # thinking throughout + budget control
```

### JSON Repair Pipeline

8 rules with a state machine that tracks both single- and double-quote contexts. LIFO stack for brace closure. Function-call syntax converter. Handles every known DeepSeek malformed-JSON pattern.

| Rule | Example Input | Repaired |
|------|--------------|----------|
| Markdown fences | ` ```json\n{...}\n``` ` | `{...}` |
| Function-call syntax | `fn(city="Beijing")` | `{"city":"Beijing"}` |
| Single quotes | `{'key':'val'}` | `{"key":"val"}` |
| Missing braces | `{"a":[1,{"b":2` | `{"a":[1,{"b":2}]}` |

### Prompt Cache Stabilization

DeepSeek caches from byte 0. SeekFlow freezes the system prompt prefix and uses append-only compression to maintain **90%+ cache hit rates** across multi-turn conversations.

```python
from seekflow import CacheStabilizer
stabilizer = CacheStabilizer()
stabilizer.freeze(system_prompt, tool_schemas=tools)
# Every API call: stabilizer.ensure_stable_prefix(messages)
```

### R1 Thought Harvesting

Extracts structured decision points (subgoals, hypotheses, uncertainties) from reasoning content. Injects them as compact insights rather than passing back full verbose reasoning chains.

```python
from seekflow import harvest_thoughts
ht = harvest_thoughts(reasoning_content)
# → subgoals: ["calculate ROI for all 3 companies"]
# → hypotheses: ["A has lowest debt ratio"]
# → uncertainties: ["C's volatility impact unclear"]
```

### Production Reliability

| Component | Description |
|-----------|-------------|
| Circuit Breaker | 3-state (CLOSED→OPEN→HALF_OPEN). Prevents cascading failures |
| Retry Executor | Exponential backoff + jitter. Rate-limit aware (429 handling) |
| Tool Cache | LRU+TTL. SHA256 keys with argument-order independence |
| Context Window | Auto-trim preserves tool-call/result pairs. Append-only compression |
| Trace Recorder | Full execution timeline. JSON export for debugging |
| Cost Tracker | Cache-aware pricing. Real-time cost per agent run |

### DeepSeek-Native Features

| Feature | Description |
|---------|-------------|
| Thinking auto-management | Single-turn=on, multi-turn=auto-disable with warning |
| FIM completions | `fim_complete()` for code infilling (beta endpoint) |
| Batch API | 50% cost savings for bulk processing |
| Balance check | Pre-flight balance query with 5-min cache |
| Rate limit awareness | X-RateLimit-Remaining/Reset header parsing |
| Chinese token counting | CJK-aware fallback (1.5 tokens/char, not 0.25) |

---

## Run Demos

4 production scenarios with blind judge comparison against LangChain and CrewAI:

```bash
export DEEPSEEK_API_KEY="sk-..."
python examples/demo_financial.py       # Financial portfolio analysis
python examples/demo_supply_chain.py    # Supply chain risk assessment
python examples/demo_code_auditor.py    # Code review & security audit
python examples/demo_research.py        # Multi-topic research synthesis
```

Multi-round benchmark with statistical analysis:

```bash
python examples/multi_round_benchmark.py --rounds 3
```

---

## Comparison

| Feature | SeekFlow | LangChain | CrewAI |
|---------|:--:|:--:|:--:|
| Thinking mode | Auto-hybrid | Manual config | Not supported |
| JSON repair | 8-rule pipeline | None | None |
| Cache stabilization | CacheStabilizer | None | None |
| Circuit breaker | 3-state | None | None |
| FIM | Built-in | None | None |
| Balance check | Built-in | None | None |
| R1 thought harvesting | Built-in | None | None |
| Self-consistency branching | Built-in | None | None |
| DeepSeek-optimized presets | 7 agents | Generic only | Generic only |
| Prompt injection filter | Built-in | None | None |
| MCP support | Built-in + fallback | Community | None |
| Dependencies | **6** | 40+ | 30+ |

---

## Documentation

- [Examples](examples/) — 4 demo scenarios + multi-round benchmark
- [Architecture Notes](docs/architecture/) — performance optimization guide
- [Tests](tests/) — 418 tests covering all modules
- [Presets](src/seekflow/agent/presets/) — 7 DeepSeek-optimized agent templates

## License

MIT
