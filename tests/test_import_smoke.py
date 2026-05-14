"""Import smoke tests — ensure all public APIs are importable."""
import importlib
import sys
import pytest


def test_public_imports():
    import seekflow
    from seekflow import DeepSeekAgent, tool
    from seekflow.runtime import ToolRuntime
    from seekflow.client import DeepSeekClient
    from seekflow.tools.executor import ToolExecutor
    from seekflow.policy import PolicyEngine
    from seekflow.execution.context import ToolExecutionContext
    from seekflow.execution.approval import ApprovalRequest
    assert seekflow.__version__ == "0.2.5"


def test_package_contains_required_submodules():
    for mod in [
        "seekflow.tools.builtins",
        "seekflow.deepseek.params",
        "seekflow.deepseek.protocol",
        "seekflow.deepseek.adapter",
        "seekflow.security.http",
    ]:
        importlib.import_module(mod)


def test_errors_import():
    from seekflow.errors import (
        SeekFlowError, DeepSeekAPIError, BadRequestError,
        AuthenticationError, PaymentRequiredError, RateLimitError,
        InsufficientBalanceError, ContextLengthExceededError,
        ServiceUnavailableError, PermissionDeniedError,
        map_http_error, ToolNotFoundError, ToolExecutionError,
    )
    assert issubclass(BadRequestError, DeepSeekAPIError)
    assert issubclass(PaymentRequiredError, DeepSeekAPIError)
    assert issubclass(PermissionDeniedError, DeepSeekAPIError)


def test_adapter_imports():
    from seekflow.deepseek.adapter import (
        DeepSeekAdapter, DeepSeekCapabilities, ThinkingConfig, NormalizedUsage,
    )
    caps = DeepSeekCapabilities()
    assert caps.supports_developer_role is False
    assert caps.supports_tool_choice_in_thinking is False

    thinking = ThinkingConfig(enabled=True, effort="high")
    assert thinking.enabled is True


def test_protocol_imports():
    from seekflow.deepseek.protocol import (
        ValidationIssue, validate_deepseek_messages,
        ConversationState, repair_deepseek_messages,
    )
    issue = ValidationIssue(code="test", message="test")
    assert issue.severity == "error"


def test_builtins_import():
    from seekflow.tools.builtins import (
        make_calculate, make_read_file, make_write_file,
        make_list_dir, make_fetch_url, make_python_exec, make_sqlite_query,
    )
    assert callable(make_calculate)
    assert callable(make_read_file)
    assert callable(make_list_dir)


@pytest.mark.skipif(
    "DEEPSEEK_API_KEY" not in __import__("os").environ,
    reason="No DEEPSEEK_API_KEY set"
)
def test_client_import_and_construction():
    from seekflow.client import DeepSeekClient
    client = DeepSeekClient()
    assert client.base_url.startswith("https://")
