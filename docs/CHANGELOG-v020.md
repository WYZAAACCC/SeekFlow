# SeekFlow v0.2.0 Changelog

## Breaking Changes

- `Agent.with_default_tools()` now registers only `calculate` by default. Set `Agent(dangerous_tools=True)` to restore all 11 tools.
- `ToolCall.arguments` type changed from `dict` to `dict | str` to preserve malformed JSON for repair.
- `repair_message_order()` no longer injects semantic messages ("Please continue").
- `embed_files_into_message()` returns a new dict instead of mutating the input.
- `_sanitize_tool_output()` removed — replaced with `UntrustedContent` wrapper.

## Security Fixes (P0)

- **429 infinite retry**: attempt counter + deadline enforcement + Retry-After cap.
- **CircuitBreaker**: non-retryable errors (400/401/403) no longer count against upstream CB.
- **Default tools**: dangerous tools (read_file, web_search, fetch_url, run_python, query_sql, etc.) disabled by default.
- **Path sandbox**: `safe_join()` + `validate_file_access()` with workspace root, extension allowlisting.
- **SSRF protection**: `validate_url()` blocks private IPs, localhost, metadata endpoints, non-http schemes.
- **Secret redaction**: `redact_secrets()` across error/log/trace pipeline.
- **Untrusted content**: `UntrustedContent` wrapper replaces regex blocklist sanitizer.
- **Preflight cost**: `CostBudget` + `CostEstimator` with hard budget stops.
- **Per-tool timeout**: `ToolExecutor.execute(timeout=)` with ThreadPoolExecutor isolation.
- **Raw args preservation**: malformed JSON in tool calls preserved for repair pipeline.

## New Modules

- `seekflow.security` — `safe_join`, `validate_url`, `redact_secrets`, `UntrustedContent`, `wrap_untrusted`
- `seekflow.budget` — `CostBudget`, `CostEstimator`, `PreflightEstimate`, `BudgetExceeded`
- `seekflow.policy` — `PolicyEngine`, `PolicyDecision`
- `seekflow.state` — `StepKind`, `RunState`, `BudgetState`
- `seekflow.sandbox` — `ToolSandbox`, `NoSandbox`, `LocalThreadSandbox`, `ProcessSandbox`, `ContainerSandbox`
- `seekflow.telemetry` — OTel spans, structured logging (graceful degradation without OTel SDK)

## New Features (P1/P2)

- **ToolPolicy**: capability + risk + timeout + parallel-safety metadata on all tools.
- **Policy Engine**: centralized `PolicyEngine.authorize()` for tool call authorization.
- **JSON repair confidence**: repair levels 0-3, dangerous-tool gating at confidence < 0.85.
- **Parallel execution awareness**: tools classified by `parallel_safe` flag; side-effect tools serialized.
- **Final synthesis**: `tool_choice="none"` forced on penultimate step.
- **File limits**: per-file size, total size, PDF page count caps + zip bomb protection.
- **MCP hardening**: trust levels, capability allowlists, startup timeout, error observability.
- **Search provenance**: `SearchResult` with URL/timestamp/hash + `format_search_results()` citations.
- **Cache Compiler**: `CacheCompiler` with prefix analysis + cache hit predictor.
- **Thinking Router**: `ThinkingRouter` task-aware thinking mode/budget selection.
- **Tool audit trail**: `ToolAuditRecord` with args/result hashes, policy decisions.
- **Sandbox workers**: `ProcessSandbox` + `ContainerSandbox` for code execution isolation.
- **StateGraph enhancements**: per-node retry/fallback, budget-aware scheduling, deterministic replay.
- **Deep copy**: messages deep-copied in runtime; `embed_files_into_message` immutable.

## Deprecated

- `_sanitize_tool_output()` — removed
- `sanitize` parameter on `@tool` decorator — superseded by `trusted`
- Old `with_default_tools()` behavior — now requires `dangerous_tools=True`
