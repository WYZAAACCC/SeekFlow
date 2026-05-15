"""PR-5: Trusted output controlled by ToolPolicy.trusted_output, not metadata.trusted."""
import json
import warnings

import pytest

from seekflow.types import ToolDefinition, ToolPolicy, ToolCall
from seekflow.tools.registry import ToolRegistry
from seekflow.tools.executor import ToolExecutor


def _dummy_read():
    return "public data"


def _dummy_sensitive():
    return "api_key = sk-abc123def456"


class TestTrustedOutputPolicy:
    """ToolPolicy.trusted_output controls output wrapping."""

    def test_metadata_trusted_does_not_skip_untrusted_wrap(self):
        """metadata.trusted=True alone does NOT skip untrusted wrapping."""
        policy = ToolPolicy(risk="read", trusted=True)  # execution trusted, not output
        td = ToolDefinition(
            name="t", description="", parameters={}, func=_dummy_read,
            policy=policy, metadata={"trusted": True},
        )
        reg = ToolRegistry()
        reg.register(td)
        executor = ToolExecutor(reg)

        result = executor.execute(ToolCall(name="t", arguments={}))
        assert result.ok
        # Result should be wrapped (untrusted content format)
        assert "[Tool Result" in str(result.result)

    def test_policy_trusted_execution_still_wraps_output_by_default(self):
        """trusted=True (execution trusted) does not automatically set trusted_output."""
        policy = ToolPolicy(risk="read", trusted=True)
        td = ToolDefinition(
            name="t", description="", parameters={}, func=_dummy_read,
            policy=policy,
        )
        reg = ToolRegistry()
        reg.register(td)
        executor = ToolExecutor(reg)

        result = executor.execute(ToolCall(name="t", arguments={}))
        assert result.ok
        # Still wrapped because trusted_output defaults to False
        assert "[Tool Result" in str(result.result)

    def test_policy_trusted_output_skips_wrap_but_still_redacts(self):
        """trusted_output=True skips untrusted wrap but still redacts secrets."""
        policy = ToolPolicy(risk="read", trusted=True, trusted_output=True)
        td = ToolDefinition(
            name="t", description="", parameters={}, func=_dummy_sensitive,
            policy=policy,
        )
        reg = ToolRegistry()
        reg.register(td)
        executor = ToolExecutor(reg)

        result = executor.execute(ToolCall(name="t", arguments={}))
        assert result.ok
        result_str = str(result.result)
        # Not wrapped
        assert "[Tool Result" not in result_str
        # But secrets still redacted
        assert "sk-abc" not in result_str or "[REDACTED" in result_str

    def test_default_output_is_wrapped_and_redacted(self):
        """Default (no trusted_output) wraps AND redacts output."""
        policy = ToolPolicy(risk="read")
        td = ToolDefinition(
            name="t", description="", parameters={}, func=_dummy_sensitive,
            policy=policy,
        )
        reg = ToolRegistry()
        reg.register(td)
        executor = ToolExecutor(reg)

        result = executor.execute(ToolCall(name="t", arguments={}))
        assert result.ok
        result_str = str(result.result)
        assert "[Tool Result" in result_str

    def test_metadata_trusted_emits_deprecation_warning(self):
        """metadata.trusted without policy.trusted_output emits DeprecationWarning."""
        policy = ToolPolicy(risk="read")
        td = ToolDefinition(
            name="t", description="", parameters={}, func=_dummy_read,
            policy=policy, metadata={"trusted": True},
        )
        reg = ToolRegistry()
        reg.register(td)
        executor = ToolExecutor(reg)

        with pytest.warns(DeprecationWarning, match="metadata.trusted is deprecated"):
            executor.execute(ToolCall(name="t", arguments={}))
