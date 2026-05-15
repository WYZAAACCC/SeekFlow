"""PR-8: ContainerSandbox timeout performs explicit docker kill/rm cleanup."""
import subprocess
from unittest import mock

import pytest

from seekflow.sandbox import ContainerSandbox, SandboxResult


class TestContainerSandboxCleanup:
    """ContainerSandbox must cleanup containers on timeout and normal exit."""

    def test_sandbox_result_has_killed_and_container_name_fields(self):
        """SandboxResult has killed and container_name fields."""
        result = SandboxResult(ok=True, killed=False, container_name="test-container")
        assert result.killed is False
        assert result.container_name == "test-container"

    def test_container_sandbox_generates_unique_name(self):
        """Each sandbox execution generates a unique container name."""
        sandbox = ContainerSandbox()
        with mock.patch("subprocess.Popen") as mock_popen, \
             mock.patch("subprocess.run") as mock_run:
            mock_proc = mock.MagicMock()
            mock_proc.communicate.return_value = ("output", "")
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc

            result = sandbox.execute("print('hello')", timeout=5.0)
            assert result.container_name is not None
            assert result.container_name.startswith("seekflow-sandbox-")
            assert len(result.container_name) > len("seekflow-sandbox-")

    def test_container_timeout_kills_and_removes(self):
        """Timeout triggers docker kill + docker rm -f."""
        sandbox = ContainerSandbox()
        with mock.patch("subprocess.Popen") as mock_popen:
            mock_proc = mock.MagicMock()
            mock_proc.communicate.side_effect = subprocess.TimeoutExpired("cmd", 10)
            mock_popen.return_value = mock_proc

            with mock.patch("subprocess.run") as mock_run:
                result = sandbox.execute("while True: pass", timeout=1.0)

                assert not result.ok
                assert result.killed
                assert "timed out" in (result.error or "")

                # Verify docker kill was called
                kill_calls = [c for c in mock_run.call_args_list
                              if "docker" in str(c) and "kill" in str(c)]
                rm_calls = [c for c in mock_run.call_args_list
                            if "docker" in str(c) and "rm" in str(c)]
                assert len(kill_calls) >= 1, "docker kill should be called on timeout"
                assert len(rm_calls) >= 1, "docker rm should be called on timeout"

    def test_container_cleanup_called_on_normal_exit(self):
        """Normal execution still cleans up via docker rm -f in finally."""
        sandbox = ContainerSandbox()
        with mock.patch("subprocess.Popen") as mock_popen:
            mock_proc = mock.MagicMock()
            mock_proc.communicate.return_value = ("output", "")
            mock_proc.returncode = 0
            mock_popen.return_value = mock_proc

            with mock.patch("subprocess.run") as mock_run:
                result = sandbox.execute("print('hello')", timeout=5.0)

                assert result.ok
                # Finally block always calls docker rm -f
                rm_calls = [c for c in mock_run.call_args_list
                            if "docker" in str(c) and "rm" in str(c)]
                assert len(rm_calls) >= 1, "docker rm should be called in finally"

    def test_container_name_in_timeout_result(self):
        """Timeout result includes container_name."""
        sandbox = ContainerSandbox()
        with mock.patch("subprocess.Popen") as mock_popen:
            mock_proc = mock.MagicMock()
            mock_proc.communicate.side_effect = subprocess.TimeoutExpired("cmd", 10)
            mock_popen.return_value = mock_proc

            with mock.patch("subprocess.run"):
                result = sandbox.execute("while True: pass", timeout=1.0)
                assert result.container_name is not None
                assert result.container_name.startswith("seekflow-sandbox-")
