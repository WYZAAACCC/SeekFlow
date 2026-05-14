# Implement preflight cost estimator with hard budget stops before API calls

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** enhancement
**State:** ready-for-agent

## What to build

New module `seekflow.budget` that estimates cost BEFORE API calls and enforces hard stops, replacing the current approach of computing cost after the fact and returning a `cost_guardrail` warning.

1. **`CostBudget`** dataclass:
   - `max_cny: float` — total cost ceiling in CNY
   - `max_prompt_tokens: int` — per-request prompt token cap
   - `max_completion_tokens: int` — per-request completion token cap
   - `max_tool_calls: int` — maximum tool calls across all steps
   - `max_wall_time_s: int` — wall-clock execution timeout

2. **`PreflightEstimate`** dataclass:
   - `lower_bound_cost: float` — minimum expected cost
   - `upper_bound_cost: float` — maximum expected cost (worst-case)
   - `estimated_prompt_tokens: int`
   - `estimated_completion_tokens: int`
   - `estimated_cache_hit: bool`
   - `breakdown: dict` — token breakdown by component

3. **`CostEstimator`** class:
   - `estimate(messages, model, thinking_budget, max_steps) -> PreflightEstimate`
   - Uses tiktoken (when available) for accurate token counting
   - Accounts for: system prompt, conversation history, tools schema, thinking budget tokens, max tool calls × avg tool result tokens
   - Falls back to character-based estimation when tiktoken unavailable

4. **Integration in `Agent._run_impl()`**: before calling `rt.chat()`, run estimate. If `upper_bound_cost > budget.max_cny`:
   - Mode `"reject"`: raise `BudgetExceeded` — a new exception in `seekflow.errors`, subclass of `SeekFlowError`, with fields `limit: float`, `estimated: float`, `model: str` — (default)
   - Mode `"downgrade"`: switch to a cheaper model from `fallback_models`
   - Mode `"warn"`: emit warning and proceed

5. **Runtime integration**: `ToolRuntime.chat()` accepts optional `budget: CostBudget`. Before each model call, estimator checks remaining budget. When budget is exhausted mid-loop, a special "budget exceeded, synthesize final answer now" message is injected.

## Acceptance criteria

- [ ] `CostEstimator.estimate()` returns upper_bound > 0 for non-empty messages
- [ ] Estimation accounts for thinking budget tokens (budget_tokens × max_steps)
- [ ] Estimation accounts for tool schema tokens
- [ ] `CostBudget(max_cny=0.001)` with large prompt → `BudgetExceeded` raised before API call
- [ ] `CostBudget(max_cny=999)` with small prompt → request proceeds normally
- [ ] Downgrade mode: when estimate exceeds budget, falls back to next model in list
- [ ] Runtime mid-loop: when remaining budget < estimated next turn cost, injects final synthesis prompt
- [ ] Regression test: preflight estimate is computed before the first API call
- [ ] Regression test: budget exceeded raises before any tokens are consumed

## Blocked by

None — can start immediately.
