"""Tests for eval framework: loader, runner, metrics, report."""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from seekflow.eval.types import EvalCase, EvalReport, ExpectedToolCall
from seekflow.types import ToolExecutionResult, ToolRuntimeResult


class TestEvalTypes:
    def test_expected_tool_call(self):
        etc = ExpectedToolCall(name="add", arguments={"a": 1, "b": 2})
        assert etc.name == "add"
        assert etc.arguments == {"a": 1, "b": 2}

    def test_expected_tool_call_default_arguments(self):
        etc = ExpectedToolCall(name="ping")
        assert etc.arguments == {}

    def test_eval_case(self):
        case = EvalCase(
            id="test_001",
            input="What is 1+2?",
            expected_tools=[ExpectedToolCall(name="add", arguments={"a": 1, "b": 2})],
            expected_final_contains=["3"],
        )
        assert case.id == "test_001"
        assert len(case.expected_tools) == 1
        assert case.expected_final_contains == ["3"]

    def test_eval_case_defaults(self):
        case = EvalCase(id="minimal", input="Hello")
        assert case.expected_tools == []
        assert case.expected_final_contains == []

    def test_eval_report(self):
        report = EvalReport(
            name="basic",
            model="deepseek-chat",
            metrics={"total_cases": 5, "passed_cases": 4, "success_rate": 80.0},
            case_results=[],
        )
        assert report.name == "basic"
        assert report.metrics["success_rate"] == 80.0


class TestEvalLoader:
    def test_load_yaml_benchmark(self):
        """Load a YAML benchmark file and parse cases."""
        yaml_content = (
            "name: basic_tool_calling\n"
            "model: deepseek-chat\n"
            "\n"
            "cases:\n"
            "  - id: weather_001\n"
            '    input: "What is the weather in Hangzhou?"\n'
            "    expected_tools:\n"
            "      - name: get_weather\n"
            "        arguments:\n"
            '          city: "Hangzhou"\n'
            "    expected_final_contains:\n"
            '      - "Hangzhou"\n'
            "\n"
            "  - id: math_001\n"
            '    input: "What is 1+2?"\n'
            "    expected_tools:\n"
            "      - name: add\n"
            "        arguments:\n"
            "          a: 1\n"
            "          b: 2\n"
            "    expected_final_contains:\n"
            '      - "3"\n'
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bench.yaml"
            path.write_text(yaml_content)

            from seekflow.eval.loader import load_benchmark
            name, model, cases = load_benchmark(str(path))

        assert name == "basic_tool_calling"
        assert model == "deepseek-chat"
        assert len(cases) == 2
        assert cases[0].id == "weather_001"
        assert cases[0].input == "What is the weather in Hangzhou?"
        assert cases[0].expected_tools[0].name == "get_weather"
        assert cases[0].expected_tools[0].arguments == {"city": "Hangzhou"}
        assert cases[0].expected_final_contains == ["Hangzhou"]
        assert cases[1].expected_tools[0].arguments == {"a": 1, "b": 2}

    def test_load_yaml_without_tools(self):
        """YAML cases may have no expected_tools."""
        yaml_content = """
name: chat_only
model: deepseek-chat

cases:
  - id: hello_001
    input: "Say hello"
    expected_final_contains:
      - "hello"
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "chat.yaml"
            path.write_text(yaml_content)

            from seekflow.eval.loader import load_benchmark
            name, model, cases = load_benchmark(str(path))

        assert len(cases) == 1
        assert cases[0].expected_tools == []


class TestEvalMetrics:
    def test_calculate_metrics_all_pass(self):
        from seekflow.eval.metrics import calculate_metrics

        case_results = [
            {
                "case_id": "c1",
                "passed": True,
                "tool_name_match": True,
                "argument_match": True,
                "final_contains_match": True,
                "steps": 2,
                "latency_ms": 1000,
            },
            {
                "case_id": "c2",
                "passed": True,
                "tool_name_match": True,
                "argument_match": True,
                "final_contains_match": True,
                "steps": 3,
                "latency_ms": 1500,
            },
        ]

        metrics = calculate_metrics(case_results)
        assert metrics["total_cases"] == 2
        assert metrics["passed_cases"] == 2
        assert metrics["failed_cases"] == 0
        assert metrics["success_rate"] == 100.0
        assert metrics["tool_name_accuracy"] == 100.0
        assert metrics["argument_accuracy"] == 100.0
        assert metrics["final_contains_accuracy"] == 100.0
        assert metrics["avg_steps"] == 2.5
        assert metrics["avg_latency_ms"] == 1250.0

    def test_calculate_metrics_mixed(self):
        from seekflow.eval.metrics import calculate_metrics

        case_results = [
            {
                "case_id": "c1",
                "passed": True,
                "tool_name_match": True,
                "argument_match": True,
                "final_contains_match": True,
                "steps": 1,
                "latency_ms": 500,
            },
            {
                "case_id": "c2",
                "passed": False,
                "tool_name_match": False,
                "argument_match": False,
                "final_contains_match": True,
                "steps": 2,
                "latency_ms": 800,
            },
        ]

        metrics = calculate_metrics(case_results)
        assert metrics["total_cases"] == 2
        assert metrics["passed_cases"] == 1
        assert metrics["failed_cases"] == 1
        assert metrics["success_rate"] == 50.0
        assert metrics["tool_name_accuracy"] == 50.0
        assert metrics["argument_accuracy"] == 50.0
        assert metrics["final_contains_accuracy"] == 100.0

    def test_calculate_metrics_empty(self):
        from seekflow.eval.metrics import calculate_metrics

        metrics = calculate_metrics([])
        assert metrics["total_cases"] == 0
        assert metrics["success_rate"] == 0.0


class TestEvalRunner:
    @pytest.fixture
    def mock_runtime(self):
        """Mock ToolRuntime to return preset results."""
        runtime = MagicMock()

        def make_result(final_text, tool_name, tool_args, tool_result, steps=2):
            return ToolRuntimeResult(
                final=final_text,
                messages=[],
                tool_results=[
                    ToolExecutionResult(
                        tool_call_id="call_1",
                        name=tool_name,
                        arguments=tool_args,
                        ok=True,
                        result=tool_result,
                        elapsed_ms=500,
                    ),
                ],
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

        runtime.chat = MagicMock(side_effect=[
            make_result("杭州天气晴朗", "get_weather", {"city": "杭州"}, {"temp": 25}),
            make_result("1+2=3", "add", {"a": 1, "b": 2}, 3),
        ])
        return runtime

    def test_run_cases(self, mock_runtime):
        from seekflow.eval.runner import EvalRunner

        cases = [
            EvalCase(
                id="weather_001",
                input="查询杭州天气",
                expected_tools=[ExpectedToolCall(name="get_weather", arguments={"city": "杭州"})],
                expected_final_contains=["杭州"],
            ),
            EvalCase(
                id="math_001",
                input="1+2等于多少",
                expected_tools=[ExpectedToolCall(name="add", arguments={"a": 1, "b": 2})],
                expected_final_contains=["3"],
            ),
        ]

        runner = EvalRunner(mock_runtime, model="deepseek-chat")
        report = runner.run_cases(cases)

        assert isinstance(report, EvalReport)
        assert report.name == "eval"
        assert report.model == "deepseek-chat"
        assert len(report.case_results) == 2
        assert report.case_results[0]["passed"] is True
        assert report.case_results[1]["passed"] is True
        assert report.metrics["success_rate"] == 100.0
        assert report.metrics["tool_name_accuracy"] == 100.0

    def test_run_cases_with_failure(self, mock_runtime):
        """When final text doesn't contain expected text, case fails."""
        from seekflow.eval.runner import EvalRunner

        # Override the runtime to return a non-matching final
        mock_runtime.chat = MagicMock(return_value=ToolRuntimeResult(
            final="Sorry, I cannot help",
            messages=[],
            tool_results=[],
        ))

        cases = [
            EvalCase(
                id="fail_001",
                input="查询杭州天气",
                expected_final_contains=["杭州"],
            ),
        ]

        runner = EvalRunner(mock_runtime, model="deepseek-chat")
        report = runner.run_cases(cases)

        assert report.case_results[0]["passed"] is False
        assert report.case_results[0]["final_contains_match"] is False
        assert report.metrics["success_rate"] == 0.0

    def test_run_cases_tool_name_mismatch(self, mock_runtime):
        from seekflow.eval.runner import EvalRunner

        mock_runtime.chat = MagicMock(return_value=ToolRuntimeResult(
            final="Done",
            messages=[],
            tool_results=[
                ToolExecutionResult(
                    tool_call_id="call_1",
                    name="wrong_tool",
                    arguments={},
                    ok=True,
                    result=None,
                    elapsed_ms=100,
                ),
            ],
        ))

        cases = [
            EvalCase(
                id="t1",
                input="Do something",
                expected_tools=[ExpectedToolCall(name="right_tool", arguments={})],
            ),
        ]

        runner = EvalRunner(mock_runtime, model="deepseek-chat")
        report = runner.run_cases(cases)

        assert report.case_results[0]["tool_name_match"] is False
        assert report.metrics["tool_name_accuracy"] == 0.0

    def test_run_cases_batch_uses_chat_batch(self, mock_runtime):
        """run_cases_batch() calls runtime.chat_batch() with correct requests."""
        from seekflow.eval.runner import EvalRunner

        mock_runtime.chat_batch = MagicMock(return_value=[
            ToolRuntimeResult(
                final="杭州天气晴朗",
                messages=[],
                tool_results=[
                    ToolExecutionResult(
                        tool_call_id="call_1", name="get_weather",
                        arguments={"city": "杭州"}, ok=True, result={"temp": 25},
                        elapsed_ms=500,
                    ),
                ],
            ),
            ToolRuntimeResult(
                final="1+2=3",
                messages=[],
                tool_results=[
                    ToolExecutionResult(
                        tool_call_id="call_1", name="add",
                        arguments={"a": 1, "b": 2}, ok=True, result=3,
                        elapsed_ms=300,
                    ),
                ],
            ),
        ])

        cases = [
            EvalCase(
                id="weather_001",
                input="查询杭州天气",
                expected_tools=[ExpectedToolCall(name="get_weather", arguments={"city": "杭州"})],
                expected_final_contains=["杭州"],
            ),
            EvalCase(
                id="math_001",
                input="1+2等于多少",
                expected_tools=[ExpectedToolCall(name="add", arguments={"a": 1, "b": 2})],
                expected_final_contains=["3"],
            ),
        ]

        runner = EvalRunner(mock_runtime, model="deepseek-chat")
        report = runner.run_cases_batch(cases)

        assert mock_runtime.chat_batch.called
        call_kwargs = mock_runtime.chat_batch.call_args.kwargs
        assert call_kwargs["model"] == "deepseek-chat"
        assert len(call_kwargs["requests"]) == 2
        assert call_kwargs["requests"][0]["messages"][0]["content"] == "查询杭州天气"

    def test_run_cases_batch_all_pass(self, mock_runtime):
        """run_cases_batch() evaluates all cases correctly."""
        from seekflow.eval.runner import EvalRunner

        mock_runtime.chat_batch = MagicMock(return_value=[
            ToolRuntimeResult(
                final="杭州天气晴朗",
                messages=[],
                tool_results=[
                    ToolExecutionResult(
                        tool_call_id="call_1", name="get_weather",
                        arguments={"city": "杭州"}, ok=True, result={"temp": 25},
                        elapsed_ms=500,
                    ),
                ],
            ),
            ToolRuntimeResult(
                final="1+2=3",
                messages=[],
                tool_results=[
                    ToolExecutionResult(
                        tool_call_id="call_1", name="add",
                        arguments={"a": 1, "b": 2}, ok=True, result=3,
                        elapsed_ms=300,
                    ),
                ],
            ),
        ])

        cases = [
            EvalCase(
                id="weather_001",
                input="查询杭州天气",
                expected_tools=[ExpectedToolCall(name="get_weather", arguments={"city": "杭州"})],
                expected_final_contains=["杭州"],
            ),
            EvalCase(
                id="math_001",
                input="1+2等于多少",
                expected_tools=[ExpectedToolCall(name="add", arguments={"a": 1, "b": 2})],
                expected_final_contains=["3"],
            ),
        ]

        runner = EvalRunner(mock_runtime, model="deepseek-chat")
        report = runner.run_cases_batch(cases)

        assert isinstance(report, EvalReport)
        assert report.name == "eval-batch"
        assert report.model == "deepseek-chat"
        assert len(report.case_results) == 2
        assert report.case_results[0]["passed"] is True
        assert report.case_results[1]["passed"] is True
        assert report.metrics["success_rate"] == 100.0

    def test_run_cases_batch_with_failure(self, mock_runtime):
        """run_cases_batch() handles failed cases."""
        from seekflow.eval.runner import EvalRunner

        mock_runtime.chat_batch = MagicMock(return_value=[
            ToolRuntimeResult(
                final="Sorry, I cannot help",
                messages=[],
                tool_results=[],
            ),
        ])

        cases = [
            EvalCase(
                id="fail_001",
                input="查询杭州天气",
                expected_final_contains=["杭州"],
            ),
        ]

        runner = EvalRunner(mock_runtime, model="deepseek-chat")
        report = runner.run_cases_batch(cases)

        assert report.case_results[0]["passed"] is False
        assert report.case_results[0]["final_contains_match"] is False
        assert report.metrics["success_rate"] == 0.0

    def test_run_cases_batch_empty(self, mock_runtime):
        """run_cases_batch() handles empty case list."""
        from seekflow.eval.runner import EvalRunner

        mock_runtime.chat_batch = MagicMock(return_value=[])

        runner = EvalRunner(mock_runtime, model="deepseek-chat")
        report = runner.run_cases_batch([])

        assert report.metrics["total_cases"] == 0
        assert report.metrics["success_rate"] == 0.0

    def test_run_cases_batch_passes_max_wait(self, mock_runtime):
        """run_cases_batch() passes poll_interval and max_wait to chat_batch."""
        from seekflow.eval.runner import EvalRunner

        mock_runtime.chat_batch = MagicMock(return_value=[
            ToolRuntimeResult(final="ok", messages=[], tool_results=[]),
        ])

        cases = [EvalCase(id="c1", input="test")]

        runner = EvalRunner(mock_runtime, model="deepseek-chat")
        runner.run_cases_batch(cases, poll_interval=10.0, max_wait=600.0)

        call_kwargs = mock_runtime.chat_batch.call_args.kwargs
        assert call_kwargs["poll_interval"] == 10.0
        assert call_kwargs["max_wait"] == 600.0

    def test_report_print(self):
        """EvalReport.print() should not raise."""
        report = EvalReport(
            name="test_bench",
            model="deepseek-chat",
            metrics={
                "total_cases": 10,
                "passed_cases": 8,
                "failed_cases": 2,
                "success_rate": 80.0,
                "tool_name_accuracy": 90.0,
                "argument_accuracy": 85.0,
                "final_contains_accuracy": 88.0,
                "avg_steps": 2.4,
                "avg_latency_ms": 1530.0,
            },
            case_results=[
                {"case_id": "c1", "passed": True, "error": None},
                {"case_id": "c2", "passed": False, "error": "Tool name mismatch"},
            ],
        )
        # Should not raise
        report.print()
