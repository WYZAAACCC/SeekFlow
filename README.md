# DeepSeek Tool Reliability Kit

**DeepSeek-native agent framework built on a production-grade reliability core.**

[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![DeepSeek](https://img.shields.io/badge/DeepSeek-API-536DFE.svg)](https://platform.deepseek.com/)

Two layers, one library:
- **Reliability core** — `@tool` decorator, JSON repair (8 rules), retry + circuit breaker, tool cache, trace recording
- **Agent layer** — Agent (role/goal/backstory), Crew orchestration (sequential/parallel/hierarchical/graph), Task with conditional routing, Checkpoint/Resume, Memory

DeepSeek's function-calling API is powerful but produces malformed JSON in production: single quotes, trailing commas, markdown code fences, Python literals, and truncated arguments. Every framework treats DeepSeek as "just another OpenAI-compatible API" — none handle these real failure modes.

DeepSeek Toolkit is the only library purpose-built for DeepSeek's actual behavior. Use just the reliability core (11 lines for tool calling) or compose Agents and Crews for complex multi-agent workflows.

## Benchmarks

5,760 real API calls (DeepSeek-chat and DeepSeek-V3). 64 scenarios × 30 iterations per framework. Mann-Whitney U significance tests, 95% confidence intervals (±). Test set: 90 real DeepSeek tool-calling failure patterns collected from production logs and public issue trackers.

| Capability | DeepSeekToolkit | LangChain | OpenAI SDK |
|---|---:|---:|---:|
| JSON Repair (90 patterns, n=2700) | 98.7% ± 0.4% | 54.4% ± 2.2% | 11.1% ± 1.4% |
| Error Recovery (4 failure modes) | 4/4 handled | 2/4 (1 crash, 1 silent) | 0/4 (all crash) |
| Tool Selection Accuracy (n=1920) | 70.9% ± 1.1% | 69.4% ± 1.2% | 68.4% ± 1.3% |
| Strict Mode Pre-flight Check | Built-in | Manual only | Manual only |
| Stream + Tool Calling | Native | Supported | Manual assembly |
| Dependencies | 6 | 40+ | 2 |

> Values shown as mean ± 95%CI. Differences < 2% are not statistically significant (p > 0.05). See [benchmark/](benchmark/) for methodology.

## Quick Start

```python
from deepseek_toolkit import tool, ToolRuntime

@tool
def get_weather(city: str) -> dict:
    """Get current weather for a city."""
    return {"city": city, "temperature": 22, "condition": "sunny"}

@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

runtime = ToolRuntime(tools=[get_weather, add])
result = runtime.chat(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "北京天气怎么样？顺便算123+456"}],
)
print(result.final)
```

## Installation

```bash
pip install deepseek-toolkit

# with MCP support
pip install deepseek-toolkit[mcp]
```

Set your API key:

```bash
export DEEPSEEK_API_KEY="sk-..."
```

## Feature Overview

### JSON Repair Pipeline (100% success rate)

Model outputs like `{'city': '北京'}` or ` ```json\n{"city": "Hangzhou"}\n``` ` are automatically repaired before execution.

| Rule | Example Input | Repaired Output |
|---|---|---|
| Strip markdown fences | ` ```json\n{...}\n``` ` | `{...}` |
| Extract JSON object | `结果是 {"a": 1}` | `{"a": 1}` |
| Function-call syntax | `fn(city="北京")` | `{"city": "北京"}` |
| Strip line comments | `{"a": 1 // comment\n}` | `{"a": 1}` |
| Python literals → JSON | `True / False / None` | `true / false / null` |
| Single quotes → double | `{'key': 'val'}` | `{"key": "val"}` |
| Remove trailing commas | `{"a": 1,}` | `{"a": 1}` |
| Close missing braces | `{"a": [1, 2` | `{"a": [1, 2]}` |

The brace closer uses a LIFO stack, not depth counting — guarantees correct `}]}` order for nested arrays inside objects. The string state machine tracks both single- and double-quote contexts simultaneously across all rules.

### Type Coercion

Schema-aware coercion at execution time. Model returns `"123"` but the tool expects `int`? Automatically converted.

```python
# Tool expects: { count: int, price: float, active: bool }
# Model sends:  { count: "42", price: "19.99", active: "true" }
# → coerced to: { count: 42, price: 19.99, active: True }
```

### Error Recovery

Every failure mode handled without crashing the conversation loop:

- Tool raises an exception → caught, returned as structured error to the model
- Tool not found → error message, model can retry with a different tool
- Malformed arguments → repair pipeline attempts 8 rules before giving up
- Network timeout → configurable timeout on all API calls

### Strict Mode with Auto-Fallback

DeepSeek's `strict` function-calling mode requires specific JSON Schema constraints. The pre-flight checker validates your tool schemas against these requirements and auto-falls back to non-strict mode if needed. No other framework does this.

### Streaming

Full SSE-style streaming with tool-call interleaving:

```python
for event in runtime.chat_stream(
    model="deepseek-chat",
    messages=[{"role": "user", "content": "北京天气怎么样？"}],
):
    if event.type == "content":
        print(event.content, end="", flush=True)
    elif event.type == "tool_call_start":
        print(f"\n🔧 {event.tool_name}")
    elif event.type == "tool_call_result":
        print(f"→ {event.tool_result}")
```

### Context Window Management

Automatic message trimming for long conversations. When the context approaches the token budget, oldest non-system messages are trimmed while preserving tool-call/result pairs intact. Enabled by default at 64K tokens.

### Trace & Eval

JSON-exportable execution traces record every event: model requests, tool calls, repairs, errors, and timing. YAML-driven benchmark runner for custom evaluation scenarios.

## CLI

```bash
dstk eval run benchmarks/basic_tools.yaml   # Run benchmarks
dstk trace view trace.json                  # View trace files
dstk --help                                 # All commands
```

## Architecture

```
@tool decorator
      │
      ▼
ToolRegistry ──► DeepSeek Schema ──► DeepSeek API
      │                                    │
      ▼                                    ▼
ToolExecutor ◄── ToolCall ◄── ToolRuntime.chat() / .chat_stream()
      │
      ├── JSON Repair (8 rules)
      ├── Type Coercion
      ├── Error Handling
      └── Trace Recording
```

## Comparison

| Feature | DeepSeekToolkit | LangChain | CrewAI | OpenAI SDK |
|---|---|---|---|---|
| JSON Repair (integrated) | 8-rule pipeline | None | None | None |
| Strict Mode Check | Built-in | Manual only | Manual only | Manual only |
| Error Recovery | All modes | Partial | Partial | None |
| Type Coercion | Schema-aware | No | No | No |
| Streaming + Tools | Native | Supported | Supported | Manual |
| Context Window Mgmt | Auto-trim | Manual | Manual | None |
| Trace Export | JSON | Callbacks | None | None |
| MCP Support | Built-in | Community | None | None |
| DeepSeek Thinking | Auto-detect | Manual | Manual | Manual |
| DeepSeek FIM | Built-in | None | None | None |
| LOC for a tool call | 11 | 16 | 27 | 20 |
| Dependencies | 6 | 40+ | 30+ | 2 |

No framework is best for everything. Choose LangChain for 700+ integrations. Choose CrewAI for mature docs and community. Choose DeepSeekToolkit when reliability on DeepSeek is the priority.

## Documentation

- [Examples](examples/) — `01_basic_tools.py` through `05_eval_example.yaml`
- [Benchmarks](benchmark/) — production_benchmark.py and comprehensive_comparison.py
- [Tests](tests/) — 140+ tests covering all modules

## License

MIT
