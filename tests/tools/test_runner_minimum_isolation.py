"""PR-1: Runner override must not weaken isolation — explicit runner can only increase isolation."""
import pytest
from pathlib import Path

from seekflow.tools.planner import plan_execution, RUNNER_ORDER, _required_runner
from seekflow.types import ToolDefinition, ToolPolicy


def _dummy_func():
    pass


def test_code_exec_runner_process_upgraded_to_container():
    """code_exec requesting process runner is auto-upgraded to container."""
    policy = ToolPolicy(risk="code_exec", capabilities={"code.exec"}, runner="process", trusted=True)
    td = ToolDefinition(name="x", description="", parameters={}, func=lambda: 1, policy=policy)
    plan = plan_execution(td, timeout=30)
    assert plan.runner == "container"


def test_destructive_runner_in_process_upgraded_to_container():
    """destructive requesting in_process runner is auto-upgraded to container."""
    policy = ToolPolicy(risk="destructive", runner="in_process", trusted=True)
    td = ToolDefinition(name="x", description="", parameters={}, func=lambda: 1, policy=policy)
    plan = plan_execution(td, timeout=30)
    assert plan.runner == "container"


def test_network_runner_in_process_upgraded_to_process():
    """network requesting in_process is auto-upgraded to process."""
    policy = ToolPolicy(risk="network", runner="in_process", trusted=True,
                        capabilities={"network.public_http"},
                        allowed_domains={"example.com"}, url_params=frozenset({"url"}))
    td = ToolDefinition(name="x", description="",
                        parameters={"type": "object", "properties": {"url": {"type": "string"}}},
                        func=lambda url: "ok", policy=policy)
    plan = plan_execution(td, timeout=30)
    assert plan.runner == "process"


def test_write_runner_in_process_upgraded_to_process():
    """write requesting in_process is auto-upgraded to process."""
    policy = ToolPolicy(risk="write", runner="in_process", trusted=True,
                        capabilities={"filesystem.write"},
                        workspace_root=Path("/tmp"), path_params=frozenset({"path"}))
    td = ToolDefinition(name="x", description="",
                        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
                        func=lambda path: "ok", policy=policy)
    plan = plan_execution(td, timeout=30)
    assert plan.runner == "process"


def test_read_runner_container_allowed_as_stronger_isolation():
    """read tool can explicitly upgrade to container (stronger isolation)."""
    policy = ToolPolicy(risk="read", runner="container")
    td = ToolDefinition(name="x", description="", parameters={}, func=lambda: 1, policy=policy)
    plan = plan_execution(td, timeout=30)
    assert plan.runner == "container"


def test_read_runner_process_allowed_as_stronger_isolation():
    """read tool can explicitly upgrade to process."""
    policy = ToolPolicy(risk="read", runner="process")
    td = ToolDefinition(name="x", description="", parameters={}, func=lambda: 1, policy=policy)
    plan = plan_execution(td, timeout=30)
    assert plan.runner == "process"


def test_explicit_container_for_write_allowed():
    """write tool with explicit container runner is allowed (upgrade)."""
    policy = ToolPolicy(risk="write", capabilities={"filesystem.write"}, runner="container",
                        trusted=True)
    td = ToolDefinition(name="x", description="", parameters={}, func=lambda: 1, policy=policy)
    plan = plan_execution(td, timeout=30)
    assert plan.runner == "container"


def test_explicit_process_for_code_exec_upgraded_to_container():
    """code_exec with explicit process runner is upgraded to container."""
    policy = ToolPolicy(risk="code_exec", capabilities={"code.exec"}, runner="process",
                        trusted=True)
    td = ToolDefinition(name="x", description="", parameters={}, func=lambda: 1, policy=policy)
    plan = plan_execution(td, timeout=30)
    assert plan.runner == "container"


class TestRunnerOrder:
    """RUNNER_ORDER defines the isolation hierarchy."""

    def test_in_process_lowest(self):
        assert RUNNER_ORDER["in_process"] < RUNNER_ORDER["process"] < RUNNER_ORDER["container"]

    def test_required_runner_for_destructive(self):
        policy = ToolPolicy(risk="destructive")
        assert _required_runner(policy) == "container"

    def test_required_runner_for_code_exec(self):
        policy = ToolPolicy(risk="code_exec", capabilities={"code.exec"})
        assert _required_runner(policy) == "container"

    def test_required_runner_for_network(self):
        policy = ToolPolicy(risk="network", capabilities={"network.public_http"})
        assert _required_runner(policy) == "process"

    def test_required_runner_for_trusted_read(self):
        policy = ToolPolicy(risk="read", trusted=True, parallel_safe=True)
        assert _required_runner(policy) == "in_process"

    def test_required_runner_defaults_to_process(self):
        policy = ToolPolicy(risk="read", trusted=False)
        assert _required_runner(policy) == "process"
