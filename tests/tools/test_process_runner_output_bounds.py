"""PR-3: ProcessRunner bounds all output types, not just strings."""
import pytest

from seekflow.tools.runners import ProcessRunner


def _large_dict():
    """Return a dict with a large string value (built at runtime)."""
    return {"data": "x" * 30_000}


def _small_dict():
    return {"a": 1, "b": 2}


def _large_list():
    """Return a list of many items (built at runtime)."""
    return ["item_%d" % i for i in range(20_000)]


def _large_str():
    """Return a large string (built at runtime to avoid constant-fold)."""
    size = 50_000
    return "y" * size


def _small_str():
    return "hello"


class TestProcessRunnerOutputBounds:
    """ProcessRunner must bound large outputs of all types in the child process."""

    def test_large_dict_output_bounded_in_child(self):
        runner = ProcessRunner()
        result = runner.run(_large_dict, {}, timeout_s=60.0, max_output_bytes=5_000)
        assert result.ok
        assert result.output_truncated
        assert len(str(result.result)) <= 5_000 + 100

    def test_small_dict_output_preserved(self):
        runner = ProcessRunner()
        result = runner.run(_small_dict, {}, timeout_s=60.0, max_output_bytes=100_000)
        assert result.ok
        assert not result.output_truncated
        assert result.result == {"a": 1, "b": 2}

    def test_large_list_output_bounded(self):
        runner = ProcessRunner()
        result = runner.run(_large_list, {}, timeout_s=60.0, max_output_bytes=5_000)
        assert result.ok
        assert result.output_truncated

    def test_large_string_output_bounded(self):
        runner = ProcessRunner()
        result = runner.run(_large_str, {}, timeout_s=60.0, max_output_bytes=5_000)
        assert result.ok
        assert result.output_truncated
        assert len(str(result.result)) <= 5_000 + 100

    def test_small_result_no_truncation(self):
        runner = ProcessRunner()
        result = runner.run(_small_str, {}, timeout_s=60.0, max_output_bytes=100_000)
        assert result.ok
        assert not result.output_truncated
        assert result.result == "hello"
