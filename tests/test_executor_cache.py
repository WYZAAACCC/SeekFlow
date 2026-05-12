"""Tests for ToolExecutor cache integration (P1-2)."""
from deepseek_toolkit.tool_cache import ToolCallCache
from deepseek_toolkit.tools.executor import ToolExecutor
from deepseek_toolkit.tools.registry import ToolRegistry
from deepseek_toolkit.types import ToolCall


_call_counts: dict[str, int] = {}


def _counting_add(a: int, b: int) -> int:
    """Add two numbers."""
    _call_counts["_counting_add"] = _call_counts.get("_counting_add", 0) + 1
    return a + b


def _counting_sub(a: int, b: int) -> int:
    """Subtract two numbers."""
    _call_counts["_counting_sub"] = _call_counts.get("_counting_sub", 0) + 1
    return a - b


class TestExecutorCache:
    """ToolExecutor cache integration — cache hit/miss behavior."""

    def test_cache_hit_returns_cached_result_without_calling_tool(self):
        _call_counts.clear()
        registry = ToolRegistry()
        registry.register(_counting_add)

        cache = ToolCallCache(max_size=10)
        executor = ToolExecutor(registry, cache=cache)

        tc = ToolCall(name="_counting_add", arguments={"a": 1, "b": 2})

        r1 = executor.execute(tc)
        assert r1.ok is True
        assert r1.result == 3
        assert _call_counts["_counting_add"] == 1

        r2 = executor.execute(tc)
        assert r2.ok is True
        assert r2.result == 3
        assert _call_counts["_counting_add"] == 1  # No second call
        assert "cache_hit" in r2.repair_notes

    def test_different_arguments_different_cache_key(self):
        _call_counts.clear()
        registry = ToolRegistry()
        registry.register(_counting_add)

        cache = ToolCallCache(max_size=10)
        executor = ToolExecutor(registry, cache=cache)

        r1 = executor.execute(ToolCall(name="_counting_add", arguments={"a": 1, "b": 2}))
        r2 = executor.execute(ToolCall(name="_counting_add", arguments={"a": 3, "b": 4}))

        assert r1.ok and r2.ok
        assert _call_counts["_counting_add"] == 2

    def test_cache_false_tool_always_executes(self):
        _call_counts.clear()
        registry = ToolRegistry()
        td = registry.register(_counting_add)
        td.metadata["cache"] = False

        cache = ToolCallCache(max_size=10)
        executor = ToolExecutor(registry, cache=cache)

        tc = ToolCall(name="_counting_add", arguments={"a": 1, "b": 2})
        r1 = executor.execute(tc)
        r2 = executor.execute(tc)

        assert r1.ok and r2.ok
        assert _call_counts["_counting_add"] == 2

    def test_no_cache_disabled(self):
        _call_counts.clear()
        registry = ToolRegistry()
        registry.register(_counting_add)

        executor = ToolExecutor(registry, cache=None)
        tc = ToolCall(name="_counting_add", arguments={"a": 1, "b": 2})

        r1 = executor.execute(tc)
        r2 = executor.execute(tc)
        assert r1.ok and r2.ok
        assert _call_counts["_counting_add"] == 2


class TestToolDecoratorCache:
    """@tool(cache=False) metadata."""

    def test_cache_defaults_to_true(self):
        registry = ToolRegistry()
        td = registry.register(_counting_add)
        assert td.metadata.get("cache", True) is True

    def test_cache_false_sets_metadata(self):
        registry = ToolRegistry()
        td = registry.register(_counting_add)
        td.metadata["cache"] = False
        assert td.metadata["cache"] is False
