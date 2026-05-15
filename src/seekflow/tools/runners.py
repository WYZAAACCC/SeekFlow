"""Tool execution runners — InProcessRunner and ProcessRunner.

InProcessRunner is the ONLY place where tool_def.func(**arguments) may be
called directly. All other execution paths must go through a runner.
"""
from __future__ import annotations

import multiprocessing
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolRunResult:
    """Result of a runner execution."""

    ok: bool
    result: Any = None
    error: str | None = None
    killed: bool = False
    runner_name: str = ""
    elapsed_ms: int = 0


def _run_in_subprocess(func, args: dict, queue: multiprocessing.Queue) -> None:
    """Target function executed in the child process."""
    try:
        result = func(**args)
        queue.put({"ok": True, "result": result})
    except Exception as e:
        queue.put({"ok": False, "error": str(e)})


class InProcessRunner:
    """Runs tool functions in the current process.

    Only suitable for trusted=True + risk="read" + parallel_safe=True tools.
    Does NOT provide hard timeout isolation — a blocking call blocks the caller.
    """

    name = "in_process"

    def run(self, func, arguments: dict, timeout_s: float) -> ToolRunResult:
        import time
        start = time.monotonic()
        try:
            result = func(**arguments)
            elapsed = int((time.monotonic() - start) * 1000)
            return ToolRunResult(
                ok=True, result=result, runner_name=self.name, elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            return ToolRunResult(
                ok=False, error=str(e), runner_name=self.name, elapsed_ms=elapsed,
            )


class ProcessRunner:
    """Runs tool functions in a spawned child process with hard timeout.

    Uses multiprocessing.get_context("spawn") for cross-platform isolation.
    On timeout: terminate() → 0.5s grace → kill().
    The tool function MUST be pickleable (no closures or lambdas).
    """

    name = "process"

    def run(self, func, arguments: dict, timeout_s: float) -> ToolRunResult:
        import time

        if timeout_s is None or timeout_s <= 0:
            timeout_s = 30.0

        ctx = multiprocessing.get_context("spawn")
        queue: multiprocessing.Queue = ctx.Queue()
        proc = ctx.Process(target=_run_in_subprocess, args=(func, arguments, queue))
        start = time.monotonic()
        proc.start()

        try:
            # Wait for result with timeout
            proc.join(timeout_s)
        except Exception:
            pass  # join can raise on some platforms, handled below

        elapsed = int((time.monotonic() - start) * 1000)

        if proc.is_alive():
            # Hard kill: terminate → grace → kill
            proc.terminate()
            proc.join(0.5)
            if proc.is_alive():
                proc.kill()
                proc.join(1.0)
            return ToolRunResult(
                ok=False,
                error=f"Tool timed out after {timeout_s}s and was killed",
                killed=True,
                runner_name=self.name,
                elapsed_ms=elapsed,
            )

        # Process finished — get result from queue
        try:
            data = queue.get_nowait()
            data["runner_name"] = self.name
            data["elapsed_ms"] = elapsed
            return ToolRunResult(**data)
        except Exception:
            # Process exited but no result (crash / SIGSEGV)
            return ToolRunResult(
                ok=False,
                error="Tool process exited without returning a result (possible crash)",
                killed=False,
                runner_name=self.name,
                elapsed_ms=elapsed,
            )
        finally:
            proc.close()
