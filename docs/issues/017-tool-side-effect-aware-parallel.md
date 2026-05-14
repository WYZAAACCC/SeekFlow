# Implement tool side-effect/dependency awareness for parallel execution ordering

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** bug
**State:** ready-for-agent

## What to build

`ToolExecutor.execute_batch()` currently submits all tool calls to a `ThreadPoolExecutor` assuming they are independent. This is unsafe when the model returns multiple tool calls in one response and some have side effects (write, network, code_exec) that could conflict.

Implement execution ordering based on `ToolPolicy`:

1. **Classify tools in a batch**: read each `ToolCall`, look up its `ToolDefinition`, check `policy.parallel_safe` and `policy.risk`.

2. **Grouping rules**:
   - `parallel_safe=True` and `risk="read"` → can execute in parallel with any other tool
   - `parallel_safe=False` → must execute sequentially, in the order the model declared them
   - `risk` in `{"write", "network", "code_exec", "destructive"}` → executes sequentially after all pure reads

3. **Execution plan**:
   - Phase 1: execute all parallel-safe read tools concurrently
   - Phase 2: execute non-parallel-safe tools sequentially in original order
   - Phase 3 (if any): execute destructive/write tools sequentially, after all reads complete

4. **Result ordering**: regardless of execution order, results are returned in the original `tool_calls` list order so the caller can zip results with tool calls by index.

5. **Default behavior**: when tools have no `ToolPolicy` (policy=None), they are treated as `parallel_safe=False, risk="read"` — conservative default, safe for unknown tools.

## Acceptance criteria

- [ ] Tools with `parallel_safe=True` execute concurrently in Phase 1
- [ ] Tools with `parallel_safe=False` execute sequentially in Phase 2
- [ ] Destructive tools execute in Phase 3 after all reads complete
- [ ] Results returned in original tool_calls order regardless of execution phase
- [ ] All-read batch (all parallel_safe=True) → all execute concurrently (unchanged behavior)
- [ ] Mixed batch (2 reads + 1 write) → reads execute concurrently first, then write sequentially
- [ ] Policy=None tools treated as parallel_safe=False (conservative)
- [ ] Unit test: read+read concurrent execution
- [ ] Unit test: read+write → write executes after reads complete
- [ ] Unit test: results order matches input order

## Blocked by

- Issue #11 (ToolPolicy schema — `parallel_safe` field)

## Depends on for integration

- Issue #12 (Policy Engine — policy lookup during classification)
