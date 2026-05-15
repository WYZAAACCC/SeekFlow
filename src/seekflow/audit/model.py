"""Audit event model for Lv3 durable audit trail."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class EgressAudit(BaseModel):
    """Network egress audit entry."""
    url: str = ""
    domain: str = ""
    method: str = "GET"
    status_code: int = 0
    request_hash: str = ""
    response_hash: str = ""
    bytes_sent: int = 0
    bytes_received: int = 0
    allowed: bool = True
    block_reason: str | None = None


class AuditEvent(BaseModel):
    """A single audit event in the durable audit trail.

    Hash-chained: each event includes the hash of the previous event
    (prev_hash), forming a tamper-evident chain.
    """

    event_id: str
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    run_id: str = ""
    step: int = 0
    event_type: str = ""  # "tool_execution", "policy_decision", "secret_resolution", etc.

    # Tool identity
    tool_name: str | None = None
    tool_version: str | None = None
    tool_digest: str | None = None
    manifest_digest: str | None = None
    policy_digest: str | None = None

    # Input/output hashes (not values — values never in audit)
    input_hash: str | None = None
    output_hash: str | None = None

    # Execution context
    runner: str | None = None
    sandbox_image_digest: str | None = None

    # Egress audit
    egress: list[EgressAudit] = Field(default_factory=list)
    secret_refs: list[str] = Field(default_factory=list)

    # Hash chain
    prev_hash: str | None = None
    event_hash: str = ""

    # Outcome
    ok: bool = True
    error: str | None = None
    elapsed_ms: int = 0
