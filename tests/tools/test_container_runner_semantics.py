"""PR-2: ContainerRunner requires trusted code-generation tool policy."""
import pytest

from seekflow.tools.container_runner import ContainerRunner, CodeExecutionRequest
from seekflow.tools.runners import ToolRunResult
from seekflow.tools.executor import RunnerUnavailableError
from seekflow.types import ToolDefinition, ToolPolicy
from seekflow.tools.planner import ExecutionPlan


def _dummy_codegen(**kwargs):
    return CodeExecutionRequest(code="print('hello')")


def _dummy_plain(**kwargs):
    return {"data": "not a CodeExecutionRequest"}


class FakeContainerSandbox:
    """Fake sandbox that returns success."""
    name = "container"

    def execute(self, code, *, timeout=10.0, env=None):
        from seekflow.sandbox import SandboxResult
        return SandboxResult(ok=True, stdout=code, elapsed_ms=10)


class FakeNoContainerSandbox:
    """Fake sandbox that is NOT a container."""
    name = "no_sandbox"


class TestContainerRunnerCodegenGate:
    """ContainerRunner._runner_for() enforces container_codegen_trusted."""

    def test_container_runner_requires_trusted_codegen_policy(self):
        """No container_codegen_trusted → RunnerUnavailableError."""
        from seekflow.tools.executor import ToolExecutor
        from seekflow.tools.registry import ToolRegistry

        reg = ToolRegistry()
        td = ToolDefinition(
            name="code_tool",
            description="test",
            parameters={},
            func=_dummy_codegen,
            policy=ToolPolicy(risk="code_exec", capabilities={"code.exec"},
                              trusted=True),  # trusted but NOT container_codegen_trusted
        )
        reg.register(td)

        executor = ToolExecutor(reg, sandbox=FakeContainerSandbox(), policy_engine=None)
        plan = ExecutionPlan(runner="container", timeout_s=30.0, requires_hard_timeout=True,
                             allow_parallel=False, cache_allowed=False, reason="test")

        with pytest.raises(RunnerUnavailableError, match="container_codegen_trusted"):
            executor._runner_for(plan, td)

    def test_untrusted_container_codegen_denied(self):
        """trusted=False + container_codegen_trusted=True → rejected by model_validator at construction."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="container_codegen_trusted=True requires trusted=True"):
            ToolPolicy(risk="code_exec", capabilities={"code.exec"},
                       trusted=False, container_codegen_trusted=True)

    def test_container_runner_with_codegen_trusted_accepted(self):
        """trusted=True + container_codegen_trusted=True → container runner created."""
        from seekflow.tools.executor import ToolExecutor
        from seekflow.tools.registry import ToolRegistry

        reg = ToolRegistry()
        td = ToolDefinition(
            name="code_tool",
            description="test",
            parameters={},
            func=_dummy_codegen,
            policy=ToolPolicy(risk="code_exec", capabilities={"code.exec"},
                              trusted=True, container_codegen_trusted=True),
        )
        reg.register(td)

        executor = ToolExecutor(reg, sandbox=FakeContainerSandbox(), policy_engine=None)
        plan = ExecutionPlan(runner="container", timeout_s=30.0, requires_hard_timeout=True,
                             allow_parallel=False, cache_allowed=False, reason="test")

        runner = executor._runner_for(plan, td)
        assert runner.name == "container"

    def test_container_runner_rejects_plain_object_result(self):
        """Returning non-CodeExecutionRequest/non-str from tool function → error."""
        sandbox = FakeContainerSandbox()
        runner = ContainerRunner(sandbox)
        result = runner.run(_dummy_plain, {}, timeout_s=5.0)
        assert not result.ok
        assert "CodeExecutionRequest" in result.error

    def test_no_policy_container_denied(self):
        """Container runner without any policy → RunnerUnavailableError."""
        from seekflow.tools.executor import ToolExecutor
        from seekflow.tools.registry import ToolRegistry

        reg = ToolRegistry()
        td = ToolDefinition(
            name="code_tool",
            description="test",
            parameters={},
            func=_dummy_codegen,
            policy=None,
        )
        reg.register(td)

        executor = ToolExecutor(reg, sandbox=FakeContainerSandbox(), policy_engine=None)
        plan = ExecutionPlan(runner="container", timeout_s=30.0, requires_hard_timeout=True,
                             allow_parallel=False, cache_allowed=False, reason="test")

        with pytest.raises(RunnerUnavailableError, match="container_codegen_trusted"):
            executor._runner_for(plan, td)
