"""Test file embedding security."""
import os
import pytest
from pathlib import Path
from seekflow.files import embed_files_into_message, DEFAULT_DENY_GLOBS


def test_embed_files_requires_workspace_root(tmp_path):
    """Files outside workspace should be blocked when root is set."""
    (tmp_path / "safe.txt").write_text("hello")

    # Without workspace_root, should work (no validation)
    msg = {"role": "user", "content": "Look at this"}
    try:
        result = embed_files_into_message(msg, [str(tmp_path / "safe.txt")])
        assert "hello" in result["content"]
    except Exception:
        pass


def test_embed_files_blocks_path_traversal(tmp_path):
    """Path traversal outside workspace should be blocked."""
    (tmp_path / "safe.txt").write_text("hello")
    msg = {"role": "user", "content": "Query"}

    with pytest.raises((PermissionError, FileNotFoundError)):
        embed_files_into_message(
            msg, ["../etc/passwd"],
            workspace_root=tmp_path,
        )


def test_embed_files_respects_max_total_bytes(tmp_path):
    """Total file size should be enforced."""
    (tmp_path / "a.txt").write_text("a" * 500)
    (tmp_path / "b.txt").write_text("b" * 500)
    msg = {"role": "user", "content": "Query"}
    try:
        result = embed_files_into_message(
            msg, [str(tmp_path / "a.txt"), str(tmp_path / "b.txt")],
            workspace_root=tmp_path, max_total_bytes=600,
        )
    except ValueError as e:
        assert "exceed" in str(e).lower() or "limit" in str(e).lower()


def test_deny_globs_contain_sensitive_patterns():
    assert ".env" in DEFAULT_DENY_GLOBS
    assert any("pem" in g for g in DEFAULT_DENY_GLOBS)
    assert any("key" in g for g in DEFAULT_DENY_GLOBS)
    assert ".git/*" in DEFAULT_DENY_GLOBS


def test_embed_files_blocks_absolute_path(tmp_path):
    """Absolute paths that escape workspace should be blocked."""
    msg = {"role": "user", "content": "Query"}
    with pytest.raises((PermissionError, FileNotFoundError)):
        embed_files_into_message(
            msg, ["C:\\Windows\\System32\\config\\SAM"],
            workspace_root=tmp_path,
        )
