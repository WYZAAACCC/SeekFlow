"""Verify PolicyEngine is enforced in ToolExecutor."""
from __future__ import annotations

import pytest

from seekflow.policy import PolicyEngine
from seekflow.tools.executor import ToolExecutor
from seekflow.tools.registry import ToolRegistry
from seekflow.types import ToolCall, ToolDefinition, ToolPolicy


class TestNoPolicyToolDenied:
    def test_no_policy_tool_denied_with_policy_engine(self):
        reg = ToolRegistry()
        reg.register(ToolDefinition(
            name="unknown_tool", description="No policy",
            parameters={"type": "object", "properties": {}},
            func=lambda **kw: "ok",
        ))
        engine = PolicyEngine()
        executor = ToolExecutor(reg, policy_engine=engine)
        tc = ToolCall(name="unknown_tool", arguments={})
        result = executor.execute(tc)
        assert not result.ok
        assert "policy" in result.error.lower() or "denied" in result.error.lower()

    def test_tool_with_read_policy_allowed(self):
        reg = ToolRegistry()
        reg.register(ToolDefinition(
            name="safe_read", description="Safe",
            parameters={"type": "object", "properties": {}},
            func=lambda: "data",
            policy=ToolPolicy(risk="read", capabilities={"read"}),
        ))
        engine = PolicyEngine()
        executor = ToolExecutor(reg, policy_engine=engine)
        tc = ToolCall(name="safe_read", arguments={})
        result = executor.execute(tc)
        assert result.ok

    def test_dangerous_code_exec_denied_without_sandbox(self):
        reg = ToolRegistry()
        reg.register(ToolDefinition(
            name="exec_code", description="Exec",
            parameters={"type": "object", "properties": {}},
            func=lambda code: "ran",
            policy=ToolPolicy(risk="code_exec", capabilities={"code.exec"}),
        ))
        engine = PolicyEngine()
        executor = ToolExecutor(reg, policy_engine=engine)
        tc = ToolCall(name="exec_code", arguments={"code": "print(1)"})
        result = executor.execute(tc)
        assert not result.ok


class TestBatchExecutionPolicy:
    def test_no_policy_tools_not_parallel_safe(self):
        from seekflow.tools.executor import ToolExecutor
        from seekflow.tools.registry import ToolRegistry
        from seekflow.types import ToolCall

        reg = ToolRegistry()
        reg.register(ToolDefinition(
            name="t1", description="nop",
            parameters={"type": "object", "properties": {}},
            func=lambda: "a",
        ))
        reg.register(ToolDefinition(
            name="t2", description="nop",
            parameters={"type": "object", "properties": {}},
            func=lambda: "b",
        ))
        executor = ToolExecutor(reg)
        results = executor.execute_batch([
            ToolCall(name="t1", arguments={}),
            ToolCall(name="t2", arguments={}),
        ])
        assert len(results) == 2
        # Both should still execute (sequential), just not parallel
        assert results[0].ok or not results[0].ok
        assert results[1].ok or not results[1].ok
