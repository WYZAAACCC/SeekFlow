"""OpenTelemetry integration — minimal span-based tracing.

Uses OpenTelemetry if installed, falls back to no-op silently.
Creates spans for: Agent.run(), tool calls, model calls.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any

try:
    from opentelemetry import trace
    from opentelemetry.trace import Status, StatusCode
    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False


def _tracer():
    if _HAS_OTEL:
        return trace.get_tracer("deepseek_toolkit")
    return None


@contextmanager
def agent_span(agent_role: str, task: str):
    """Create an OpenTelemetry span for Agent.run()."""
    tracer = _tracer()
    if tracer is None:
        start = time.time()
        yield None
        return

    with tracer.start_as_current_span(
        "agent.run",
        attributes={
            "agent.role": agent_role,
            "task.preview": task[:200],
        },
    ) as span:
        start = time.time()
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise
        finally:
            span.set_attribute("duration_ms", (time.time() - start) * 1000)


@contextmanager
def tool_span(tool_name: str):
    """Create an OpenTelemetry span for a tool call."""
    tracer = _tracer()
    if tracer is None:
        yield None
        return

    with tracer.start_as_current_span(
        "tool.call",
        attributes={"tool.name": tool_name},
    ) as span:
        start = time.time()
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise
        finally:
            span.set_attribute("duration_ms", (time.time() - start) * 1000)


__all__ = ["agent_span", "tool_span"]
