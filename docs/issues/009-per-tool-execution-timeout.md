# Implement per-tool execution timeout with ThreadPoolExecutor isolation

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** bug
**State:** ready-for-agent

## What to build

Currently `ToolExecutor.execute()` calls `tool_def.func(**arguments)` directly in the calling thread with no per-tool timeout. A hung tool blocks the entire agent run indefinitely. The only timeout available is the `execution_timeout` on `Agent.run()` which wraps the entire run — too coarse.

1. **Per-tool timeout in `ToolExecutor.execute()`**: Execute each tool in a `ThreadPoolExecutor(max_workers=1)` with `future.result(timeout=tool_timeout)`. On `TimeoutError`, return a `ToolExecutionResult(ok=False, error="Tool execution timed out after {timeout}s")` and cancel the future.

2. **Default timeout**: 30 seconds for read-only tools (configurable). Built-in network tools get 15 seconds. The timeout is sourced from `ToolPolicy.timeout_s` when available, otherwise uses a per-executor default.

3. **`execute_batch()` integration**: parallel execution already uses ThreadPoolExecutor — add timeout to each `future.result()` call.

4. **Timeout behavior**: on timeout, the thread is not killable in pure Python, but the result is abandoned. The tool function should ideally check a threading.Event for cancellation. Provide a `set_timeout` context variable that tools can optionally check. Document this limitation.

5. **Graceful degradation**: after a tool timeout, the error result is appended to the message list. The model sees "Tool X timed out after Y seconds" and can decide to retry with different parameters or proceed without the result.

6. **Interaction with Agent-level timeout**: per-tool timeout is independent of `Agent.run(execution_timeout=...)`. If the tool timeout fires first, the tool returns an error result and the run continues to the next step. If the agent-level `execution_timeout` fires first, the entire run is terminated via `ThreadPoolExecutor` cancellation. The tool-level timeout should always be set shorter than the agent-level timeout (if both are configured).

## Acceptance criteria

- [ ] `ToolExecutor.execute()` accepts a per-call `timeout` parameter (default 30s)
- [ ] Tool that sleeps 60s with timeout=2s → returns `ok=False` with timeout error after ~2s
- [ ] Timeout error message includes tool name and timeout value
- [ ] `execute_batch()` applies timeout to each parallel tool individually
- [ ] Fast tool completes normally even when another tool in the batch times out
- [ ] Tool timeout does NOT crash the runtime loop — next step proceeds
- [ ] Timeout behavior documented: threads not forcibly killed, tool should cooperate
- [ ] Regression test: tool sleeps 5s with 1s timeout → returns timeout error within 2s wall clock
- [ ] Regression test: tool with None timeout runs normally (backward compat)

## Blocked by

None — can start immediately. (Issue #11 provides ToolPolicy which will supply per-tool timeout values.)
