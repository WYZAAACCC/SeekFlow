"""Test ToolPolicy enforcement in ToolExecutor."""
import pytest
from pathlib import Path
from seekflow.types import ToolDefinition, ToolPolicy, ToolCall, ToolExecutionResult
from seekflow.tools.registry import ToolRegistry
from seekflow.tools.executor import ToolExecutor
from seekflow.policy import PolicyEngine
from seekflow.execution.context import ToolExecutionContext
from seekflow.execution.approval import DefaultDenyApprovalHandler, ApprovalResult


def _make_tool(name, func=None, policy=None):
    return ToolDefinition(
        name=name, description="test", parameters={"type": "object", "properties": {}},
        func=func, policy=policy,
    )


def _make_registry(*defs):
    reg = ToolRegistry()
    for td in defs:
        reg.register(td)
    return reg


def test_no_policy_tool_denied_by_default():
    td = _make_tool("unsafe", func=lambda: "ok", policy=None)
    reg = _make_registry(td)
    pe = PolicyEngine(allow_no_policy=False)
    ctx = ToolExecutionContext.conservative(run_id="test")
    executor = ToolExecutor(reg, policy_engine=pe, context=ctx)
    result = executor.execute(ToolCall(name="unsafe", arguments={}))
    assert result.ok is False
    assert "no policy" in result.error.lower() or "policy" in result.error.lower()


def test_policy_allows_read_with_policy():
    def read():
        return "data"
    policy = ToolPolicy(
        capabilities={"filesystem.read"}, risk="read",
        workspace_root=Path(".").resolve(),  # required by policy engine
    )
    td = _make_tool("read", func=read, policy=policy)
    reg = _make_registry(td)
    pe = PolicyEngine()
    ctx = ToolExecutionContext(
        run_id="test",
        allowed_capabilities={"filesystem.read"},
        max_risk="read",
        dangerous_tools_enabled=False,
    )
    executor = ToolExecutor(reg, policy_engine=pe, context=ctx)
    result = executor.execute(ToolCall(name="read", arguments={}))
    assert result.ok


def test_approval_required_invokes_handler():
    approved = False

    class TestApproval:
        def request_approval(self, request):
            nonlocal approved
            approved = True
            return ApprovalResult(approved=False, reason="denied by test")

    policy = ToolPolicy(
        capabilities={"filesystem.write"}, risk="write", requires_approval=True,
        workspace_root=Path(".").resolve(),  # required by policy engine
    )
    td = _make_tool("write", func=lambda: "written", policy=policy)
    reg = _make_registry(td)
    pe = PolicyEngine()
    # Need a context that allows write risk level
    ctx = ToolExecutionContext(
        run_id="test",
        allowed_capabilities={"filesystem.write"},
        max_risk="write",
        dangerous_tools_enabled=True,
    )
    handler = TestApproval()
    executor = ToolExecutor(reg, policy_engine=pe, context=ctx, approval_handler=handler)
    result = executor.execute(ToolCall(name="write", arguments={}))
    assert not result.ok
    assert approved is True


def test_approval_denial_prevents_execution():
    policy = ToolPolicy(
        capabilities={"filesystem.write"}, risk="write", requires_approval=True,
        workspace_root=Path(".").resolve(),
    )
    td = _make_tool("write", func=lambda: "written", policy=policy)
    reg = _make_registry(td)
    pe = PolicyEngine()
    ctx = ToolExecutionContext(
        run_id="test",
        allowed_capabilities={"filesystem.write"},
        max_risk="write",
        dangerous_tools_enabled=True,
    )
    executor = ToolExecutor(reg, policy_engine=pe, context=ctx, approval_handler=DefaultDenyApprovalHandler())
    result = executor.execute(ToolCall(name="write", arguments={}))
    assert not result.ok
    assert "denied" in result.error.lower() or "deny" in result.error.lower()


def test_dangerous_tool_disabled_by_default():
    policy = ToolPolicy(capabilities={"code.exec"}, risk="code_exec")
    td = _make_tool("exec", func=lambda: "executed", policy=policy)
    reg = _make_registry(td)
    pe = PolicyEngine()
    ctx = ToolExecutionContext.conservative(run_id="test")
    executor = ToolExecutor(reg, policy_engine=pe, context=ctx)
    result = executor.execute(ToolCall(name="exec", arguments={}))
    assert not result.ok
