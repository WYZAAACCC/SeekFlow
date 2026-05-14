"""Safe filesystem tool factory — workspace-bound read/write/list + trusted calculate."""
from __future__ import annotations

import json as _json
import operator as _op
import math as _math
from pathlib import Path

from seekflow.security import safe_join, validate_file_access
from seekflow.tools.decorator import tool
from seekflow.types import ToolPolicy

#: Safe operations allowed in calculate (no eval, no attribute access)
_SAFE_OPS: dict[str, object] = {
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum, "len": len,
    "int": int, "float": float, "str": str, "bool": bool,
    "pow": pow, "divmod": divmod,
    "sqrt": _math.sqrt, "log": _math.log, "log10": _math.log10,
    "ceil": _math.ceil, "floor": _math.floor,
    "add": _op.add, "sub": _op.sub, "mul": _op.mul,
    "truediv": _op.truediv, "floordiv": _op.floordiv, "mod": _op.mod,
    "neg": _op.neg, "pos": _op.pos,
    "eq": _op.eq, "ne": _op.ne, "lt": _op.lt, "le": _op.le, "gt": _op.gt, "ge": _op.ge,
    "and_": _op.and_, "or_": _op.or_, "not_": _op.not_,
    "pi": _math.pi, "e": _math.e, "tau": _math.tau,
}


def _safe_eval(expr: str) -> object:
    """Evaluate a restricted arithmetic/logic expression. No attribute access, no calls except safe ops."""
    code = compile(expr, "<calculate>", "eval")
    for name in code.co_names:
        if name not in _SAFE_OPS:
            raise ValueError(f"'{name}' is not an allowed operation")
    return eval(code, {"__builtins__": {}}, _SAFE_OPS)


def make_calculate() -> "ToolDefinition":
    """Create a trusted calculate tool — safe arithmetic, no side effects."""

    @tool(trusted=True, sanitize=False)
    def calculate(expression: str) -> str:
        """Evaluate a mathematical expression. Supports: +, -, *, /, **, %, //, sqrt, log, abs, round, min, max, sum, len, pi, e, int, float, and comparisons."""
        try:
            result = _safe_eval(expression)
        except Exception as e:
            return f"Calculation error: {e}"
        return _json.dumps(result, ensure_ascii=False)

    return calculate.with_policy(ToolPolicy(
        capabilities={"compute.basic"},
        risk="read",
        timeout_s=1.0,
        parallel_safe=True,
    ))


def make_list_dir(
    *,
    workspace_root: str | Path,
    max_entries: int = 200,
) -> "ToolDefinition":
    """Create a workspace-bound list_dir tool."""
    root = Path(workspace_root).resolve()

    @tool(trusted=False)
    def list_dir(path: str = ".") -> str:
        resolved = validate_file_access(
            path, workspace_root=root, max_bytes=0,
        ) if path != "." else safe_join(root, path)
        if path == ".":
            resolved = root
        entries = []
        count = 0
        for child in sorted(resolved.iterdir()):
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
        timeout_s=2.0,
        parallel_safe=True,
        path_params=frozenset({"path"}),
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
        timeout_s=2.0,
        max_output_bytes=max_file_bytes,
        parallel_safe=True,
        path_params=frozenset({"path"}),
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
        path_params=frozenset({"filename"}),
    ))
