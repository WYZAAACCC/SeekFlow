"""Tests for redaction.py — Secret redaction completeness."""

from mini_agent_runtime.redaction import redact_secrets


def test_redacts_deepseek_key():
    text = "api_key=sk-1234567890abcdef"
    assert "1234567890abcdef" not in redact_secrets(text)


def test_redacts_bearer_token():
    text = "Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456"
    out = redact_secrets(text)
    assert "abcdefghijklmnopqrstuvwxyz123456" not in out
    assert "Bearer" in out  # keyword preserved


def test_redacts_aws_access_key():
    text = "AWS key AKIAIOSFODNN7EXAMPLE leaked"
    assert "AKIAIOSFODNN7EXAMPLE" not in redact_secrets(text)


def test_redacts_jwt():
    token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signaturevalue"
    assert token not in redact_secrets(token)


def test_redacts_url_query_token():
    text = "GET https://api.example.com/data?token=secret123abc&other=val"
    out = redact_secrets(text)
    assert "secret123abc" not in out


def test_leaves_normal_text_intact():
    text = "The quick brown fox jumps over the lazy dog."
    out = redact_secrets(text)
    # Should preserve normal text structure
    assert "fox" in out and "dog" in out
    assert len(out) == len(text)


def test_redacts_github_token():
    text = "ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
    assert "ghp_A1b2C3d4E5f6G7h8I9j0" not in redact_secrets(text)
