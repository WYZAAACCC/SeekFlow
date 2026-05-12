"""Tests for P3-2: keep_fields integration with @tool decorator and ToolExecutor."""
import json

import pytest

from deepseek_toolkit.tools.decorator import tool
from deepseek_toolkit.tools.executor import ToolExecutor
from deepseek_toolkit.tools.registry import ToolRegistry
from deepseek_toolkit.truncation import TruncationStrategy, truncate_result
from deepseek_toolkit.types import ToolCall


class TestToolDecoratorKeepFields:
    """keep_fields parameter in @tool decorator."""

    def test_keep_fields_stored_in_metadata(self):
        @tool(keep_fields=["temperature", "humidity"])
        def weather(city: str) -> str:
            """Get weather."""
            return json.dumps({"temperature": 25, "humidity": 80, "wind": 10})

        assert weather.metadata["keep_fields"] == ["temperature", "humidity"]

    def test_keep_fields_defaults_to_none(self):
        @tool
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        assert add.metadata.get("keep_fields") is None

    def test_keep_fields_none_explicit(self):
        @tool(keep_fields=None)
        def sub(a: int, b: int) -> int:
            """Subtract."""
            return a - b

        assert sub.metadata["keep_fields"] is None

    def test_cache_and_keep_fields_together(self):
        @tool(name="my_tool", cache=False, keep_fields=["foo"])
        def my_func(x: int) -> int:
            """Test."""
            return x

        assert my_func.metadata["cache"] is False
        assert my_func.metadata["keep_fields"] == ["foo"]
        assert my_func.name == "my_tool"


class TestToolExecutorTruncationStrategy:
    """ToolExecutor truncation_strategy integration."""

    def test_json_aware_strategy_uses_json_truncation(self):
        @tool
        def get_data() -> str:
            """Return structured data."""
            return json.dumps({"results": [{"id": i, "name": f"item_{i}"} for i in range(100)]})

        reg = ToolRegistry()
        reg.register(get_data)
        executor = ToolExecutor(
            reg,
            max_result_chars=500,
            truncation_strategy=TruncationStrategy.JSON_AWARE,
        )
        result = executor.execute(ToolCall(name="get_data", arguments="{}"))
        assert result.ok
        parsed = json.loads(result.result)
        assert "_truncation" in parsed
        assert "results" in parsed

    def test_simple_strategy_uses_simple_truncation(self):
        @tool
        def get_data() -> str:
            """Return long text."""
            return "x" * 1000

        reg = ToolRegistry()
        reg.register(get_data)
        executor = ToolExecutor(
            reg,
            max_result_chars=60,
            truncation_strategy=TruncationStrategy.SIMPLE,
        )
        result = executor.execute(ToolCall(name="get_data", arguments="{}"))
        assert result.ok
        assert "truncated" in result.result.lower()
        assert len(result.result) <= 60

    def test_default_strategy_is_json_aware(self):
        """Backward compatibility: default executor uses JSON-aware truncation."""
        @tool
        def get_data() -> str:
            return json.dumps({"key": "value"})

        reg = ToolRegistry()
        reg.register(get_data)
        executor = ToolExecutor(reg, max_result_chars=1000)  # No explicit strategy
        result = executor.execute(ToolCall(name="get_data", arguments="{}"))
        assert result.ok
        parsed = json.loads(result.result)
        assert parsed["key"] == "value"

    def test_non_string_result_not_truncated(self):
        @tool
        def get_number() -> int:
            return 42

        reg = ToolRegistry()
        reg.register(get_number)
        executor = ToolExecutor(
            reg,
            max_result_chars=10,
            truncation_strategy=TruncationStrategy.JSON_AWARE,
        )
        result = executor.execute(ToolCall(name="get_number", arguments="{}"))
        assert result.ok
        assert result.result == 42


class TestPriorityStrategy:
    """PRIORITY truncation strategy — keeps specified fields first."""

    def test_priority_keeps_specified_fields(self):
        data = json.dumps({
            "temperature": 25,
            "humidity": 80,
            "wind": 10,
            "pressure": 1013,
            "description": "sunny with clear skies",
            "uv_index": 7,
        })
        result = truncate_result(
            data,
            max_result_chars=110,
            strategy=TruncationStrategy.PRIORITY,
            keep_fields=["temperature", "humidity"],
        )
        parsed = json.loads(result)
        assert "temperature" in parsed
        assert "humidity" in parsed
        assert "_truncation" in parsed

    def test_priority_without_keep_fields_falls_back(self):
        data = json.dumps({"a": 1, "b": 2, "c": 3})
        result = truncate_result(
            data,
            max_result_chars=100,
            strategy=TruncationStrategy.PRIORITY,
        )
        parsed = json.loads(result)
        assert parsed["a"] == 1
        assert parsed["b"] == 2

    def test_keep_fields_not_in_data_ignored_silently(self):
        data = json.dumps({"x": 1, "y": 2})
        result = truncate_result(
            data,
            max_result_chars=100,
            strategy=TruncationStrategy.PRIORITY,
            keep_fields=["nonexistent", "also_fake"],
        )
        parsed = json.loads(result)
        assert parsed["x"] == 1
        assert parsed["y"] == 2

    def test_executor_passes_keep_fields_to_truncation(self):
        @tool(keep_fields=["temperature"])
        def weather(city: str) -> str:
            return json.dumps({
                "temperature": 25,
                "wind": 10,
                "humidity": 80,
                "pressure": 1013,
            })

        reg = ToolRegistry()
        reg.register(weather)
        executor = ToolExecutor(
            reg,
            max_result_chars=130,
            truncation_strategy=TruncationStrategy.PRIORITY,
        )
        result = executor.execute(ToolCall(name="weather", arguments='{"city": "Beijing"}'))
        assert result.ok
        parsed = json.loads(result.result)
        assert "temperature" in parsed
