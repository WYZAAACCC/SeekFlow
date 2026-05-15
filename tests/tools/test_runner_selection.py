"""Tests for execution planner — runner selection logic."""
import pytest

from seekflow.tools.planner import ExecutionPlan, plan_execution
from seekflow.types import ToolDefinition, ToolPolicy


def _dummy_func():
    pass


def make_tool(
    risk="read",
    capabilities=None,
    trusted=False,
    parallel_safe=False,
    runner="auto",
    policy=None,
    metadata=None,
):
    """Helper to build a ToolDefinition with the given policy values."""
    if policy is None:
        policy = ToolPolicy(
            risk=risk,
            capabilities=capabilities or set(),
            trusted=trusted,
            parallel_safe=parallel_safe,
            runner=runner,
        )
    return ToolDefinition(
        name="test_tool",
        description="A test tool",
        parameters={"type": "object", "properties": {}},
        func=_dummy_func,
        policy=policy,
        metadata=metadata or {},
    )


class TestRunnerSelection:
    """plan_execution must route tools to the correct runner."""

    def test_trusted_read_parallel_safe_uses_in_process(self):
        td = make_tool(risk="read", trusted=True, parallel_safe=True)
        plan = plan_execution(td, timeout=30.0)
        assert plan.runner == "in_process"

    def test_network_uses_process(self):
        td = make_tool(risk="network", capabilities={"network.public_http"})
        plan = plan_execution(td, timeout=30.0)
        assert plan.runner == "process"

    def test_write_uses_process(self):
        td = make_tool(risk="write", capabilities={"filesystem.write"})
        plan = plan_execution(td, timeout=30.0)
        assert plan.runner == "process"

    def test_code_exec_uses_container(self):
        td = make_tool(risk="code_exec", capabilities={"code.exec"})
        plan = plan_execution(td, timeout=30.0)
        assert plan.runner == "container"

    def test_destructive_uses_container(self):
        td = make_tool(risk="destructive")
        plan = plan_execution(td, timeout=30.0)
        assert plan.runner == "container"

    def test_explicit_runner_override_wins(self):
        td = make_tool(risk="write", capabilities={"filesystem.write"}, runner="container")
        plan = plan_execution(td, timeout=30.0)
        assert plan.runner == "container"

    def test_no_policy_defaults_to_process(self):
        """Untrusted tools without a policy get process isolation."""
        td = ToolDefinition(
            name="bare_tool",
            description="No policy",
            parameters={"type": "object", "properties": {}},
            func=_dummy_func,
        )
        plan = plan_execution(td, timeout=30.0)
        assert plan.runner == "process"

    def test_no_policy_trusted_metadata_uses_in_process(self):
        """When no policy but metadata declares trusted, use in_process."""
        td = ToolDefinition(
            name="bare_trusted",
            description="No policy but trusted",
            parameters={"type": "object", "properties": {}},
            func=_dummy_func,
            metadata={"trusted": True},
        )
        plan = plan_execution(td, timeout=30.0)
        assert plan.runner == "in_process"

    def test_plan_includes_timeout(self):
        td = make_tool(risk="read", trusted=True, parallel_safe=True)
        plan = plan_execution(td, timeout=45.0)
        # Policy default (30.0) is ceiling; arg (45.0) is clamped to policy max
        assert plan.timeout_s == 30.0

    def test_arg_timeout_used_when_shorter_than_policy(self):
        td = make_tool(risk="read", trusted=True, parallel_safe=True)
        plan = plan_execution(td, timeout=15.0)
        # Caller timeout (15.0) is shorter than policy default (30.0)
        assert plan.timeout_s == 15.0

    def test_no_policy_uses_arg_timeout(self):
        td = ToolDefinition(
            name="bare",
            description="No policy",
            parameters={"type": "object", "properties": {}},
            func=_dummy_func,
        )
        plan = plan_execution(td, timeout=60.0)
        assert plan.timeout_s == 60.0

    def test_policy_timeout_ceil_clamps_arg(self):
        td = make_tool(risk="read", trusted=True, parallel_safe=True)
        td.policy.timeout_s = 60.0
        plan = plan_execution(td, timeout=30.0)
        # Caller timeout (30.0) is shorter than policy ceiling (60.0)
        assert plan.timeout_s == 30.0

    def test_policy_timeout_ceil_caps_arg(self):
        td = make_tool(risk="read", trusted=True, parallel_safe=True)
        td.policy.timeout_s = 10.0
        plan = plan_execution(td, timeout=30.0)
        # Policy ceiling (10.0) caps caller timeout (30.0)
        assert plan.timeout_s == 10.0

    def test_code_exec_requires_hard_timeout(self):
        td = make_tool(risk="code_exec", capabilities={"code.exec"})
        plan = plan_execution(td, timeout=30.0)
        assert plan.requires_hard_timeout

    def test_in_process_no_hard_timeout(self):
        td = make_tool(risk="read", trusted=True, parallel_safe=True)
        plan = plan_execution(td, timeout=30.0)
        assert not plan.requires_hard_timeout

    def test_read_not_trusted_uses_process(self):
        """Read tools that are not trusted still get process isolation."""
        td = make_tool(risk="read", trusted=False)
        plan = plan_execution(td, timeout=30.0)
        assert plan.runner == "process"

    def test_plan_reason_is_set(self):
        td = make_tool(risk="network", capabilities={"network.public_http"})
        plan = plan_execution(td, timeout=30.0)
        assert plan.reason
