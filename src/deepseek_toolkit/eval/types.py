"""Eval data types."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExpectedToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class EvalCase(BaseModel):
    id: str
    input: str
    expected_tools: list[ExpectedToolCall] = Field(default_factory=list)
    expected_final_contains: list[str] = Field(default_factory=list)


class EvalReport(BaseModel):
    name: str
    model: str
    metrics: dict[str, float]
    case_results: list[dict]

    def print(self) -> None:
        """Rich formatted output of the evaluation report."""
        try:
            from rich.console import Console
            from rich.table import Table
        except ImportError:
            # Fallback to plain text
            self._print_plain()
            return

        console = Console()
        console.print()
        console.print(f"[bold]Benchmark:[/bold] {self.name}", style="")
        console.print(f"[bold]Model:[/bold] {self.model}", style="")
        console.print()

        # Metrics table
        table = Table(title="Metrics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        metric_labels = [
            ("total_cases", "Total cases"),
            ("passed_cases", "Passed"),
            ("failed_cases", "Failed"),
            ("success_rate", "Success rate"),
            ("tool_name_accuracy", "Tool name accuracy"),
            ("argument_accuracy", "Argument accuracy"),
            ("final_contains_accuracy", "Final contains accuracy"),
            ("avg_steps", "Average steps"),
            ("avg_latency_ms", "Average latency (ms)"),
        ]

        for key, label in metric_labels:
            if key in self.metrics:
                val = self.metrics[key]
                if key in ("success_rate", "tool_name_accuracy", "argument_accuracy", "final_contains_accuracy"):
                    table.add_row(label, f"{val:.2f}%")
                elif key == "avg_steps":
                    table.add_row(label, f"{val:.1f}")
                elif key == "avg_latency_ms":
                    table.add_row(label, f"{val:.0f} ms")
                else:
                    table.add_row(label, f"{int(val)}")

        console.print(table)

        # Case results
        if self.case_results:
            case_table = Table(title="Case Results")
            case_table.add_column("Case ID", style="cyan")
            case_table.add_column("Passed", style="green")
            case_table.add_column("Error", style="red")

            for cr in self.case_results:
                passed = "PASS" if cr.get("passed") else "FAIL"
                error = cr.get("error") or ""
                case_table.add_row(cr.get("case_id", ""), passed, error)

            console.print()
            console.print(case_table)

    def _print_plain(self) -> None:
        """Plain text fallback for environments without Rich."""
        print(f"\nBenchmark: {self.name}")
        print(f"Model: {self.model}\n")
        for key, value in self.metrics.items():
            print(f"  {key}: {value}")
