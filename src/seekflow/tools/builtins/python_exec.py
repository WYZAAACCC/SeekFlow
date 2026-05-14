"""Safe Python execution tool factory — sandbox-required."""
from __future__ import annotations

import json as _json

from seekflow.sandbox import ToolSandbox, NoSandbox
from seekflow.tools.decorator import tool
from seekflow.types import ToolPolicy


def make_python_exec(
    *,
    sandbox: ToolSandbox,
    timeout_s: float = 10.0,
    max_output_bytes: int = 200_000,
) -> "ToolDefinition":
    """Create a sandbox-bound Python execution tool."""

    if isinstance(sandbox, NoSandbox):
        raise ValueError("Python execution requires a real sandbox, not NoSandbox")

    @tool(trusted=False)
    def run_python(code: str) -> str:
        result = sandbox.execute(code, timeout=timeout_s)
        return _json.dumps(
            {
                "ok": result.ok,
                "stdout": (result.stdout or "")[:max_output_bytes],
                "stderr": (result.stderr or "")[:50_000],
                "error": result.error,
                "elapsed_ms": result.elapsed_ms,
            },
            ensure_ascii=False,
        )

    return run_python.with_policy(ToolPolicy(
        capabilities={"code.exec"},
        risk="code_exec",
        timeout_s=timeout_s,
        max_input_bytes=200_000,
        max_output_bytes=max_output_bytes,
        parallel_safe=False,
        requires_approval=True,
    ))
