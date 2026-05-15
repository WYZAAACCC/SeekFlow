"""Tool execution runners — InProcessRunner and ProcessRunner.

InProcessRunner is the ONLY place where tool_def.func(**arguments) may be
called directly. All other execution paths must go through a runner.
"""
from __future__ import annotations

import multiprocessing
from dataclasses import dataclass
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
    exit_code: int | None = None
    output_truncated: bool = False


def _run_in_subprocess(
    func,
    args: dict,
    queue: multiprocessing.Queue,
    max_output_bytes: int,
) -> None:
    """Target function executed in the child process. Bounds large string output."""
    try:
        from seekflow.tools.limits import serialize_bounded

        result = func(**args)
        if isinstance(result, str):
            bounded, truncated = serialize_bounded(result, max_output_bytes)
            queue.put({
                "ok": True,
                "result": bounded,
                "output_truncated": truncated,
            })
        else:
            queue.put({
                "ok": True,
                "result": result,
                "output_truncated": False,
            })
    except Exception as e:
        queue.put({"ok": False, "error": str(e)})


class InProcessRunner:
    """Runs tool functions in the current process.

    Only suitable for trusted=True + risk="read" + parallel_safe=True tools.
    Does NOT provide hard timeout isolation — a blocking call blocks the caller.
    """

    name = "in_process"

    def run(
        self,
        func,
        arguments: dict,
        timeout_s: float,
        *,
        max_output_bytes: int = 100_000,
    ) -> ToolRunResult:
        import time

        start = time.monotonic()
        try:
            result = func(**arguments)
            elapsed = int((time.monotonic() - start) * 1000)
            return ToolRunResult(
                ok=True,
                result=result,
                runner_name=self.name,
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            return ToolRunResult(
                ok=False,
                error=str(e),
                runner_name=self.name,
                elapsed_ms=elapsed,
            )


class ProcessRunner:
    """Runs tool functions in a spawned child process with hard timeout.

    Uses multiprocessing.get_context("spawn") for cross-platform isolation.
    On timeout: terminate() → 0.5s grace → kill().
    The tool function MUST be pickleable (no closures or lambdas).

    Hardening (semi-production):
    - Queue maxsize=1 to prevent unbounded buffering
    - queue.get timeout to prevent hang on crashed child
    - exit_code recorded on every result
    - Output bounded in child process via serialize_bounded
    - queue.close / join_thread / proc.close for clean resource cleanup
    """

    name = "process"

    def run(
        self,
        func,
        arguments: dict,
        timeout_s: float,
        *,
        max_output_bytes: int = 100_000,
    ) -> ToolRunResult:
        import time

        if timeout_s is None or timeout_s <= 0:
            timeout_s = 30.0

        ctx = multiprocessing.get_context("spawn")
        queue: multiprocessing.Queue = ctx.Queue(maxsize=1)
        proc = ctx.Process(
            target=_run_in_subprocess,
            args=(func, arguments, queue, max_output_bytes),
        )
        start = time.monotonic()
        proc.start()
        exit_code: int | None = None

        # Wait for result with timeout
        proc.join(timeout_s)
        elapsed = int((time.monotonic() - start) * 1000)

        if proc.is_alive():
            # Hard kill: terminate → grace → kill
            proc.terminate()
            proc.join(0.5)
            if proc.is_alive():
                proc.kill()
                proc.join(1.0)
            exit_code = proc.exitcode
            try:
                queue.close()
                queue.join_thread()
            except Exception:
                pass
            proc.close()
            return ToolRunResult(
                ok=False,
                error=f"Tool timed out after {timeout_s}s and was killed",
                killed=True,
                runner_name=self.name,
                elapsed_ms=elapsed,
                exit_code=exit_code,
            )

        exit_code = proc.exitcode

        # Process finished — get result from queue (with timeout safety)
        try:
            data = queue.get(timeout=0.5)
            data["runner_name"] = self.name
            data["elapsed_ms"] = elapsed
            data["exit_code"] = exit_code
            data.setdefault("output_truncated", False)
            return ToolRunResult(**data)
        except Exception:
            # Process exited but no result (crash / SIGSEGV / queue empty)
            return ToolRunResult(
                ok=False,
                error=f"Tool process exited with code {exit_code} without returning a result (possible crash)",
                killed=False,
                runner_name=self.name,
                elapsed_ms=elapsed,
                exit_code=exit_code,
            )
        finally:
            try:
                queue.close()
                queue.join_thread()
            except Exception:
                pass
            proc.close()
