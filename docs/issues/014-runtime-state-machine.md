# Refactor Runtime while-loop into explicit StepKind state machine

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** enhancement
**State:** ready-for-agent

## What to build

Replace the current `while step < max_steps` monolithic loop in `ToolRuntime.chat()` with an explicit state machine where each phase is a discrete, traceable, testable step.

**`StepKind` enum** (in `seekflow.state`):
```
PREPARE → MODEL_CALL → PARSE_RESPONSE → [TOOL_CALLS | FINALIZE]
TOOL_CALLS → VALIDATE → POLICY_GATE → EXECUTE → APPEND_RESULTS → PREPARE
```

**`RunState` model** (in `seekflow.state`):
```python
class RunState(BaseModel):
    run_id: str
    step: int
    current_phase: StepKind
    messages: list[dict]
    budget_remaining: dict  # remaining token/cost budget
    tool_results: list[ToolExecutionResult]
    errors: list[RuntimeErrorRecord]
    trace_id: str
    model: str
    finish_reason: str | None = None
```

**Refactored `ToolRuntime.chat()`**: each state transition is a method:
- `_prepare(run_state)` — context trimming, cache stabilization, tool schema generation
- `_call_model(run_state, **kwargs)` — the API call via RetryExecutor
- `_parse_response(run_state, response)` — extract content, tool calls, reasoning, usage
- `_validate_tool_calls(run_state, tool_calls)` — verify tool names exist, check strict mode
- `_execute_tools(run_state, tool_calls)` — batch execution with policy gate
- `_append_results(run_state, results)` — append tool result messages, reasoning compression
- `_finalize(run_state)` — build ToolRuntimeResult

Each method is independently testable with a prepared `RunState` input. The main loop becomes:

```python
state = RunState(...)
while state.step < self._max_steps:
    state = self._prepare(state)
    if self._should_finalize(state): break
    response = self._call_model(state, **kwargs)
    state = self._parse_response(state, response)
    if not state.pending_tool_calls: break
    state = self._execute_tools(state)
    state = self._append_results(state)
return self._finalize(state)
```

**Backward compatibility**: the public API (`ToolRuntime.chat()`, `chat_stream()`) is unchanged. Internal refactor only. `chat_stream()` follows the same pattern but with streaming model calls.

## Acceptance criteria

- [ ] `StepKind` enum defined with all 7 phases
- [ ] `RunState` model defined with all fields
- [ ] `ToolRuntime.chat()` uses explicit state machine, not raw while-loop
- [ ] Each `_<phase>()` method is independently callable and testable
- [ ] Public API unchanged: `chat()` and `chat_stream()` signatures and return types identical
- [ ] All existing tests pass without modification
- [ ] State transitions traced via TraceRecorder (each phase start/end recorded)
- [ ] `chat_stream()` refactored with same pattern
- [ ] Unit test: prepare → trimmed messages under max_context_tokens
- [ ] Unit test: parse_response with tool_calls → pending_tool_calls populated
- [ ] Unit test: parse_response with content only → finalize triggered
- [ ] Unit test: execute_tools applies policy gate and returns results in order

## Blocked by

- Issue #13 (deep copy — state machine starts from a clean copy)

## Depends on for full integration

- Issue #12 (Policy Engine — called in VALIDATE/POLICY_GATE phase)
- Issue #15 (final synthesis — handled in the PREPARE phase near max_steps)
