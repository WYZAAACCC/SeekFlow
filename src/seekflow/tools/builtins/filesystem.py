"""Safe filesystem tool factory — workspace-bound read/write."""
from __future__ import annotations

from pathlib import Path

from seekflow.security import safe_join, validate_file_access
from seekflow.tools.decorator import tool
from seekflow.types import ToolPolicy


def make_read_file(
    *,
    workspace_root: str | Path,
    allowed_extensions: set[str] | None = None,
    max_file_bytes: int = 5_000_000,
) -> "ToolDefinition":
    """Create a workspace-bound read_file tool."""
    root = Path(workspace_root).resolve()

    @tool(trusted=False)
    def read_file(path: str) -> str:
        resolved = validate_file_access(
            path, workspace_root=root,
            allow_ext=allowed_extensions, max_bytes=max_file_bytes,
        )
        try:
            content = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = resolved.read_bytes().decode("utf-8", errors="replace")
        if len(content) > max_file_bytes:
            content = content[:max_file_bytes] + "\n...[truncated]"
        return content

    return read_file.with_policy(ToolPolicy(
        capabilities={"filesystem.read"},
        risk="read",
        workspace_root=root,
        timeout_s=2.0,
        max_output_bytes=max_file_bytes,
        parallel_safe=True,
    ))


def make_write_file(
    *,
    workspace_root: str | Path,
    max_file_bytes: int = 1_000_000,
) -> "ToolDefinition":
    """Create a workspace-bound write_file tool. Requires approval by default."""
    root = Path(workspace_root).resolve()

    @tool(trusted=False)
    def write_file(filename: str, content: str) -> str:
        try:
            target = safe_join(root, filename)
        except PermissionError:
            return f"Write blocked: path '{filename}' is outside workspace"
        if len(content) > max_file_bytes:
            return f"Write blocked: content exceeds {max_file_bytes} bytes"
        target.write_text(content, encoding="utf-8")
        return f"Saved {len(content)} chars to {filename}"

    return write_file.with_policy(ToolPolicy(
        capabilities={"filesystem.write"},
        risk="write",
        workspace_root=root,
        requires_approval=True,
        timeout_s=5.0,
        parallel_safe=False,
    ))
