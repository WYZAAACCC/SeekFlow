"""OpenTelemetry integration — spans, metrics, structured logging, trace records.

Gracefully degrades when the OTel SDK is not installed: all functions
become no-ops so the framework works without OTel as a dependency.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from seekflow.security import redact_secrets

logger = logging.getLogger("seekflow")

# ── OTel availability ───────────────────────────────────────────────────

_OTEL_AVAILABLE = False
try:
    from opentelemetry import trace, metrics  # noqa: F401
    _OTEL_AVAILABLE = True
except ImportError:
    pass


# ── Span management ─────────────────────────────────────────────────────

class _NoopSpan:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def set_attribute(self, key: str, value: Any): pass
    def set_status(self, status): pass
    def record_exception(self, exception): pass


def _get_tracer(name: str = "seekflow"):
    if _OTEL_AVAILABLE:
        from opentelemetry import trace
        return trace.get_tracer(name)
    return None


@contextmanager
def agent_span(role: str, task: str = ""):
    """Create a root span for an agent run."""
    tracer = _get_tracer()
    if tracer is None:
        yield _NoopSpan()
        return

    with tracer.start_as_current_span("agent.run") as span:
        span.set_attribute("agent.role", role)
        if task:
            span.set_attribute("agent.task", task[:200])
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            raise


@contextmanager
def step_span(step: int, phase: str = "unknown"):
    """Create a span for a single runtime step."""
    tracer = _get_tracer()
    if tracer is None:
        yield _NoopSpan()
        return

    with tracer.start_as_current_span("runtime.step") as span:
        span.set_attribute("step.index", step)
        span.set_attribute("step.phase", phase)
        yield span


@contextmanager
def tool_span(tool_name: str):
    """Create a span for tool execution."""
    tracer = _get_tracer()
    if tracer is None:
        yield _NoopSpan()
        return

    with tracer.start_as_current_span("tool.execute") as span:
        span.set_attribute("tool.name", tool_name)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            raise


# ── Structured logging helpers ──────────────────────────────────────────

def log_agent_start(role: str, task: str = "") -> None:
    logger.info("agent.start role=%r task=%r", role, task[:200])

def log_agent_end(role: str, cost: float = 0.0) -> None:
    logger.info("agent.end role=%r cost=%.6f", role, cost)

def log_tool_call(tool_name: str, ok: bool, latency_ms: int) -> None:
    level = logging.DEBUG if ok else logging.ERROR
    logger.log(level, "tool.call name=%r ok=%s latency_ms=%d", tool_name, ok, latency_ms)

def log_retry_attempt(reason: str, attempt: int, delay: float) -> None:
    logger.warning("retry.attempt reason=%r attempt=%d delay=%.3f", reason, attempt, delay)

def log_circuit_breaker_change(old_state: str, new_state: str) -> None:
    logger.warning("circuit_breaker.change old=%r new=%r", old_state, new_state)

def log_security_violation(violation_type: str, detail: str = "") -> None:
    logger.error("security.violation type=%r detail=%r", violation_type, detail[:200])


# ═══════════════════════════════════════════════════════════════════════════
# Trace records — structured execution timeline
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class StepTrace:
    """A single step in a run trace."""
    step: int
    kind: str  # "model_call", "tool_execute", "finalize", etc.
    started_at: float = 0.0
    ended_at: float | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class RunTrace:
    """Full trace of a single agent run — all steps, usage, cost, errors."""

    run_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    model: str | None = None
    steps: list[StepTrace] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    cost: dict = field(default_factory=dict)
    cache: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def add_step(self, kind: str, **metadata: Any) -> StepTrace:
        safe_metadata = {
            key: redact_secrets(str(value)) if isinstance(value, str) else value
            for key, value in metadata.items()
        }
        step = StepTrace(
            step=len(self.steps) + 1,
            kind=kind,
            started_at=time.time(),
            metadata=safe_metadata,
        )
        self.steps.append(step)
        return step

    def finish(self) -> None:
        self.ended_at = time.time()

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "model": self.model,
            "steps": [
                {
                    "step": s.step,
                    "kind": s.kind,
                    "started_at": s.started_at,
                    "ended_at": s.ended_at,
                    "metadata": s.metadata,
                }
                for s in self.steps
            ],
            "usage": self.usage,
            "cost": self.cost,
            "cache": self.cache,
            "errors": self.errors,
        }
