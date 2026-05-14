"""Safe filesystem tool factory — workspace-bound read/write/list."""
from __future__ import annotations

import json as _json
from pathlib import Path

from seekflow.security import safe_join, validate_file_access
from seekflow.tools.decorator import tool
from seekflow.types import ToolPolicy


def make_list_dir(
    *,
    workspace_root: str | Path,
    max_entries: int = 200,
) -> "ToolDefinition":
    """Create a workspace-bound list_dir tool."""
    root = Path(workspace_root).resolve()

    @tool(trusted=False)
    def list_dir(path: str = ".") -> str:
        if path == ".":
            target = root
        else:
            target = validate_file_access(
                path, workspace_root=root, max_bytes=None,
            )
        entries = []
        count = 0
        for child in sorted(target.iterdir()):
            if count >= max_entries:
                entries.append("... [truncated]")
                break
            suffix = "/" if child.is_dir() else ""
            try:
                size = child.stat().st_size
            except OSError:
                size = 0
            entries.append(f"{child.name}{suffix}  ({size} bytes)")
            count += 1
        return "\n".join(entries) if entries else "(empty directory)"

    return list_dir.with_policy(ToolPolicy(
        capabilities={"filesystem.read"},
        risk="read",
        workspace_root=root,
        path_params=frozenset({"path"}),
        timeout_s=2.0,
        max_input_bytes=10_000,
        max_output_bytes=100_000,
        parallel_safe=True,
    ))


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
        path_params=frozenset({"path"}),
        timeout_s=2.0,
        max_input_bytes=100_000,
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
        path_params=frozenset({"filename"}),
        timeout_s=5.0,
        max_input_bytes=max_file_bytes + 10_000,
        max_output_bytes=10_000,
        requires_approval=True,
        parallel_safe=False,
    ))
