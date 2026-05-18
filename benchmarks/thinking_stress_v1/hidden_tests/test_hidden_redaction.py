"""Hidden tests for redaction.py — AGENTS CANNOT SEE THESE.

Tests edge cases: multiple secrets, no over-redaction, various patterns.
"""

from mini_agent_runtime.redaction import redact_secrets


def test_multiple_secrets_all_redacted():
    text = (
        "api_key=sk-abc123def456, "
        "bearer=Authorization: Bearer xyz789uvw012, "
        "aws=AKIAIOSFODNN7EXAMPLE"
    )
    out = redact_secrets(text)
    assert "sk-abc123def456" not in out
    assert "xyz789uvw012" not in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    # Structural parts preserved
    assert "api_key" in out
    assert "Authorization" in out
    assert "aws" in out


def test_redaction_preserves_normal_json():
    """Redaction should not alter normal JSON structure."""
    text = '{"name": "Alice", "age": 30, "city": "Beijing"}'
    out = redact_secrets(text)
    assert '"name"' in out
    assert '"Alice"' in out
    assert '"age"' in out


def test_redacts_gitlab_token():
    text = "CI token: glpat-EXAMPLE0000000000000000"
    assert "glpat-EXAMPLE0000000000000000" not in redact_secrets(text)


def test_redacts_slack_token():
    text = "xoxb-FAKE000000000-FAKE000000000-FAKE000000000000000000"
    assert "xoxb-" not in redact_secrets(text) or "FAKE000000000000000000" not in redact_secrets(text)


def test_redacts_private_key_header():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA..."
    out = redact_secrets(text)
    # At minimum the key content after header should be redacted
    assert "MIIEpAIBAA" not in out or len(out) < len(text)
