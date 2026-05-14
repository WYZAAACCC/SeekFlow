"""Trace event types — standardised event naming for observability."""
from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field


class TraceEvent(BaseModel):
    type: str
    timestamp: float = Field(default_factory=time.time)
    data: dict[str, Any] = Field(default_factory=dict)


class TraceRecord(BaseModel):
    trace_id: str
    started_at: str
    ended_at: str | None = None
    model: str | None = None
    events: list[TraceEvent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Canonical event type constants ──────────────────────────────────────────
# Use these when calling TraceRecorder.record() for consistent observability.

# DeepSeek API lifecycle
EVENT_DEEPSEEK_REQUEST_BUILT = "deepseek.request.built"
EVENT_DEEPSEEK_PROTOCOL_VALIDATED = "deepseek.protocol.validated"
EVENT_DEEPSEEK_RESPONSE_RECEIVED = "deepseek.response.received"

# Tool execution lifecycle
EVENT_TOOL_POLICY_CHECKED = "tool.policy.checked"
EVENT_TOOL_APPROVAL_REQUESTED = "tool.approval.requested"
EVENT_TOOL_EXECUTION_STARTED = "tool.execution.started"
EVENT_TOOL_EXECUTION_FINISHED = "tool.execution.finished"

# Reliability
EVENT_RETRY_SCHEDULED = "retry.scheduled"
EVENT_CIRCUIT_OPENED = "circuit.opened"

# Cost / cache
EVENT_BUDGET_PREFLIGHT_CHECKED = "budget.preflight.checked"
EVENT_CACHE_PREFIX_COMPILED = "cache.prefix.compiled"

# Canonical set for validation
ALL_CANONICAL_EVENTS: frozenset[str] = frozenset({
    EVENT_DEEPSEEK_REQUEST_BUILT,
    EVENT_DEEPSEEK_PROTOCOL_VALIDATED,
    EVENT_DEEPSEEK_RESPONSE_RECEIVED,
    EVENT_TOOL_POLICY_CHECKED,
    EVENT_TOOL_APPROVAL_REQUESTED,
    EVENT_TOOL_EXECUTION_STARTED,
    EVENT_TOOL_EXECUTION_FINISHED,
    EVENT_RETRY_SCHEDULED,
    EVENT_CIRCUIT_OPENED,
    EVENT_BUDGET_PREFLIGHT_CHECKED,
    EVENT_CACHE_PREFIX_COMPILED,
})
