"""Tests for ToolExecutor."""
import pytest
from deepseek_toolkit.tools import tool, ToolRegistry
from deepseek_toolkit.tools.executor import ToolExecutor
from deepseek_toolkit.types import ToolCall


class TestToolExecutor:
    @pytest.fixture
    def registry(self):
        reg = ToolRegistry()

        @tool
        def add(a: int, b: int) -> int:
            return a + b

        @tool
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        @tool
        def fail() -> str:
            raise ValueError("intentional error")

        reg.register(add)
        reg.register(greet)
        reg.register(fail)
        return reg

    @pytest.fixture
    def executor(self, registry):
        return ToolExecutor(registry)

    def test_execute_successful_tool(self, executor):
        tc = ToolCall(name="add", arguments={"a": 1, "b": 2})
        result = executor.execute(tc)
        assert result.ok
        assert result.result == 3
        assert result.name == "add"

    def test_execute_with_string_arguments(self, executor):
        tc = ToolCall(name="add", arguments='{"a": 10, "b": 20}')
        result = executor.execute(tc)
        assert result.ok
        assert result.result == 30

    def test_tool_not_found(self, executor):
        tc = ToolCall(name="nonexistent", arguments={})
        result = executor.execute(tc)
        assert not result.ok
        assert "not found" in result.error.lower()

    def test_tool_raises_exception(self, executor):
        tc = ToolCall(name="fail", arguments={})
        result = executor.execute(tc)
        assert not result.ok
        assert result.error is not None

    def test_result_truncation(self, registry):
        @tool
        def long_output() -> str:
            return "x" * 100

        registry.register(long_output)
        executor = ToolExecutor(registry, max_result_chars=20)
        tc = ToolCall(name="long_output", arguments={})
        result = executor.execute(tc)
        assert result.ok
        assert "truncated" in str(result.result).lower()

    def test_repair_disabled(self, registry):
        @tool(name="add_without_repair")
        def add_vals(a: int, b: int) -> int:
            return a + b

        registry.register(add_vals)
        exc = ToolExecutor(registry, repair=False)
        tc = ToolCall(name="add_without_repair", arguments="{'a': 1, 'b': 2}")
        result = exc.execute(tc)
        # Without repair, single-quote JSON would fail to parse
        # Arguments won't repair, so the raw string can't be parsed
        assert not result.ok

    def test_elapsed_time_recorded(self, executor):
        tc = ToolCall(name="greet", arguments={"name": "World"})
        result = executor.execute(tc)
        assert result.ok
        assert result.elapsed_ms is not None
        assert result.elapsed_ms >= 0
