"""Tool execution context — security profile for a single agent run."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

RiskLevel = Literal["read", "network", "write", "code_exec", "destructive"]


@dataclass(frozen=True)
class ToolExecutionContext:
    """Immutable security context for tool execution.

    Passed from Agent → Runtime → Executor to enforce capability, risk,
    workspace, domain, sandbox, and cost boundaries per run.
    """

    run_id: str
    user_id: str | None = None
    tenant_id: str | None = None

    dangerous_tools_enabled: bool = False
    allowed_capabilities: set[str] = field(default_factory=set)
    max_risk: RiskLevel = "read"

    workspace_root: Path | None = None
    allowed_domains: set[str] = field(default_factory=set)

    sandbox_required: bool = True
    sandbox: Any | None = None

    cost_budget_remaining: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def conservative(cls, run_id: str = "unknown") -> "ToolExecutionContext":
        """Create the most restrictive context — safe for unknown callers."""
        return cls(
            run_id=run_id,
            dangerous_tools_enabled=False,
            allowed_capabilities={"read"},
            max_risk="read",
            sandbox_required=True,
        )
