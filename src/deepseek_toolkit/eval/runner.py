"""Eval runner — executes benchmark cases against a ToolRuntime."""
from __future__ import annotations

import time

from deepseek_toolkit.eval.metrics import calculate_metrics
from deepseek_toolkit.eval.types import EvalCase, EvalReport


class EvalRunner:
    """Runs eval cases against a ToolRuntime and produces reports."""

    def __init__(self, runtime, model: str) -> None:
        self.runtime = runtime
        self.model = model

    def run_file(self, path: str) -> EvalReport:
        """Load a benchmark file and run all cases."""
        from deepseek_toolkit.eval.loader import load_benchmark

        name, model, cases = load_benchmark(path)
        model = model or self.model
        return self._run(name, model, cases)

    def run_cases(self, cases: list[EvalCase]) -> EvalReport:
        """Run a list of eval cases directly."""
        return self._run("eval", self.model, cases)

    def run_cases_batch(
        self,
        cases: list[EvalCase],
        poll_interval: float = 30.0,
        max_wait: float = 3600.0,
    ) -> EvalReport:
        """Run eval cases via Batch API (single submission, lower cost).

        All cases are submitted as one batch. Results are evaluated after
        the batch completes. No multi-turn tool loops — tool results are
        not sent back to the model.
        """
        if not cases:
            return EvalReport(
                name="eval-batch", model=self.model,
                metrics={"total_cases": 0, "passed_cases": 0, "failed_cases": 0,
                         "success_rate": 0.0, "tool_name_accuracy": 0.0,
                         "argument_accuracy": 0.0, "final_contains_accuracy": 0.0,
                         "avg_steps": 0.0, "avg_latency_ms": 0.0},
                case_results=[],
            )

        print(f"Submitting batch of {len(cases)} requests...")
        batch_requests = []
        for case in cases:
            batch_requests.append({
                "messages": [{"role": "user", "content": case.input}],
            })

        results = self.runtime.chat_batch(
            model=self.model,
            requests=batch_requests,
            poll_interval=poll_interval,
            max_wait=max_wait,
        )

        print(f"Downloading results...")

        case_results: list[dict] = []
        for case, result in zip(cases, results):
            case_results.append(self._eval_result(case, result))

        metrics = calculate_metrics(case_results)
        print(f"Done. {metrics.get('passed_cases', 0)}/{metrics.get('total_cases', 0)} passed.")
        return EvalReport(
            name="eval-batch", model=self.model,
            metrics=metrics, case_results=case_results,
        )

    def _eval_result(self, case: EvalCase, result, latency_ms: float = 0) -> dict:
        """Evaluate a single ToolRuntimeResult against expected case outcomes."""
        tool_name_match = True
        argument_match = True

        called_names = [tr.name for tr in result.tool_results if tr.ok]

        for i, expected in enumerate(case.expected_tools):
            if i >= len(called_names):
                tool_name_match = False
                argument_match = False
            elif called_names[i] != expected.name:
                tool_name_match = False
                argument_match = False
            elif expected.arguments:
                if i < len(result.tool_results):
                    actual_args = result.tool_results[i].arguments
                    if not _dict_contains(actual_args, expected.arguments):
                        argument_match = False

        if len(called_names) < len(case.expected_tools):
            tool_name_match = False
            argument_match = False

        final_contains_match = True
        for phrase in case.expected_final_contains:
            if phrase not in result.final:
                final_contains_match = False
                break

        all_passed = tool_name_match and argument_match and final_contains_match

        return {
            "case_id": case.id,
            "passed": all_passed,
            "error": None if all_passed else _describe_failure(
                tool_name_match, argument_match, final_contains_match
            ),
            "tool_name_match": tool_name_match,
            "argument_match": argument_match,
            "final_contains_match": final_contains_match,
            "steps": len(result.tool_results),
            "latency_ms": latency_ms,
        }

    def _run(self, name: str, model: str, cases: list[EvalCase]) -> EvalReport:
        case_results: list[dict] = []

        for case in cases:
            start = time.time()

            try:
                result = self.runtime.chat(
                    model=model,
                    messages=[{"role": "user", "content": case.input}],
                )
                latency_ms = (time.time() - start) * 1000
            except Exception as e:
                case_results.append({
                    "case_id": case.id,
                    "passed": False,
                    "error": str(e),
                    "tool_name_match": False,
                    "argument_match": False,
                    "final_contains_match": False,
                    "steps": 0,
                    "latency_ms": 0,
                })
                continue

            case_results.append(self._eval_result(case, result, latency_ms=latency_ms))

        metrics = calculate_metrics(case_results)
        return EvalReport(name=name, model=model, metrics=metrics, case_results=case_results)


def _dict_contains(actual: dict, expected: dict) -> bool:
    """Check that actual dict contains all key-value pairs from expected."""
    for key, value in expected.items():
        if key not in actual:
            return False
        if actual[key] != value:
            return False
    return True


def _describe_failure(
    tool_name_match: bool,
    argument_match: bool,
    final_contains_match: bool,
) -> str:
    parts = []
    if not tool_name_match:
        parts.append("Tool name mismatch")
    if not argument_match:
        parts.append("Argument mismatch")
    if not final_contains_match:
        parts.append("Final text does not contain expected text")
    return "; ".join(parts)
