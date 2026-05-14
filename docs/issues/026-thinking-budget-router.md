# Build Thinking Budget Router: task-aware dynamic thinking mode/budget selection

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** enhancement
**State:** ready-for-agent

## What to build

Replace the binary `thinking=True/False` agent parameter with a `ThinkingRouter` that dynamically selects thinking configuration based on task characteristics.

**`ThinkingRouter`**:
```python
router = ThinkingRouter(strategy="cost_aware")

decision = router.route(
    task=task_text,
    tools=tools,
    model=model,
    budget=budget,
    sla_max_latency_s=30.0,
)
# → ThinkingDecision(
#     enable_thinking: bool,
#     budget_tokens: int,       # 0 if disabled, 256-4096 if enabled
#     self_consistency: int,    # 1 (default), 3, or 5
#     compress_reasoning: bool, # whether to compress before injecting
#     inject_reasoning: bool,   # whether to include compressed reasoning in context
# )
```

**Routing factors:**

| Factor | Effect |
|--------|--------|
| Task complexity (estimated via token count + tool count) | High complexity → thinking enabled, higher budget |
| Tool risk level (max risk across all available tools) | Destructive tools → thinking enabled for safety reasoning |
| Expected cost (preflight estimate) | High cost → thinking disabled to save tokens |
| Past success rate (if available via eval results) | Low success rate → thinking enabled, self_consistency > 1 |
| Latency SLA | Tight SLA → thinking disabled or minimal budget |
| Structured output required (`response_format="json_object"`) | JSON mode → thinking enabled for schema adherence |
| Multi-turn conversation | Multi-turn → compress_reasoning=True to preserve cache |
| Model capability (V4 vs V3 vs Chat) | Chat model → thinking disabled (not supported) |

**Integration**: `Agent._thinking_mode()` calls the router instead of returning a static `"enabled"/"disabled"` string. The router is configured once and re-evaluated for each `run()` call (or cached per task hash for identical tasks).

**Fallback**: if routing fails for any reason, default to the user's explicit `thinking` parameter. If neither is set, default to `enabled` with `budget_tokens=2048`.

## Acceptance criteria

- [ ] `ThinkingRouter.route()` returns a `ThinkingDecision` with all fields
- [ ] Complex task (long prompt + many tools) → thinking enabled, higher budget
- [ ] Simple task (short prompt, no tools) → thinking disabled, 0 budget
- [ ] Tight SLA (5s) → thinking disabled regardless of complexity
- [ ] Destructive tools present → thinking enabled
- [ ] JSON response format → thinking enabled
- [ ] DeepSeek Chat model → thinking disabled (not supported by API)
- [ ] `self_consistency > 1` → model called multiple times, results compared
- [ ] `compress_reasoning=True` → reasoning compressed before context injection
- [ ] Router configurable via `Agent(thinking_strategy="cost_aware")`
- [ ] User's explicit `thinking=True/False` overrides router
- [ ] Unit test: simple task → ThinkingDecision(enable=False, budget=0)
- [ ] Unit test: complex task with destructive tools → ThinkingDecision(enable=True, budget>=2048)
- [ ] Unit test: V4-Pro with tight SLA → ThinkingDecision(enable=False)

## Blocked by

- Issue #8 (preflight cost estimate — used as routing input)
- Issue #11 (ToolPolicy — tool risk used as routing input)
