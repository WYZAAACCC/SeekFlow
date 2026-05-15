"""Tests for ProcessRunner hard-timeout and kill behavior."""
import time

import pytest

from seekflow.tools.runners import InProcessRunner, ProcessRunner, ToolRunResult


def _infinite_loop():
    while True:
        time.sleep(0.01)


def _slow_but_finishes(sleep_s: float = 2.0):
    time.sleep(sleep_s)
    return "done"


def _normal_func(a: int, b: int) -> int:
    return a + b


class TestProcessRunnerTimeout:
    """ProcessRunner must hard-kill timed-out tools."""

    def test_infinite_loop_is_killed(self):
        runner = ProcessRunner()
        result = runner.run(_infinite_loop, {}, timeout_s=0.5)
        assert not result.ok
        assert result.killed
        assert "timed out" in (result.error or "").lower()

    def test_slow_tool_timeout_returns_killed(self):
        runner = ProcessRunner()
        result = runner.run(_slow_but_finishes, {"sleep_s": 10.0}, timeout_s=0.3)
        assert not result.ok
        assert result.killed

    def test_fast_tool_succeeds_within_timeout(self):
        runner = ProcessRunner()
        result = runner.run(_normal_func, {"a": 1, "b": 2}, timeout_s=5.0)
        assert result.ok
        assert result.result == 3
        assert not result.killed
        assert result.runner_name == "process"

    def test_timeout_result_records_elapsed(self):
        runner = ProcessRunner()
        result = runner.run(_infinite_loop, {}, timeout_s=0.3)
        assert result.elapsed_ms > 0


class TestInProcessRunner:
    """InProcessRunner does NOT provide hard timeout."""

    def test_normal_execution(self):
        runner = InProcessRunner()
        result = runner.run(_normal_func, {"a": 3, "b": 4}, timeout_s=30)
        assert result.ok
        assert result.result == 7
        assert result.runner_name == "in_process"

    def test_exception_is_caught(self):
        def _raiser():
            raise ValueError("boom")

        runner = InProcessRunner()
        result = runner.run(_raiser, {}, timeout_s=30)
        assert not result.ok
        assert "boom" in (result.error or "")

    def test_timeout_not_hard_enforced(self):
        """InProcessRunner cannot kill a blocking call — timeout is advisory."""
        runner = InProcessRunner()
        start = time.monotonic()
        result = runner.run(_slow_but_finishes, {"sleep_s": 0.1}, timeout_s=0.01)
        elapsed = time.monotonic() - start
        # Tool completes despite timeout_s being short (no hard kill)
        assert result.ok
        assert result.result == "done"
        # It took about 0.1s, not killed at 0.01s
        assert elapsed > 0.05
