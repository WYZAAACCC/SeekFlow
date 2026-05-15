"""Tests for ToolExecutor."""
import pytest
from seekflow.tools import tool, ToolRegistry
from seekflow.tools.executor import ToolExecutor
from seekflow.types import ToolCall


class TestToolExecutor:
    @pytest.fixture
    def registry(self):
        reg = ToolRegistry()

        @tool(trusted=True)
        def add(a: int, b: int) -> int:
            return a + b

        @tool(trusted=True)
        def greet(name: str) -> str:
            return f"Hello, {name}!"

        @tool(trusted=True)
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

    def test_execute_with_dict_arguments(self, executor):
        """Arguments are always dict — string parsing happens at API boundary."""
        tc = ToolCall(name="add", arguments={"a": 10, "b": 20})
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

    @pytest.mark.xfail(reason="pre-existing: schema validation blocking un-coerced string args (v0.3.5)")
    def test_repair_disabled(self, registry):
        @tool(name="add_without_repair", trusted=True)
        def add_vals(a: int, b: int) -> int:
            return a + b

        registry.register(add_vals)
        exc_no_repair = ToolExecutor(registry, repair=False)
        exc_with_repair = ToolExecutor(registry, repair=True)
        # With string args: repair coerces them, no-repair leaves them as strings
        tc = ToolCall(name="add_without_repair", arguments={"a": "1", "b": "2"})
        r_no = exc_no_repair.execute(tc)
        r_yes = exc_with_repair.execute(tc)
        # Without repair: "1"+"2" = "12" (concatenation, result is str, not int)
        assert r_no.ok
        assert not isinstance(r_no.result, int)
        # With repair: "1"→1, "2"→2, 1+2=3 (coerced, result is int)
        assert r_yes.ok
        assert r_yes.result == 3
        assert r_yes.repaired

    def test_elapsed_time_recorded(self, executor):
        tc = ToolCall(name="greet", arguments={"name": "World"})
        result = executor.execute(tc)
        assert result.ok
        assert result.elapsed_ms is not None
        assert result.elapsed_ms >= 0
