"""Phase E: SecretBroker — secret isolation tests."""
import pytest

from seekflow.secrets.types import SecretRef
from seekflow.secrets.broker import SecretBroker, _MemoryProvider, SecretAuditEntry


class TestSecretRef:
    """SecretRef model."""

    def test_defaults(self):
        ref = SecretRef(name="API_KEY")
        assert ref.name == "API_KEY"
        assert ref.scope == "tool"
        assert ref.required is True

    def test_optional_ref(self):
        ref = SecretRef(name="OPTIONAL_KEY", required=False)
        assert ref.required is False

    def test_ttl_ref(self):
        ref = SecretRef(name="TEMP_KEY", ttl_seconds=3600)
        assert ref.ttl_seconds == 3600


class TestSecretBroker:
    """SecretBroker resolution and audit."""

    def test_resolve_from_memory(self):
        broker = SecretBroker()
        provider = _MemoryProvider()
        provider.set("API_KEY", "secret-value")
        broker.register_provider("memory", provider)

        refs = [SecretRef(name="API_KEY")]
        result = broker.resolve_for_tool("test-tool", refs, run_id="run-1")
        assert result == {"API_KEY": "secret-value"}

    def test_required_unresolved_raises(self):
        broker = SecretBroker()
        refs = [SecretRef(name="MISSING_KEY", required=True)]
        with pytest.raises(ValueError, match="MISSING_KEY"):
            broker.resolve_for_tool("test-tool", refs, run_id="run-1")

    def test_optional_unresolved_is_ok(self):
        broker = SecretBroker()
        refs = [SecretRef(name="MISSING_KEY", required=False)]
        result = broker.resolve_for_tool("test-tool", refs, run_id="run-1")
        assert "MISSING_KEY" not in result

    def test_resolution_is_audited(self):
        broker = SecretBroker()
        provider = _MemoryProvider()
        provider.set("KEY", "val")
        broker.register_provider("memory", provider)

        broker.resolve_for_tool("test-tool", [SecretRef(name="KEY")], run_id="run-1")
        assert len(broker.audit_entries) == 1
        entry = broker.audit_entries[0]
        assert entry.secret_name == "KEY"
        assert entry.tool_name == "test-tool"
        assert entry.resolved is True

    def test_secret_value_never_in_audit(self):
        broker = SecretBroker()
        provider = _MemoryProvider()
        provider.set("KEY", "super-secret-value")
        broker.register_provider("memory", provider)

        broker.resolve_for_tool("test-tool", [SecretRef(name="KEY")], run_id="run-1")
        entry = broker.audit_entries[0]
        # Audit entry has no 'value' field — only SecretAuditEntry fields
        assert not hasattr(entry, "value")
        assert "super-secret" not in str(entry.__dict__)

    def test_multiple_refs_resolved(self):
        broker = SecretBroker()
        provider = _MemoryProvider()
        provider.set("KEY1", "val1")
        provider.set("KEY2", "val2")
        broker.register_provider("memory", provider)

        refs = [SecretRef(name="KEY1"), SecretRef(name="KEY2")]
        result = broker.resolve_for_tool("test-tool", refs)
        assert result == {"KEY1": "val1", "KEY2": "val2"}
        assert len(broker.audit_entries) == 2


class TestEnvProvider:
    """SecretBroker env provider (allowlist-based)."""

    def test_resolves_from_env(self):
        import os
        os.environ["SEEKFLOW_TEST_SECRET"] = "from-env"
        try:
            broker = SecretBroker()
            refs = [SecretRef(name="SEEKFLOW_TEST_SECRET")]
            result = broker.resolve_for_tool("test-tool", refs)
            assert result == {"SEEKFLOW_TEST_SECRET": "from-env"}
        finally:
            del os.environ["SEEKFLOW_TEST_SECRET"]

    def test_env_missing_returns_none(self):
        broker = SecretBroker()
        refs = [SecretRef(name="NONEXISTENT_ENV_VAR", required=False)]
        result = broker.resolve_for_tool("test-tool", refs)
        assert result == {}
