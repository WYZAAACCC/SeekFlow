"""Trace recorder for tool call execution."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from deepseek_toolkit.trace.events import TraceEvent, TraceRecord


class TraceRecorder:
    """Records a timeline of events during tool call execution."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._record = TraceRecord(
            trace_id=str(uuid.uuid4()),
            started_at=datetime.now(timezone.utc).isoformat(),
        )

    def record(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Record an event if enabled."""
        if not self.enabled:
            return
        self._record.events.append(
            TraceEvent(type=event_type, data=data or {})
        )

    def finish(self) -> None:
        """Mark the trace as finished."""
        self._record.ended_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        """Export trace as a dictionary."""
        return self._record.model_dump(mode="json")

    def to_json(self) -> str:
        """Export trace as a JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def save(self, path: str) -> None:
        """Save trace to a JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
