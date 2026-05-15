"""PR-6: No-policy tools are denied by default."""
import warnings

import pytest

from seekflow.tools.executor import ToolExecutor
from seekflow.tools.registry import ToolRegistry
from seekflow.types import ToolDefinition, ToolCall, ToolPolicy


def _dummy_read():
    return "data"


class TestNoPolicyExecution:
    """No-policy tools must be denied by default."""

    def test_no_policy_tool_denied_by_default(self):
        """No-policy tool is denied even without a policy_engine."""
        reg = ToolRegistry()
        td = ToolDefinition(
            name="read", description="", parameters={}, func=_dummy_read,
            policy=None,
        )
        reg.register(td)
        executor = ToolExecutor(reg)  # no policy_engine
        result = executor.execute(ToolCall(name="read", arguments={}))
        assert not result.ok
        assert "ToolPolicy required" in result.error

    def test_no_policy_tool_allowed_with_unsafe_flag(self):
        """allow_unsafe_no_policy_execution=True permits execution."""
        reg = ToolRegistry()
        td = ToolDefinition(
            name="read", description="", parameters={}, func=_dummy_read,
            policy=None,
        )
        reg.register(td)
        executor = ToolExecutor(reg, allow_unsafe_no_policy_execution=True)
        result = executor.execute(ToolCall(name="read", arguments={}))
        assert result.ok

    def test_unsafe_flag_emits_runtime_warning(self):
        """allow_unsafe_no_policy_execution=True emits RuntimeWarning."""
        reg = ToolRegistry()
        td = ToolDefinition(
            name="read", description="", parameters={}, func=_dummy_read,
            policy=None,
        )
        reg.register(td)
        executor = ToolExecutor(reg, allow_unsafe_no_policy_execution=True)

        with pytest.warns(RuntimeWarning, match="semi-production safety"):
            executor.execute(ToolCall(name="read", arguments={}))

    def test_policy_tool_still_allowed_by_default(self):
        """Tools with a ToolPolicy still execute normally."""
        reg = ToolRegistry()
        policy = ToolPolicy(risk="read")
        td = ToolDefinition(
            name="read", description="", parameters={}, func=_dummy_read,
            policy=policy,
        )
        reg.register(td)
        executor = ToolExecutor(reg)
        result = executor.execute(ToolCall(name="read", arguments={}))
        assert result.ok

    def test_no_policy_tool_denied_even_with_policy_engine(self):
        """No-policy tool is denied even when policy_engine is present."""
        from seekflow.policy import PolicyEngine

        reg = ToolRegistry()
        td = ToolDefinition(
            name="read", description="", parameters={}, func=_dummy_read,
            policy=None,
        )
        reg.register(td)
        engine = PolicyEngine()
        executor = ToolExecutor(reg, policy_engine=engine)
        result = executor.execute(ToolCall(name="read", arguments={}))
        assert not result.ok
        assert "ToolPolicy required" in result.error
