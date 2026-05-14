# Integrate OpenTelemetry: spans, metrics, structured logs, trace sampling

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** enhancement
**State:** ready-for-agent

## What to build

Replace the current in-memory `TraceRecorder` (a list of dicts with JSON export) with OpenTelemetry-based observability that integrates with production monitoring stacks.

**Spans** (replacing current `recorder.record()` calls):
- `agent.run` — root span for the entire agent execution
- `runtime.step` — one span per state machine step
- `model.call` — span wrapping the API call (includes model name, token counts)
- `tool.execute` — span per tool execution (includes tool name, latency, ok/error)
- `mcp.call` — span for MCP tool execution

**Metrics** (exported via OpenTelemetry Metrics API):
- `seekflow.agent.runs` — counter, tagged with model, status
- `seekflow.model.tokens` — histogram: prompt_tokens, completion_tokens, cached_tokens
- `seekflow.model.latency` — histogram: API call duration in ms
- `seekflow.tool.calls` — counter, tagged with tool_name, ok/error
- `seekflow.tool.latency` — histogram: tool execution duration in ms
- `seekflow.cache.hit_rate` — gauge: cache_hits / total_requests
- `seekflow.cost.total` — counter: cumulative cost in CNY
- `seekflow.retry.count` — counter, tagged with reason (rate_limit, server_error)
- `seekflow.circuit_breaker.state` — gauge: 0=closed, 1=half_open, 2=open

**Structured logs**: replace `warnings.warn()` and ad-hoc prints with `logging.getLogger("seekflow")` calls at appropriate levels. Key events:
- `agent.start` / `agent.end` — INFO
- `tool.call` / `tool.result` — DEBUG
- `model.call` / `model.response` — DEBUG
- `retry.attempt` — WARNING
- `circuit_breaker.change` — WARNING
- `budget.exceeded` — ERROR
- `mcp.connection.error` — ERROR
- `security.violation` — ERROR (path traversal, SSRF attempt)

**Secret redaction in telemetry**: all span attributes, metric tags, and log messages pass through `redact_secrets()` from issue #10.

**Trace sampling**: configurable via `OTEL_TRACES_SAMPLER` env var. Default: `parentbased_always_on` for agent runs, `parentbased_traceidratio(0.1)` for individual tool calls.

**Backward compatibility**: `TraceRecorder` continues to work for in-memory trace export. OTel integration is additive — when OTel is not configured (no exporter), the framework works as before.

## Acceptance criteria

- [ ] OTel spans created for agent.run, runtime.step, model.call, tool.execute
- [ ] Span attributes include model name, tool name, latency, token counts
- [ ] Metrics exported: runs, tokens, latency, tool_calls, cache_hit_rate, cost, retry_count, circuit_breaker_state
- [ ] Structured logging via `logging.getLogger("seekflow")` with appropriate levels
- [ ] All telemetry data passes through `redact_secrets()`
- [ ] Trace sampling configurable via standard OTel environment variables
- [ ] No OTel SDK installed → framework works normally (no crashes, no metrics exported)
- [ ] Existing `TraceRecorder` still works for JSON export
- [ ] Unit test: agent run creates root span with correct attributes
- [ ] Unit test: tool execution creates child span with tool_name and latency
- [ ] Unit test: secret in tool result → redacted in span attribute

## Blocked by

- Issue #14 (state machine — spans align with state machine phases)
- Issue #10 (secret redaction — applied to all telemetry)
