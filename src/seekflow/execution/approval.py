"""Approval protocol — human-in-the-loop gate for dangerous tool calls."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from seekflow.types import ToolDefinition


@dataclass(frozen=True)
class ApprovalRequest:
    tool: ToolDefinition
    arguments: dict[str, Any]
    reason: str
    risk: str
    capability: set[str]
    run_id: str | None = None


@dataclass(frozen=True)
class ApprovalResult:
    approved: bool
    reason: str = ""


class ApprovalHandler(Protocol):
    """Protocol for approval handlers.

    Implementations may defer to a human operator, an automated policy
    engine, or a timeout-based default-deny.
    """

    def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        ...


class DefaultDenyApprovalHandler:
    """Default handler: deny all approval requests."""

    def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        return ApprovalResult(
            approved=False,
            reason="No approval handler configured. All approvals denied by default.",
        )
