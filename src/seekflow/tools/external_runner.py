"""ExternalToolRunner — containerized execution for third-party tools.

Lv3 core component: third-party tools NEVER enter the host Python process.
Instead, they run in isolated containers with:
- JSON protocol (stdin input, stdout result)
- No host env, no host network (--network none)
- Fresh container per execution
- Timeout → kill + rm (zombie prevention)
- Output bounded + JSON validated before model sees it
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import time as _time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from seekflow.tools.manifest import ToolManifest, SandboxManifest
from seekflow.tools.runners import ToolRunResult


@dataclass(frozen=True)
class EgressProfile:
    """Network egress policy for external tool execution (Phase E placeholder)."""
    allowed_domains: set[str] = frozenset()
    allowed_ports: set[int] = frozenset({443})
    block_private_ips: bool = True


@dataclass(frozen=True)
class FSProfile:
    """Filesystem profile for external tool execution."""
    read_only: bool = True
    workspace_mount: str | None = None


@dataclass(frozen=True)
class EnvProfile:
    """Environment profile for external tool execution."""
    allowlist: dict[str, str] = frozenset()


class ExternalToolRunner:
    """Runs third-party tools in isolated Docker containers.

    The tool is defined by a ToolManifest, not a Python callable.
    Input comes as JSON on stdin. Output is read as JSON from stdout.
    Stderr is captured for audit but never reaches the model.
    """

    name = "external_container"

    def run(
        self,
        manifest: ToolManifest,
        arguments: dict,
        timeout_s: float,
        *,
        max_output_bytes: int = 100_000,
        egress_profile: EgressProfile | None = None,
        fs_profile: FSProfile | None = None,
        env_profile: dict[str, str] | None = None,
    ) -> ToolRunResult:
        """Execute an external tool in an isolated container.

        Args:
            manifest: The tool's manifest (identity, entrypoint, sandbox, schemas).
            arguments: Tool arguments (serialized to JSON for stdin).
            timeout_s: Hard timeout in seconds.
            max_output_bytes: Maximum stdout bytes before truncation.
            egress_profile: Network policy (Phase E).
            fs_profile: Filesystem mounts.
            env_profile: Environment allowlist.

        Returns:
            ToolRunResult with ok, result (parsed JSON), error, elapsed_ms.
        """
        start = _time.monotonic()
        sandbox = manifest.sandbox
        container_name = f"seekflow-ext-{uuid.uuid4().hex[:12]}"
        tmp_input = None

        try:
            # ── Write input JSON ───────────────────────────────────
            tmp_input = tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, prefix="seekflow_input_"
            )
            json.dump(arguments, tmp_input, ensure_ascii=False)
            tmp_input.close()

            # ── Build container command ────────────────────────────
            # Lv3: non-local tools MUST have a pinned image digest
            if manifest.source != "local":
                if not sandbox.image_digest:
                    return ToolRunResult(
                        ok=False,
                        error="External tools require sandbox.image_digest pinned by sha256",
                        runner_name=self.name,
                    )
                if not sandbox.image_digest.startswith("sha256:"):
                    return ToolRunResult(
                        ok=False,
                        error="image_digest must start with 'sha256:'",
                        runner_name=self.name,
                    )

            if sandbox.image_digest:
                base_image = (sandbox.image or "python:3.11-slim").split(":")[0]
                image_ref = f"{base_image}@{sandbox.image_digest}"
            else:
                image_ref = sandbox.image or "python:3.11-slim"

            # Lv3: external tools default to --network none unless egress sidecar configured
            network_mode = "none"
            if manifest.network.allowed_domains:
                # Network access requires egress sidecar (Phase 5)
                # For now, block — sidecar must be explicitly started
                network_mode = "none"

            cmd = [
                "docker", "run",
                "--name", container_name,
                "--network", network_mode,
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--pids-limit", str(sandbox.pids_limit),
                "--memory", f"{sandbox.memory_mb}m",
                "--cpus", str(sandbox.cpu_count),
                "--user", "65534:65534",
                "--tmpfs", f"/tmp:rw,noexec,nosuid,nodev,size={sandbox.tmpfs_size_mb}m",
                "-v", f"{tmp_input.name}:/seekflow/input.json:ro",
            ]

            if sandbox.read_only_rootfs:
                cmd.append("--read-only")

            # Inject secrets from env_profile (SecretBroker) — only declared secrets
            if env_profile:
                for key, value in env_profile.items():
                    cmd.extend(["-e", f"{key}={value}"])

            # Entrypoint: the tool's entrypoint command
            entrypoint_cmd = manifest.entrypoint.get("command", "python")
            entrypoint_args = manifest.entrypoint.get("args", ["/tool/main.py"])
            cmd.append(image_ref)
            cmd.append(entrypoint_cmd)
            cmd.extend(entrypoint_args)

            # ── Execute with bounded stream read ───────────────────
            # Lv3: do NOT use proc.communicate() — that buffers unbounded output
            # in parent memory first. Instead, read chunks with a hard limit.
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            try:
                stdout_str, stderr_str, timed_out, limit_exceeded = _bounded_communicate(
                    proc, timeout_s + 10, max_output_bytes + 4096, 64_000,
                )
            except Exception:
                _kill_container(container_name)
                proc.kill()
                elapsed = int((_time.monotonic() - start) * 1000)
                return ToolRunResult(
                    ok=False,
                    error=f"External tool I/O error",
                    runner_name=self.name,
                    elapsed_ms=elapsed,
                )

            if timed_out:
                _kill_container(container_name)
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                elapsed = int((_time.monotonic() - start) * 1000)
                return ToolRunResult(
                    ok=False,
                    error=f"External tool timed out after {timeout_s}s",
                    killed=True,
                    runner_name=self.name,
                    elapsed_ms=elapsed,
                    exit_code=proc.returncode,
                )

            if limit_exceeded:
                _kill_container(container_name)
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                elapsed = int((_time.monotonic() - start) * 1000)
                return ToolRunResult(
                    ok=False,
                    error=f"External tool stdout exceeded max_output_bytes ({max_output_bytes})",
                    killed=True,
                    runner_name=self.name,
                    elapsed_ms=elapsed,
                    exit_code=proc.returncode,
                    output_truncated=True,
                )

            elapsed = int((_time.monotonic() - start) * 1000)

            # ── Check exit code ────────────────────────────────────
            if proc.returncode != 0:
                _kill_container(container_name)
                return ToolRunResult(
                    ok=False,
                    error=f"External tool exited with code {proc.returncode}: "
                          f"{stderr_str[:500] if stderr_str else 'no stderr'}",
                    runner_name=self.name,
                    elapsed_ms=elapsed,
                    exit_code=proc.returncode,
                )

            # ── Parse stdout as JSON ───────────────────────────────
            # stdout_str is already set by _bounded_communicate above
            stdout_str = (stdout_str or "").strip()
            if not stdout_str:
                _kill_container(container_name)
                return ToolRunResult(
                    ok=False,
                    error="External tool produced no output",
                    runner_name=self.name,
                    elapsed_ms=elapsed,
                    exit_code=proc.returncode,
                )

            # Bound output before parse
            from seekflow.tools.limits import serialize_bounded
            bounded_stdout, truncated = serialize_bounded(stdout_str, max_output_bytes)

            try:
                result = json.loads(bounded_stdout)
            except json.JSONDecodeError as e:
                _kill_container(container_name)
                return ToolRunResult(
                    ok=False,
                    error=f"External tool output is not valid JSON: {e}",
                    runner_name=self.name,
                    elapsed_ms=elapsed,
                    exit_code=proc.returncode,
                    output_truncated=truncated,
                )

            # ── Validate output schema if present ──────────────────
            if manifest.output_schema:
                from seekflow.tools.validation import validate_tool_arguments
                issues = validate_tool_arguments(manifest.output_schema, result)
                if issues:
                    _kill_container(container_name)
                    joined = "; ".join(f"{i.path}: {i.message}" for i in issues[:3])
                    return ToolRunResult(
                        ok=False,
                        error=f"Output schema validation failed: {joined}",
                        runner_name=self.name,
                        elapsed_ms=elapsed,
                        exit_code=proc.returncode,
                    )

            # ── Cleanup and return ──────────────────────────────────
            _kill_container(container_name)

            return ToolRunResult(
                ok=True,
                result=result,
                runner_name=self.name,
                elapsed_ms=elapsed,
                exit_code=proc.returncode,
                output_truncated=truncated,
            )

        except FileNotFoundError:
            return ToolRunResult(
                ok=False,
                error="Docker not found — cannot run external tool",
                runner_name=self.name,
            )
        except Exception as e:
            _kill_container(container_name)
            return ToolRunResult(
                ok=False,
                error=f"External tool execution failed: {e}",
                runner_name=self.name,
                elapsed_ms=int((_time.monotonic() - start) * 1000),
            )
        finally:
            # Always cleanup container and temp file
            _kill_container(container_name)
            if tmp_input is not None:
                try:
                    Path(tmp_input.name).unlink(missing_ok=True)
                except Exception:
                    pass


def _bounded_communicate(
    proc: "subprocess.Popen",
    timeout_s: float,
    max_stdout: int,
    max_stderr: int,
) -> tuple[str, str, bool, bool]:
    """Read stdout/stderr from a subprocess with hard byte limits.

    Returns (stdout_str, stderr_str, timed_out, limit_exceeded).
    Uses selectors for non-blocking chunked reads.
    """
    import selectors

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    stdout_bytes = 0
    stderr_bytes = 0
    deadline = _time.monotonic() + timeout_s
    timed_out = False
    limit_exceeded = False

    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ, "stdout")
    sel.register(proc.stderr, selectors.EVENT_READ, "stderr")

    try:
        while proc.poll() is None:
            if _time.monotonic() > deadline:
                timed_out = True
                break

            events = sel.select(timeout=0.1)
            for key, _ in events:
                chunk = key.fileobj.read(4096)
                if not chunk:
                    sel.unregister(key.fileobj)
                    continue
                if key.data == "stdout":
                    stdout_bytes += len(chunk.encode("utf-8", errors="replace"))
                    if stdout_bytes > max_stdout:
                        limit_exceeded = True
                        break
                    stdout_chunks.append(chunk)
                else:
                    stderr_bytes += len(chunk.encode("utf-8", errors="replace"))
                    if stderr_bytes > max_stderr:
                        limit_exceeded = True
                        break
                    stderr_chunks.append(chunk)

            if limit_exceeded:
                break

        if not timed_out and not limit_exceeded:
            remaining = proc.stdout.read()
            if remaining:
                stdout_chunks.append(remaining)
            remaining = proc.stderr.read()
            if remaining:
                stderr_chunks.append(remaining)
    finally:
        sel.close()

    return "".join(stdout_chunks), "".join(stderr_chunks), timed_out, limit_exceeded


def _kill_container(container_name: str) -> None:
    """Kill and remove a container, ignoring errors."""
    try:
        subprocess.run(
            ["docker", "kill", container_name],
            timeout=5, capture_output=True,
        )
    except Exception:
        pass
    try:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            timeout=5, capture_output=True,
        )
    except Exception:
        pass
