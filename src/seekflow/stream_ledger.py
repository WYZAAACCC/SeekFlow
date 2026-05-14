"""Streaming ledger — deduplication and retry safety for streaming responses."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StreamLedger:
    """Tracks emitted content and executed tool calls during a stream.

    Rules:
    - Content already emitted to the caller must not be re-emitted on retry.
    - Read-only / idempotent tools may reuse cached results across retries.
    - Write / destructive tools must never be re-executed on retry.
    """

    emitted_content: str = ""
    executed_tool_call_ids: set[str] = field(default_factory=set)

    def record_content(self, delta: str) -> None:
        self.emitted_content += delta

    def can_execute_tool(self, tool_call_id: str, *, idempotent: bool) -> bool:
        if tool_call_id not in self.executed_tool_call_ids:
            return True
        return idempotent

    def record_tool_execution(self, tool_call_id: str) -> None:
        self.executed_tool_call_ids.add(tool_call_id)

    @property
    def emitted_count(self) -> int:
        return len(self.emitted_content)
