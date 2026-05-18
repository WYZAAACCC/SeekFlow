"""Type definitions for Thinking Stress Benchmark v1."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunResult:
    """Standardized result from a single agent run."""

    framework: str
    mode: str
    thinking: bool | None
    success: bool
    final_output: str
    latency_s: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_cny: float
    tool_calls_count: int
    audit_log: list[dict[str, Any]]
    diff: str
    raw_error: str = ""
    diagnostics: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreBreakdown:
    """Six-dimension programmatic score (100 points total)."""

    total: float = 0.0
    public_tests: float = 0.0
    hidden_tests: float = 0.0
    static_scan: float = 0.0
    tool_process: float = 0.0
    patch_quality: float = 0.0
    final_report: float = 0.0


@dataclass
class TestResult:
    """Pass/fail counts for a test suite."""
    passed: int = 0
    total: int = 0

    @property
    def rate(self) -> float:
        return self.passed / self.total if self.total else 0.0


@dataclass
class ScoredRun:
    """Full result including scores and test results."""

    result: RunResult
    scores: ScoreBreakdown
    public_tests: TestResult = field(default_factory=TestResult)
    hidden_tests: TestResult = field(default_factory=TestResult)
