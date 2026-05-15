"""Tests for parallel tool call execution."""
import time
from unittest.mock import MagicMock
import pytest


class TestParallelExecution:
    def test_parallel_execution_faster_than_serial(self):
        from seekflow.tools.executor import ToolExecutor
        from seekflow.tools.registry import ToolRegistry

        def slow_tool_a() -> str:
            time.sleep(0.1)
            return "a"

        def slow_tool_b() -> str:
            time.sleep(0.1)
            return "b"

        reg = ToolRegistry()
        reg.register(slow_tool_a)
        reg.register(slow_tool_b)

        executor = ToolExecutor(reg, max_parallel=5)

        from seekflow.types import ToolCall, ToolPolicy

        # Give tools parallel-safe read policy
        for name in ("slow_tool_a", "slow_tool_b"):
            td = reg.get(name)
            td.policy = ToolPolicy(risk="read", parallel_safe=True)

        calls = [
            ToolCall(id="1", name="slow_tool_a", arguments={}),
            ToolCall(id="2", name="slow_tool_b", arguments={}),
        ]

        start = time.time()
        results = executor.execute_batch(calls)
        elapsed = time.time() - start

        assert len(results) == 2
        # Parallel should be much faster than serial 0.2s
        assert elapsed < 0.18

    def test_single_tool_call_no_overhead(self):
        from seekflow.tools.executor import ToolExecutor
        from seekflow.tools.registry import ToolRegistry

        def quick():
            return "ok"

        reg = ToolRegistry()
        td = reg.register(quick)
        td.metadata["trusted"] = True
        executor = ToolExecutor(reg)

        from seekflow.types import ToolCall
        results = executor.execute_batch([ToolCall(id="1", name="quick", arguments={})])
        assert len(results) == 1
        assert results[0].ok
