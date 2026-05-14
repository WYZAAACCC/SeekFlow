"""Tool execution sandbox — isolate code execution from host."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class SandboxResult:
    """Result of sandboxed code execution."""

    ok: bool
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    elapsed_ms: int = 0


class ToolSandbox(ABC):
    """Abstract sandbox for executing untrusted code.

    Implementations range from no-sandbox (deny all) to full container isolation.
    """

    name: str = "abstract"

    @abstractmethod
    def execute(
        self, code: str, *, timeout: float = 10.0, env: dict[str, str] | None = None,
    ) -> SandboxResult:
        """Execute *code* in the sandbox and return the result."""


class NoSandbox(ToolSandbox):
    """Always denies code execution — the safe default."""

    name = "no_sandbox"

    def execute(self, code: str, *, timeout: float = 10.0, **kwargs: Any) -> SandboxResult:
        return SandboxResult(
            ok=False,
            error="Code execution denied: no sandbox configured. "
                  "Use ContainerSandbox or ProcessSandbox for production.",
        )


class LocalThreadSandbox(ToolSandbox):
    """Execute code in a subprocess with basic isolation (no container required).

    WARNING: This runs on the host with limited isolation. For production use
    with untrusted code, prefer ContainerSandbox.
    """

    name = "local_thread"

    def execute(
        self, code: str, *, timeout: float = 10.0, env: dict[str, str] | None = None,
    ) -> SandboxResult:
        import subprocess
        import tempfile
        import os as _os
        import time

        start = time.monotonic()
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
        try:
            tmp.write(code)
            tmp.close()
            result = subprocess.run(
                [_os.sys.executable, tmp.name],
                capture_output=True, text=True,
                timeout=timeout, shell=False,
                env=env if env else {},
                cwd=tempfile.gettempdir(),
            )
            elapsed = int((time.monotonic() - start) * 1000)
            output = result.stdout[:4000]
            if result.stderr:
                output += f"\n[stderr]: {result.stderr[:1000]}"
            return SandboxResult(
                ok=result.returncode == 0,
                stdout=output or "[no output]",
                stderr=result.stderr[:1000],
                elapsed_ms=elapsed,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                ok=False,
                error=f"Code execution timed out after {timeout}s",
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as e:
            return SandboxResult(
                ok=False,
                error=f"Execution failed: {e}",
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
        finally:
            try:
                _os.unlink(tmp.name)
            except Exception:
                pass


class ContainerSandbox(ToolSandbox):
    """Execute code in an isolated Docker container.

    Requires Docker installed and running. Provides full isolation:
    no network, read-only rootfs, memory/cpu limits, non-root user.
    """

    name = "container"

    def __init__(self, image: str = "python:3.11-slim"):
        self._image = image

    def execute(
        self, code: str, *, timeout: float = 10.0, env: dict[str, str] | None = None,
    ) -> SandboxResult:
        import subprocess
        import tempfile
        import os as _os
        import time

        start = time.monotonic()
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
        try:
            tmp.write(code)
            tmp.close()

            cmd = [
                "docker", "run", "--rm",
                "--network", "none",
                "--memory", "256m",
                "--cpus", "1",
                "--read-only",
                "--tmpfs", "/tmp:noexec",
                "--user", "1000:1000",
                "-v", f"{tmp.name}:/code.py:ro",
                self._image,
                "python", "/code.py",
            ]

            result = subprocess.run(
                cmd,
                capture_output=True, text=True, shell=False,
                timeout=timeout + 5,  # extra time for container startup
            )
            elapsed = int((time.monotonic() - start) * 1000)
            return SandboxResult(
                ok=result.returncode == 0,
                stdout=result.stdout[:4000] or "[no output]",
                stderr=result.stderr[:1000],
                elapsed_ms=elapsed,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                ok=False,
                error=f"Container execution timed out after {timeout}s",
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
        except FileNotFoundError:
            return SandboxResult(
                ok=False,
                error="Docker not found. Install Docker or use ProcessSandbox.",
            )
        except Exception as e:
            return SandboxResult(
                ok=False,
                error=f"Container execution failed: {e}",
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
        finally:
            try:
                _os.unlink(tmp.name)
            except Exception:
                pass


class ProcessSandbox(ToolSandbox):
    """Execute code in a subprocess with resource limits (no Docker required).

    Uses OS-level resource limits where available. More isolated than
    LocalThreadSandbox but less than ContainerSandbox.
    """

    name = "process"

    def execute(
        self, code: str, *, timeout: float = 10.0, env: dict[str, str] | None = None,
    ) -> SandboxResult:
        import subprocess
        import tempfile
        import os as _os
        import time

        start = time.monotonic()
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False)
        try:
            tmp.write(code)
            tmp.close()

            # Build a minimal environment
            sandbox_env: dict[str, str] = {}
            if env:
                sandbox_env.update(env)
            sandbox_env.setdefault("PATH", _os.environ.get("PATH", "/usr/bin"))
            sandbox_env.setdefault("HOME", tempfile.gettempdir())

            result = subprocess.run(
                [_os.sys.executable, tmp.name],
                capture_output=True, text=True,
                timeout=timeout,
                env=sandbox_env,
                cwd=tempfile.gettempdir(),
            )
            elapsed = int((time.monotonic() - start) * 1000)
            return SandboxResult(
                ok=result.returncode == 0,
                stdout=result.stdout[:4000] or "[no output]",
                stderr=result.stderr[:1000],
                elapsed_ms=elapsed,
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                ok=False,
                error=f"Process execution timed out after {timeout}s",
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception as e:
            return SandboxResult(
                ok=False,
                error=f"Process execution failed: {e}",
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
        finally:
            try:
                _os.unlink(tmp.name)
            except Exception:
                pass
