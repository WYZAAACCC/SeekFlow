"""PR-4: Cache policy — only read tools or idempotent network with explicit opt-in are cached."""
import pytest

from seekflow.tools.executor import _cache_allowed
from seekflow.types import ToolDefinition, ToolPolicy


def _dummy_func():
    pass


def test_write_tool_result_not_cached():
    """write tool results are not cached, even if metadata.cache=True."""
    policy = ToolPolicy(risk="write", capabilities={"filesystem.write"})
    td = ToolDefinition(name="w", description="", parameters={}, func=_dummy_func,
                        policy=policy, metadata={"cache": True})
    assert not _cache_allowed(td)


def test_network_tool_not_cached_by_default():
    """network tool is not cached by default."""
    policy = ToolPolicy(risk="network", capabilities={"network.public_http"})
    td = ToolDefinition(name="n", description="", parameters={}, func=_dummy_func,
                        policy=policy, metadata={"cache": True})
    assert not _cache_allowed(td)


def test_idempotent_network_cache_with_explicit_opt_in():
    """idempotent=True + cache_network=True allows network caching."""
    policy = ToolPolicy(risk="network", capabilities={"network.public_http"},
                        idempotent=True)
    td = ToolDefinition(name="n", description="", parameters={}, func=_dummy_func,
                        policy=policy, metadata={"cache": True, "cache_network": True})
    assert _cache_allowed(td)


def test_no_policy_tool_not_cached():
    """No-policy tools are not cached."""
    td = ToolDefinition(name="bare", description="", parameters={}, func=_dummy_func,
                        policy=None, metadata={"cache": True})
    assert not _cache_allowed(td)


def test_read_tool_is_cached():
    """read tools are cached by default."""
    policy = ToolPolicy(risk="read")
    td = ToolDefinition(name="r", description="", parameters={}, func=_dummy_func,
                        policy=policy, metadata={"cache": True})
    assert _cache_allowed(td)


def test_read_tool_cache_disabled_via_metadata():
    """metadata.cache=False disables caching even for read tools."""
    policy = ToolPolicy(risk="read")
    td = ToolDefinition(name="r", description="", parameters={}, func=_dummy_func,
                        policy=policy, metadata={"cache": False})
    assert not _cache_allowed(td)


def test_idempotent_network_no_cache_network_flag_denied():
    """idempotent network without cache_network=True is not cached."""
    policy = ToolPolicy(risk="network", capabilities={"network.public_http"},
                        idempotent=True)
    td = ToolDefinition(name="n", description="", parameters={}, func=_dummy_func,
                        policy=policy, metadata={"cache": True})
    assert not _cache_allowed(td)


def test_code_exec_tool_not_cached():
    """code_exec tools are never cached."""
    policy = ToolPolicy(risk="code_exec", capabilities={"code.exec"})
    td = ToolDefinition(name="c", description="", parameters={}, func=_dummy_func,
                        policy=policy, metadata={"cache": True})
    assert not _cache_allowed(td)


def test_destructive_tool_not_cached():
    """destructive tools are never cached."""
    policy = ToolPolicy(risk="destructive")
    td = ToolDefinition(name="d", description="", parameters={}, func=_dummy_func,
                        policy=policy, metadata={"cache": True})
    assert not _cache_allowed(td)
