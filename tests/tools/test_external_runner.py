"""Phase C: ExternalToolRunner — containerized execution for third-party tools."""
import json
import subprocess
from unittest import mock

import pytest

from seekflow.tools.external_runner import (
    ExternalToolRunner, _kill_container,
)
from seekflow.tools.manifest import (
    ToolManifest, SandboxManifest, NetworkManifest, FilesystemManifest, EnvManifest,
)
from seekflow.tools.runners import ToolRunResult
from seekflow.types import ToolPolicy
from seekflow.tools.planner import plan_execution, RUNNER_ORDER


VALID_EXTERNAL_MANIFEST = {
    "name": "external-echo",
    "version": "1.0.0",
    "source": "registry",
    "package_digest": "a" * 64,
    "entrypoint": {"command": "python", "args": ["-c", "import sys,json; print(json.dumps(json.load(sys.stdin)))"]},
    "input_schema": {"type": "object", "properties": {"msg": {"type": "string"}}},
    "output_schema": {"type": "object", "properties": {"msg": {"type": "string"}}},
    "sandbox": {"image": "python:3.11-slim", "image_digest": "sha256:" + "b" * 64},
}


def _make_manifest(**overrides) -> ToolManifest:
    data = {**VALID_EXTERNAL_MANIFEST, **overrides}
    return ToolManifest.model_validate(data)


class TestExternalToolRunner:
    """ExternalToolRunner containerized execution."""

    @staticmethod
    def _mock_bounded_read(stdout="", stderr="", timed_out=False, limit_exceeded=False):
        """Mock _bounded_communicate return value."""
        return stdout, stderr, timed_out, limit_exceeded

    def test_runner_name_is_external_container(self):
        runner = ExternalToolRunner()
        assert runner.name == "external_container"

    def test_external_tool_never_calls_python_func(self):
        """ExternalToolRunner takes a manifest, not a callable."""
        runner = ExternalToolRunner()
        manifest = _make_manifest()
        with mock.patch("subprocess.Popen") as mock_popen, \
             mock.patch("seekflow.tools.external_runner._bounded_communicate") as mock_read, \
             mock.patch("seekflow.tools.external_runner._kill_container"):
            mock_proc = mock.MagicMock()
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc
            mock_read.return_value = (json.dumps({"msg": "hello"}), "", False, False)

            result = runner.run(manifest, {"msg": "hello"}, timeout_s=30.0)
            assert result.ok
            assert result.result == {"msg": "hello"}

    def test_timeout_kills_container(self):
        runner = ExternalToolRunner()
        manifest = _make_manifest()
        with mock.patch("subprocess.Popen") as mock_popen, \
             mock.patch("seekflow.tools.external_runner._bounded_communicate") as mock_read, \
             mock.patch("seekflow.tools.external_runner._kill_container") as mock_kill:
            mock_proc = mock.MagicMock()
            mock_popen.return_value = mock_proc
            mock_read.return_value = ("", "", True, False)  # timed_out=True

            result = runner.run(manifest, {"msg": "hi"}, timeout_s=1.0)
            assert not result.ok
            assert result.killed
            assert "timed out" in (result.error or "")
            mock_kill.assert_called()

    def test_non_zero_exit_code_is_error(self):
        runner = ExternalToolRunner()
        manifest = _make_manifest()
        with mock.patch("subprocess.Popen") as mock_popen, \
             mock.patch("seekflow.tools.external_runner._bounded_communicate") as mock_read, \
             mock.patch("seekflow.tools.external_runner._kill_container"):
            mock_proc = mock.MagicMock()
            mock_proc.returncode = 1
            mock_popen.return_value = mock_proc
            mock_read.return_value = ("", "something went wrong", False, False)

            result = runner.run(manifest, {"msg": "hi"}, timeout_s=30.0)
            assert not result.ok
            assert "exited with code 1" in result.error

    def test_no_output_is_error(self):
        runner = ExternalToolRunner()
        manifest = _make_manifest()
        with mock.patch("subprocess.Popen") as mock_popen, \
             mock.patch("seekflow.tools.external_runner._bounded_communicate") as mock_read, \
             mock.patch("seekflow.tools.external_runner._kill_container"):
            mock_proc = mock.MagicMock()
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc
            mock_read.return_value = ("", "", False, False)

            result = runner.run(manifest, {"msg": "hi"}, timeout_s=30.0)
            assert not result.ok
            assert "no output" in (result.error or "")

    def test_invalid_json_output_is_error(self):
        runner = ExternalToolRunner()
        manifest = _make_manifest()
        with mock.patch("subprocess.Popen") as mock_popen, \
             mock.patch("seekflow.tools.external_runner._bounded_communicate") as mock_read, \
             mock.patch("seekflow.tools.external_runner._kill_container"):
            mock_proc = mock.MagicMock()
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc
            mock_read.return_value = ("not json", "", False, False)

            result = runner.run(manifest, {"msg": "hi"}, timeout_s=30.0)
            assert not result.ok
            assert "not valid JSON" in result.error

    def test_output_schema_validation(self):
        """Output that doesn't match output_schema is rejected."""
        runner = ExternalToolRunner()
        manifest = _make_manifest(
            output_schema={
                "type": "object",
                "properties": {"result": {"type": "integer"}},
                "required": ["result"],
            }
        )
        with mock.patch("subprocess.Popen") as mock_popen, \
             mock.patch("seekflow.tools.external_runner._bounded_communicate") as mock_read, \
             mock.patch("seekflow.tools.external_runner._kill_container"):
            mock_proc = mock.MagicMock()
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc
            mock_read.return_value = (json.dumps({"msg": "hello"}), "", False, False)

            result = runner.run(manifest, {"msg": "hi"}, timeout_s=30.0)
            assert not result.ok
            assert "schema" in result.error.lower()

    def test_large_output_is_bounded(self):
        runner = ExternalToolRunner()
        manifest = _make_manifest()
        with mock.patch("subprocess.Popen") as mock_popen, \
             mock.patch("seekflow.tools.external_runner._bounded_communicate") as mock_read, \
             mock.patch("seekflow.tools.external_runner._kill_container"):
            mock_proc = mock.MagicMock()
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc
            mock_read.return_value = ("y" * 200_000, "", False, True)  # limit_exceeded=True

            result = runner.run(manifest, {"msg": "hi"}, timeout_s=30.0, max_output_bytes=10_000)
            assert not result.ok
            assert result.output_truncated

    def test_container_uses_network_none(self):
        """Container default is --network none."""
        runner = ExternalToolRunner()
        manifest = _make_manifest()
        with mock.patch("subprocess.Popen") as mock_popen, \
             mock.patch("seekflow.tools.external_runner._bounded_communicate") as mock_read, \
             mock.patch("seekflow.tools.external_runner._kill_container"):
            mock_proc = mock.MagicMock()
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc
            mock_read.return_value = (json.dumps({"msg": "ok"}), "", False, False)

            runner.run(manifest, {"msg": "ok"}, timeout_s=30.0)
            cmd = mock_popen.call_args[0][0]
            assert "--network" in cmd
            net_idx = cmd.index("--network")
            assert cmd[net_idx + 1] == "none"

    def test_container_uses_digest_pinning(self):
        """When image_digest is set, use digest-based reference."""
        runner = ExternalToolRunner()
        manifest = _make_manifest(
            sandbox={"image": "python:3.11-slim",
                     "image_digest": "sha256:abc123def456"}
        )
        with mock.patch("subprocess.Popen") as mock_popen, \
             mock.patch("seekflow.tools.external_runner._bounded_communicate") as mock_read, \
             mock.patch("seekflow.tools.external_runner._kill_container"):
            mock_proc = mock.MagicMock()
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc
            mock_read.return_value = (json.dumps({"msg": "ok"}), "", False, False)

            runner.run(manifest, {"msg": "ok"}, timeout_s=30.0)
            cmd_str = " ".join(mock_popen.call_args[0][0])
            assert "@sha256:" in cmd_str


class TestExternalToolPlannerIntegration:
    """Planner routes external tools to external_container."""

    def test_external_source_requires_external_container(self):
        from seekflow.types import ToolDefinition
        td = ToolDefinition(
            name="ext", description="", parameters={},
            source="registry", func=None,
            policy=ToolPolicy(risk="read"),
        )
        plan = plan_execution(td, timeout=30.0)
        assert plan.runner == "external_container"

    def test_local_source_still_uses_normal_routing(self):
        from seekflow.types import ToolDefinition
        td = ToolDefinition(
            name="local", description="", parameters={},
            source="local",
            policy=ToolPolicy(risk="read", trusted=True, parallel_safe=True),
        )
        plan = plan_execution(td, timeout=30.0)
        assert plan.runner == "in_process"

    def test_runner_order_external_highest(self):
        assert RUNNER_ORDER["external_container"] > RUNNER_ORDER["container"]
        assert RUNNER_ORDER["external_container"] > RUNNER_ORDER["process"]
        assert RUNNER_ORDER["external_container"] > RUNNER_ORDER["in_process"]

    def test_external_source_cannot_downgrade_to_process(self):
        """Even with explicit runner=process, external tools get upgraded."""
        from seekflow.types import ToolDefinition
        td = ToolDefinition(
            name="ext", description="", parameters={},
            source="registry", func=None,
            policy=ToolPolicy(risk="read", runner="process"),
        )
        plan = plan_execution(td, timeout=30.0)
        assert plan.runner == "external_container"
