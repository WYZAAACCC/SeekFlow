"""Trace event types."""
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
