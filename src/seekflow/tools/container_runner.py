"""ContainerRunner — executes code_exec/destructive tools in isolated containers.

Wraps a ContainerSandbox and treats the tool function's return value as either a
CodeExecutionRequest or a code string.

SECURITY BOUNDARY: The tool function runs IN-PROCESS to produce code for the
sandbox. To prevent arbitrary code execution on the host, ContainerRunner is
gated behind ToolPolicy(trusted=True, container_codegen_trusted=True). Only
safe code-builder functions that return CodeExecutionRequest are allowed.
"""
from __future__ import annotations

import time as _time
from dataclasses import dataclass

from seekflow.tools.runners import ToolRunResult


@dataclass(frozen=True)
class CodeExecutionRequest:
    """A tool function returns this to request sandboxed code execution."""

    code: str
    env: dict[str, str] | None = None


class ContainerRunner:
    """Runs code_exec/destructive tools via a configured ContainerSandbox.

    SECURITY: The tool function is called in-process to produce the code
    specification. Only functions with ToolPolicy(trusted=True,
    container_codegen_trusted=True) are accepted — these must be safe
    code-builder functions that return CodeExecutionRequest, NOT arbitrary
    tool implementations.

    The generated code is then run inside the sandbox with hard isolation.
    """

    name = "container"

    def __init__(self, sandbox):
        self._sandbox = sandbox

    def run(
        self,
        func,
        arguments: dict,
        timeout_s: float,
        *,
        max_output_bytes: int = 100_000,
    ) -> ToolRunResult:
        start = _time.monotonic()

        # Step 1: call tool function in-process to get code spec
        try:
            request = func(**arguments)
        except Exception as e:
            return ToolRunResult(
                ok=False,
                error=f"Tool function failed before sandbox execution: {e}",
                runner_name=self.name,
                elapsed_ms=int((_time.monotonic() - start) * 1000),
            )

        # Step 2: extract code from result
        if isinstance(request, CodeExecutionRequest):
            code = request.code
            env = request.env
        elif isinstance(request, str):
            code = request
            env = None
        else:
            return ToolRunResult(
                ok=False,
                error=(
                    "ContainerRunner requires tool to return a CodeExecutionRequest "
                    f"or code string, got {type(request).__name__}"
                ),
                runner_name=self.name,
                elapsed_ms=int((_time.monotonic() - start) * 1000),
            )

        # Step 3: execute inside sandbox
        try:
            sandbox_result = self._sandbox.execute(
                code, timeout=timeout_s, env=env,
            )
        except Exception as e:
            return ToolRunResult(
                ok=False,
                error=f"Sandbox execution failed: {e}",
                runner_name=self.name,
                elapsed_ms=int((_time.monotonic() - start) * 1000),
            )

        # Step 4: bound output
        from seekflow.tools.limits import serialize_bounded

        output = sandbox_result.stdout or ""
        if sandbox_result.stderr:
            output += f"\n[stderr]: {sandbox_result.stderr[:1000]}"

        bounded, truncated = serialize_bounded(output, max_output_bytes)

        return ToolRunResult(
            ok=sandbox_result.ok,
            result=bounded,
            error=sandbox_result.error,
            runner_name=self.name,
            elapsed_ms=sandbox_result.elapsed_ms,
            killed="timed out" in (sandbox_result.error or "").lower(),
            output_truncated=truncated,
        )
