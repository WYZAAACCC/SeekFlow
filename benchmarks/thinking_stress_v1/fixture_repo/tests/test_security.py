"""Tests for security.py — Path sandbox and SSRF protection."""

import os
from pathlib import Path

import pytest

from mini_agent_runtime.security import safe_join, validate_url


def test_safe_join_blocks_parent_traversal(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    with pytest.raises(ValueError):
        safe_join(str(root), "../secret.txt")


def test_safe_join_blocks_percent_encoded_traversal(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    with pytest.raises(ValueError):
        safe_join(str(root), "%2e%2e/secret.txt")


def test_validate_url_blocks_metadata_endpoint():
    assert validate_url("http://169.254.169.254/latest/meta-data") is False


def test_validate_url_allows_explicit_allowed_domain():
    assert validate_url("https://api.example.com/v1", {"api.example.com"}) is True


def test_validate_url_blocks_private_ip():
    assert validate_url("http://192.168.1.10/admin") is False


def test_safe_join_allows_normal_path(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    candidate = safe_join(str(root), "src/app.py")
    assert candidate == root / "src" / "app.py"


def test_validate_url_blocks_ftp():
    assert validate_url("ftp://evil.com/exfil") is False


def test_validate_url_blocks_disallowed_domain():
    assert validate_url("https://evil.com/malware", {"good.com"}) is False
