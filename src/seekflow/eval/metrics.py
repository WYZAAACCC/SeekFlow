"""Metrics calculation for eval results."""
from __future__ import annotations


def calculate_metrics(case_results: list[dict]) -> dict[str, float]:
    """Calculate aggregate metrics from case results.

    Each case_result dict may contain:
    - passed: bool
    - tool_name_match: bool
    - argument_match: bool
    - final_contains_match: bool
    - steps: int
    - latency_ms: float
    """
    total = len(case_results)
    if total == 0:
        return {
            "total_cases": 0,
            "passed_cases": 0,
            "failed_cases": 0,
            "success_rate": 0.0,
            "tool_name_accuracy": 0.0,
            "argument_accuracy": 0.0,
            "final_contains_accuracy": 0.0,
            "avg_steps": 0.0,
            "avg_latency_ms": 0.0,
        }

    passed = sum(1 for c in case_results if c.get("passed"))
    tool_name_match = sum(1 for c in case_results if c.get("tool_name_match"))
    argument_match = sum(1 for c in case_results if c.get("argument_match"))
    final_contains_match = sum(1 for c in case_results if c.get("final_contains_match"))
    steps = [c.get("steps", 0) for c in case_results]
    latencies = [c.get("latency_ms", 0) for c in case_results]

    return {
        "total_cases": total,
        "passed_cases": passed,
        "failed_cases": total - passed,
        "success_rate": (passed / total) * 100,
        "tool_name_accuracy": (tool_name_match / total) * 100,
        "argument_accuracy": (argument_match / total) * 100,
        "final_contains_accuracy": (final_contains_match / total) * 100,
        "avg_steps": sum(steps) / total,
        "avg_latency_ms": sum(latencies) / total,
    }
