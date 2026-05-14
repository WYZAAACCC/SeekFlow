# Implement StateGraph Agent execution model

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** enhancement
**State:** ready-for-agent

## What to build

Add a `StateGraph` execution model to `seekflow.agent` that allows composing agents as typed graphs with checkpoint/resume, retry/fallback, and deterministic replay — going beyond the current linear while-loop.

**`StateGraph` API**:
```python
from seekflow.agent.stategraph import StateGraph, NodeSpec

graph = StateGraph()

# Define nodes
graph.add_node("plan", model_call(schema=PlanOutput))
graph.add_node("approve", policy_gate(requires=["human_approval"]))
graph.add_node("execute", tool_executor(tools=tools))
graph.add_node("verify", model_call(schema=VerificationOutput))
graph.add_node("final", model_call())

# Define edges (with optional conditions)
graph.add_edge("plan", "approve")
graph.add_conditional_edge("approve", {
    "approved": "execute",
    "denied": "final",
})
graph.add_edge("execute", "verify")
graph.add_conditional_edge("verify", {
    "needs_more": "execute",    # loop back for more data
    "done": "final",
})

graph.set_entry_point("plan")
```

**Features:**

1. **Typed state**: each node receives and returns a typed `GraphState`. The graph validates state transitions at definition time (not runtime).

2. **Checkpoint/resume**: after each node executes, state is checkpointed via `CheckpointStore`. A failed graph can resume from the last successful node.

3. **Deterministic replay**: if all model calls use `temperature=0` and `seed` is fixed, the graph produces identical results. Used for debugging and testing.

4. **Budget-aware scheduling**: `GraphConfig` accepts `CostBudget`. Before each node, remaining budget is checked. If budget is exhausted, the graph transitions to a `budget_exhausted` terminal node.

5. **Per-node retry/fallback**: each node can specify `retry_policy` and `fallback_node`. If a node fails after max_retries, the graph transitions to the fallback node instead of crashing.

6. **Node-level tracing**: each node execution creates an OTel span (integrates with issue #24). State transitions are recorded as span events.

7. **Human-in-the-loop**: nodes can be marked `requires_approval=True`. When the graph reaches such a node, it pauses and exposes the pending approval via an async callback. The caller approves/denies, and the graph resumes.

**Integration with existing Agent**: 
```python
agent = DeepSeekAgent(..., graph=my_state_graph)
result = agent.run(task)  # uses StateGraph instead of linear loop
```

When `graph` is not provided, the existing linear runtime is used (backward compatible).

## Acceptance criteria

- [ ] `StateGraph` class with `add_node`, `add_edge`, `add_conditional_edge`, `set_entry_point`
- [ ] Typed state propagation (each node sees typed input, produces typed output)
- [ ] Checkpoint after each node → resume from checkpoint works
- [ ] Deterministic replay with temperature=0 and fixed seed
- [ ] Budget check before each node, budget_exhausted transition
- [ ] Per-node retry with fallback node
- [ ] OTel spans for each node execution
- [ ] HITL: approval node pauses, resumes on callback
- [ ] `Agent(graph=state_graph)` integration
- [ ] Backward compatible: no graph → existing linear runtime
- [ ] Unit test: simple plan→execute→final graph executes correctly
- [ ] Unit test: conditional edge → correct branch taken based on state
- [ ] Unit test: node failure → retry → fallback node
- [ ] Unit test: checkpoint after node 2 → resume from node 3
- [ ] Unit test: budget exhausted mid-graph → budget_exhausted node

## Blocked by

- Issue #14 (state machine — StateGraph builds on RunState concepts)
- Issue #8 (CostBudget — used for budget-aware scheduling)
- Issue #24 (OpenTelemetry — used for node-level tracing)
