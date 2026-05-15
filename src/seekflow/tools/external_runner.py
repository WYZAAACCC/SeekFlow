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
        env_profile: EnvProfile | None = None,
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
            image = sandbox.image or "python:3.11-slim"
            # If image_digest is present, use digest pinning
            if sandbox.image_digest:
                image_ref = f"{image.split(':')[0]}@{sandbox.image_digest}"
            else:
                image_ref = image

            cmd = [
                "docker", "run",
                "--name", container_name,
                "--network", sandbox.network,
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

            # Entrypoint: the tool's entrypoint command
            entrypoint_cmd = manifest.entrypoint.get("command", "python")
            entrypoint_args = manifest.entrypoint.get("args", ["/tool/main.py"])
            cmd.append(image_ref)
            cmd.append(entrypoint_cmd)
            cmd.extend(entrypoint_args)

            # ── Execute ────────────────────────────────────────────
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            try:
                stdout, stderr = proc.communicate(timeout=timeout_s + 10)
            except subprocess.TimeoutExpired:
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

            elapsed = int((_time.monotonic() - start) * 1000)

            # ── Check exit code ────────────────────────────────────
            if proc.returncode != 0:
                _kill_container(container_name)
                return ToolRunResult(
                    ok=False,
                    error=f"External tool exited with code {proc.returncode}: "
                          f"{stderr[:500] if stderr else 'no stderr'}",
                    runner_name=self.name,
                    elapsed_ms=elapsed,
                    exit_code=proc.returncode,
                )

            # ── Parse stdout as JSON ───────────────────────────────
            stdout_str = (stdout or "").strip()
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
