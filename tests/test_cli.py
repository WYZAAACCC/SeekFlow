"""Tests for deepseek_toolkit.cli."""
from unittest import mock

from typer.testing import CliRunner

from deepseek_toolkit.cli import app

runner = CliRunner()


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "DeepSeek Toolkit" in result.stdout or "deepseek" in result.stdout.lower()


def test_cli_no_args_shows_help():
    result = runner.invoke(app, [])
    # exit code 2 is standard for click/typer when --help is shown by default
    assert result.exit_code in (0, 2)


def test_eval_subcommand_help():
    result = runner.invoke(app, ["eval", "--help"])
    assert result.exit_code == 0
    assert "benchmark" in result.stdout.lower() or "eval" in result.stdout.lower()


def test_eval_run_help():
    result = runner.invoke(app, ["eval", "run", "--help"])
    assert result.exit_code == 0


def test_eval_run_help_shows_batch_options():
    """--batch, --batch-poll-interval, --batch-max-wait appear in help."""
    result = runner.invoke(app, ["eval", "run", "--help"])
    assert result.exit_code == 0
    assert "--batch" in result.stdout
    assert "--batch-poll-interval" in result.stdout
    assert "--batch-max-wait" in result.stdout


def test_trace_subcommand_help():
    result = runner.invoke(app, ["trace", "--help"])
    assert result.exit_code == 0


def test_trace_view_help():
    result = runner.invoke(app, ["trace", "view", "--help"])
    assert result.exit_code == 0


class TestEvalRunBatch:
    """Tests for dstk eval run --batch."""

    def test_non_batch_mode_calls_chat(self):
        """Without --batch, runtime.chat() is used per case (unchanged behavior)."""
        import tempfile
        from pathlib import Path

        yaml_content = (
            "name: simple_test\n"
            "model: deepseek-chat\n"
            "cases:\n"
            "  - id: c1\n"
            '    input: "hello"\n'
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            bench_path = Path(tmpdir) / "test.yaml"
            bench_path.write_text(yaml_content)

            with mock.patch("deepseek_toolkit.runtime.ToolRuntime") as MockRuntime:
                mock_rt = mock.MagicMock()
                mock_rt.chat.return_value = mock.MagicMock(
                    final="hello back",
                    messages=[],
                    tool_results=[],
                    usage=None,
                    trace=None,
                    circuit_breaker_open=False,
                    cache_stats=None,
                    reasoning_contents=[],
                )
                MockRuntime.return_value = mock_rt

                result = runner.invoke(app, [
                    "eval", "run", str(bench_path),
                    "--api-key", "sk-fake",
                ])

            assert result.exit_code == 0
            # chat() was called (not chat_batch)
            assert mock_rt.chat.called
            assert not mock_rt.chat_batch.called

    def test_batch_mode_calls_chat_batch(self):
        """With --batch, runtime.chat_batch() is used."""
        import tempfile
        from pathlib import Path

        yaml_content = (
            "name: batch_test\n"
            "model: deepseek-chat\n"
            "cases:\n"
            "  - id: c1\n"
            '    input: "hello"\n'
            "  - id: c2\n"
            '    input: "world"\n'
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            bench_path = Path(tmpdir) / "test.yaml"
            bench_path.write_text(yaml_content)

            with mock.patch("deepseek_toolkit.runtime.ToolRuntime") as MockRuntime:
                mock_rt = mock.MagicMock()
                mock_rt.chat_batch.return_value = [
                    mock.MagicMock(
                        final="hello back",
                        messages=[],
                        tool_results=[],
                        usage=None,
                        trace=None,
                        circuit_breaker_open=False,
                        cache_stats=None,
                        reasoning_contents=[],
                    ),
                    mock.MagicMock(
                        final="world back",
                        messages=[],
                        tool_results=[],
                        usage=None,
                        trace=None,
                        circuit_breaker_open=False,
                        cache_stats=None,
                        reasoning_contents=[],
                    ),
                ]
                MockRuntime.return_value = mock_rt

                result = runner.invoke(app, [
                    "eval", "run", str(bench_path),
                    "--api-key", "sk-fake",
                    "--batch",
                ])

            assert result.exit_code == 0
            assert mock_rt.chat_batch.called
            assert not mock_rt.chat.called

    def test_batch_mode_passes_poll_interval(self):
        """--batch-poll-interval is passed to chat_batch()."""
        import tempfile
        from pathlib import Path

        yaml_content = (
            "name: batch_test\n"
            "model: deepseek-chat\n"
            "cases:\n"
            "  - id: c1\n"
            '    input: "hello"\n'
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            bench_path = Path(tmpdir) / "test.yaml"
            bench_path.write_text(yaml_content)

            with mock.patch("deepseek_toolkit.runtime.ToolRuntime") as MockRuntime:
                mock_rt = mock.MagicMock()
                mock_rt.chat_batch.return_value = [
                    mock.MagicMock(
                        final="ok", messages=[], tool_results=[],
                        usage=None, trace=None, circuit_breaker_open=False,
                        cache_stats=None, reasoning_contents=[],
                    ),
                ]
                MockRuntime.return_value = mock_rt

                result = runner.invoke(app, [
                    "eval", "run", str(bench_path),
                    "--api-key", "sk-fake",
                    "--batch",
                    "--batch-poll-interval", "10",
                    "--batch-max-wait", "600",
                ])

            assert result.exit_code == 0
            call_kwargs = mock_rt.chat_batch.call_args
            assert call_kwargs.kwargs["poll_interval"] == 10.0
            assert call_kwargs.kwargs["max_wait"] == 600.0
