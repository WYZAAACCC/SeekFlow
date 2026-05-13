"""YAML benchmark loader."""
from __future__ import annotations

from pathlib import Path

import yaml

from seekflow.eval.types import EvalCase, ExpectedToolCall


def load_benchmark(path: str) -> tuple[str, str, list[EvalCase]]:
    """Load a YAML benchmark file.

    Returns (benchmark_name, model, cases).
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    name = raw.get("name", "unknown")
    model = raw.get("model", "deepseek-chat")

    cases: list[EvalCase] = []
    for entry in raw.get("cases", []):
        expected_tools = [
            ExpectedToolCall(name=et["name"], arguments=et.get("arguments", {}))
            for et in entry.get("expected_tools", [])
        ]
        cases.append(EvalCase(
            id=entry["id"],
            input=entry["input"],
            expected_tools=expected_tools,
            expected_final_contains=entry.get("expected_final_contains", []),
        ))

    return name, model, cases
