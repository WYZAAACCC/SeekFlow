"""Verify executor has no direct tool_def.func() call paths."""
from pathlib import Path

import pytest

from seekflow.tools import tool, ToolRegistry
from seekflow.tools.executor import ToolExecutor
from seekflow.types import ToolCall, ToolDefinition, ToolPolicy


EXECUTOR_FILE = Path(__file__).parents[2] / "src" / "seekflow" / "tools" / "executor.py"


def _add_proc(a: int, b: int) -> int:
    return a + b


class TestNoDirectCall:
    """Grep verification: executor.py must not call tool_def.func(**arguments)."""

    def test_no_direct_func_call_in_executor(self):
        """The string 'tool_def.func(' or '.func(**' must not appear in executor.py.
        The InProcessRunner is the only place that calls func(**arguments) directly.
        """
        text = EXECUTOR_FILE.read_text(encoding="utf-8")
        # Remove comments to avoid false positives
        lines = [line for line in text.split("\n") if not line.strip().startswith("#")]
        clean = "\n".join(lines)

        # These patterns would indicate a direct call bypassing runners
        assert "tool_def.func(" not in clean, (
            "executor.py must not call tool_def.func() directly — use runners"
        )
        assert ".func(**" not in clean, (
            "executor.py must not call func(**arguments) directly — use runners"
        )

    def test_in_process_runner_has_func_call(self):
        """InProcessRunner.run() IS allowed to call func(**arguments)."""
        runner_file = Path(__file__).parents[2] / "src" / "seekflow" / "tools" / "runners.py"
        text = runner_file.read_text(encoding="utf-8")
        # Strip module docstring (first """...""") then check code
        parts = text.split('"""')
        # parts[0] is empty/imports before docstring, parts[1] is docstring content,
        # parts[2:] is actual code
        code = '"""'.join(parts[2:]) if len(parts) > 2 else text
        assert ".func(**" not in code, (
            "runners.py code must not call tool_def.func(**arguments)"
        )
        assert "func(**arguments)" in code, (
            "InProcessRunner must call func(**arguments) — it is the only allowed caller"
        )


class TestAuditRecordsRunnerName:
    """Runner name must be recorded in the audit trail."""

    def test_audit_includes_runner_name(self):
        reg = ToolRegistry()

        @tool(trusted=True)
        def echo(msg: str) -> str:
            return msg

        reg.register(echo)
        executor = ToolExecutor(reg)
        tc = ToolCall(name="echo", arguments={"msg": "hello"})
        result = executor.execute(tc)
        assert result.ok
        assert len(executor.audit_trail) == 1
        record = executor.audit_trail[0]
        assert record.runner_name == "in_process"

    def test_process_runner_name_in_audit(self):
        """Tool routed to process runner records 'process' in audit."""
        reg = ToolRegistry()

        td = ToolDefinition(
            name="add_proc",
            description="Adds two numbers via process",
            parameters={"type": "object", "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            }},
            func=_add_proc,
            policy=ToolPolicy(risk="write", capabilities={"filesystem.write"}),
        )
        reg.register(td)
        executor = ToolExecutor(reg)
        tc = ToolCall(name="add_proc", arguments={"a": 1, "b": 2})
        result = executor.execute(tc)
        assert result.ok
        record = executor.audit_trail[0]
        assert record.runner_name == "process"


class TestExecutorUsesRunners:
    """Integration: ensure executor passes through runners, not direct calls."""

    def test_trusted_read_tool_runs_in_process(self):
        reg = ToolRegistry()

        @tool(trusted=True)
        def double(n: int) -> int:
            return n * 2

        reg.register(double)
        executor = ToolExecutor(reg)
        tc = ToolCall(name="double", arguments={"n": 21})
        result = executor.execute(tc)
        assert result.ok
        assert result.result == 42
        assert len(executor.audit_trail) == 1
        assert executor.audit_trail[0].runner_name == "in_process"
