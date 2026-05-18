"""Hidden tests for security.py — AGENTS CANNOT SEE THESE.

Tests bypass vectors that agents shouldn't know about:
integer IP, hex IP, IPv6 loopback, link-local, symlink escape, etc.
"""

import os
from pathlib import Path

import pytest

# Direct import from fixture_repo; scorer sets PYTHONPATH
from mini_agent_runtime.security import safe_join, validate_url


# ── validate_url: additional blocked IP forms ──

def test_validate_url_blocks_integer_localhost():
    """http://2130706433 is integer form of 127.0.0.1."""
    assert validate_url("http://2130706433/secret") is False


def test_validate_url_blocks_hex_localhost():
    """http://0x7f000001 is hex form of 127.0.0.1."""
    assert validate_url("http://0x7f000001/admin") is False


def test_validate_url_blocks_ipv6_loopback():
    assert validate_url("http://[::1]/api") is False


def test_validate_url_blocks_class_a_private():
    assert validate_url("http://10.0.0.1/internal") is False


def test_validate_url_blocks_class_b_private():
    assert validate_url("http://172.16.0.1/mgmt") is False


def test_validate_url_blocks_link_local():
    assert validate_url("http://169.254.100.1/config") is False


def test_validate_url_blocks_localhost_subdomain_evil():
    """localhost.evil.com should be allowed (not localhost)."""
    assert validate_url("http://localhost.evil.com/page") is True


def test_validate_url_blocks_multicast():
    assert validate_url("http://224.0.0.1/stream") is False


# ── safe_join: symlink escape ──

def test_safe_join_blocks_symlink_escape(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("secret")
    symlink = root / "link"
    # On Windows, symlinks may require admin; skip gracefully if fails
    try:
        symlink.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation requires elevated privileges on Windows")
    with pytest.raises(ValueError):
        safe_join(str(root), "link")


def test_safe_join_blocks_double_encoded_traversal(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    with pytest.raises(ValueError):
        safe_join(str(root), "%252e%252e/secret.txt")


def test_safe_join_handles_absolute_path_injection(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    with pytest.raises(ValueError):
        safe_join(str(root), "/etc/passwd")


# ── validate_url edge cases ──

def test_validate_url_blocks_reserved_ip():
    """0.0.0.0 should be blocked."""
    assert validate_url("http://0.0.0.0/debug") is False


def test_validate_url_allows_public_ip():
    """8.8.8.8 is a valid public DNS — should be allowed."""
    assert validate_url("http://8.8.8.8/resolve") is True
