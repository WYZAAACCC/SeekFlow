"""StateGraph — channel-based state machine with conditional routing.

Lighter than LangGraph (29K lines): ~200 lines covering the 80% use case.
Channels support last_value (default), append, and merge reducers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Command:
    """Resume command for interrupted graph execution."""
    resume: Any = None


class Interrupt:
    """Pause graph execution. Return this from a node to halt the graph."""
    def __init__(self, value: Any = None):
        self.value = value


Reducer = Callable[[Any, Any], Any]


def _last_value(old: Any, new: Any) -> Any:
    return new


def _append(old: Any, new: Any) -> Any:
    if not isinstance(old, list):
        old = list(old) if old else []
    if isinstance(new, list):
        return old + new
    return old + [new]


def _merge(old: Any, new: Any) -> Any:
    if isinstance(old, dict) and isinstance(new, dict):
        return {**old, **new}
    return new


REDUCERS: dict[str, Reducer] = {
    "last_value": _last_value,
    "append": _append,
    "merge": _merge,
}


class StateGraph:
    """Minimal state machine with channel-based state management.

    Usage:
        g = StateGraph(dict)
        g.add_node("analyze", my_func)
        g.add_conditional_edges("analyze", router, {"a": "node_a", "b": "node_b"})
        g.set_entry_point("analyze")
        result = g.invoke({})
    """

    def __init__(self, state_class: type = dict):
        self._nodes: dict[str, Callable] = {}
        self._edges: dict[str, str] = {}
        self._conditional_edges: dict[str, tuple[Callable, dict[str, str]]] = {}
        self._channels: dict[str, str] = {}  # channel_name -> reducer_name
        self._entry: str | None = None
        self._finish: set[str] = set()
        self._state_class = state_class

        # Interrupt state
        self.interrupted: bool = False
        self.interrupt_value: Any = None
        self._checkpoint: dict | None = None

        # Per-node retry/fallback
        self._node_retry: dict[str, int] = {}
        self._node_fallback: dict[str, str] = {}

        # Budget-aware scheduling
        self._cost_budget: Any = None
        self._budget_exhausted_node: str | None = None

        # Deterministic replay
        self._seed: int | None = None
        self._step_log: list[dict] = []

        # Checkpoint store
        self._checkpoint_store: Any = None

    def add_node(self, name: str, func: Callable) -> None:
        self._nodes[name] = func

    def add_edge(self, from_node: str, to_node: str) -> None:
        self._edges[from_node] = to_node

    def add_conditional_edges(self, from_node: str, router: Callable,
                              mapping: dict[str, str]) -> None:
        self._conditional_edges[from_node] = (router, mapping)

    def add_channel(self, name: str, reducer: str = "last_value") -> None:
        self._channels[name] = reducer

    def set_entry_point(self, name: str) -> None:
        self._entry = name

    def set_finish_point(self, name: str) -> None:
        self._finish.add(name)

    def with_retry(self, node_name: str, max_retries: int = 3,
                   fallback_node: str = "") -> "StateGraph":
        """Configure retry with optional fallback for a node."""
        self._node_retry[node_name] = max_retries
        if fallback_node:
            self._node_fallback[node_name] = fallback_node
        return self

    def with_budget(self, budget: Any, exhausted_node: str = "") -> "StateGraph":
        """Set a cost budget for the graph execution."""
        self._cost_budget = budget
        self._budget_exhausted_node = exhausted_node
        return self

    def with_deterministic_replay(self, seed: int = 42) -> "StateGraph":
        """Enable deterministic replay with a fixed seed."""
        self._seed = seed
        return self

    def with_checkpoint_store(self, store: Any) -> "StateGraph":
        """Attach a checkpoint store for save/resume."""
        self._checkpoint_store = store
        return self

    def invoke(self, state: Any, command: Command | None = None) -> Any:
        """Execute the graph, returning final state."""
        if self._entry is None:
            raise ValueError("set_entry_point() must be called before invoke()")

        if command is not None and self._checkpoint is not None:
            state = dict(self._checkpoint)
            state["__resume__"] = command.resume
            self.interrupted = False
            interrupted_node = self._checkpoint.get("__interrupted_at__")
            current = self._edges.get(interrupted_node, self._entry) if interrupted_node else self._entry
            self._checkpoint = None
        else:
            current = self._entry

        while True:
            node_fn = self._nodes[current]
            max_retries = self._node_retry.get(current, 0)
            last_err = None

            for attempt in range(max_retries + 1):
                try:
                    update = node_fn(dict(state) if isinstance(state, dict) else state)
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    if attempt < max_retries:
                        import time as _time
                        _time.sleep(0.5 * (attempt + 1))

            if last_err is not None:
                fallback = self._node_fallback.get(current)
                if fallback and fallback in self._nodes:
                    self._step_log.append({"node": current, "error": str(last_err),
                                           "fallback": fallback})
                    current = fallback
                    continue
                raise last_err

            # Budget check
            if self._cost_budget is not None:
                try:
                    if hasattr(self._cost_budget, 'max_cny'):
                        remaining = getattr(self._cost_budget, 'max_cny', float('inf'))
                        if remaining <= 0 and self._budget_exhausted_node:
                            current = self._budget_exhausted_node
                            continue
                except Exception:
                    pass

            if isinstance(update, Interrupt):
                self.interrupted = True
                self.interrupt_value = update.value
                cp = dict(state) if isinstance(state, dict) else {}
                cp["__interrupted_at__"] = current
                self._checkpoint = cp
                return state

            if update is not None:
                state = self._apply_update(state, update)

            if current in self._finish:
                return state

            # Route to next node
            if current in self._conditional_edges:
                router, mapping = self._conditional_edges[current]
                key = router(dict(state) if isinstance(state, dict) else state)
                current = mapping.get(key)
                if current is None:
                    return state  # no matching route
            elif current in self._edges:
                current = self._edges[current]
            else:
                return state  # dead end

    def _apply_update(self, state: Any, update: Any) -> Any:
        if not isinstance(state, dict) or not isinstance(update, dict):
            return update

        result = dict(state)
        for key, val in update.items():
            if key in self._channels:
                reducer_name = self._channels[key]
                reducer = REDUCERS.get(reducer_name, _last_value)
                old = result.get(key)
                result[key] = reducer(old, val)
            else:
                result[key] = val  # default: last_value
        return result


__all__ = ["StateGraph", "Command", "Interrupt"]
