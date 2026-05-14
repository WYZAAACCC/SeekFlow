"""Safe Python execution tool factory — sandbox-required."""
from __future__ import annotations

from seekflow.sandbox import ToolSandbox, NoSandbox
from seekflow.tools.decorator import tool
from seekflow.types import ToolPolicy


def make_python_exec(
    *,
    sandbox: ToolSandbox,
    timeout_s: float = 10.0,
) -> "ToolDefinition":
    """Create a sandbox-bound Python execution tool."""

    if isinstance(sandbox, NoSandbox):
        raise ValueError("Python execution requires a real sandbox, not NoSandbox")

    @tool(trusted=False)
    def run_python(code: str) -> str:
        result = sandbox.execute(code, timeout=timeout_s)
        if not result.ok:
            return f"[sandbox error] {result.error or result.stderr}"
        return result.stdout or "[no output]"

    return run_python.with_policy(ToolPolicy(
        capabilities={"code.exec"},
        risk="code_exec",
        timeout_s=timeout_s,
        parallel_safe=False,
        requires_approval=True,
    ))
