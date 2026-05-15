"""PR-7: authorize_with_context() emits DeprecationWarning."""
import pytest

from seekflow.policy import PolicyEngine
from seekflow.types import ToolPolicy


class TestDeprecatedAPI:
    """authorize_with_context() must emit DeprecationWarning."""

    def test_authorize_with_context_emits_deprecation_warning(self):
        engine = PolicyEngine()
        policy = ToolPolicy(risk="read")
        ctx = engine._make_norm_ctx() if hasattr(engine, '_make_norm_ctx') else _make_ctx()
        with pytest.warns(DeprecationWarning, match="does not validate tool arguments"):
            engine.authorize_with_context(policy, ctx)


def _make_ctx():
    from seekflow.policy import ToolPolicyContext
    return ToolPolicyContext()
