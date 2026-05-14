"""Policy Engine — centralized authorization for tool calls."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from seekflow.types import ToolDefinition, ToolPolicy


@dataclass
class PolicyDecision:
    """Result of a policy authorization check."""

    allowed: bool
    reason: str = ""
    requires_approval: bool = False
    approval_context: dict | None = None
    sanitized_args: dict | None = None


_DEFAULT_RESTRICTIVE_POLICY = ToolPolicy()


class PolicyEngine:
    """Centralized authorization gate for tool execution.

    Every tool call passes through ``authorize()`` before execution.
    Checks capabilities, workspace boundaries, URL domains, risk gating,
    and human-approval requirements.
    """

    def authorize(
        self,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        run_context: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        """Check whether *tool_def* may execute with *args*."""
        run_context = run_context or {}
        policy = tool_def.policy or _DEFAULT_RESTRICTIVE_POLICY

        # 1. Destructive always requires approval
        if policy.risk == "destructive":
            return PolicyDecision(
                allowed=True,
                requires_approval=True,
                reason="Destructive tool requires human approval",
            )

        # 2. Code execution requires sandbox
        if "code.exec" in policy.capabilities:
            sandbox = run_context.get("sandbox")
            if sandbox is None or getattr(sandbox, "name", "") == "no_sandbox":
                return PolicyDecision(
                    allowed=False,
                    reason="code_exec capability requires a configured sandbox",
                )

        # 3. Write requires workspace root
        if "filesystem.write" in policy.capabilities:
            if policy.workspace_root is None:
                return PolicyDecision(
                    allowed=False,
                    reason="filesystem.write requires workspace_root in policy",
                )

        # 4. URL validation via allowed_domains
        if "network.public_http" in policy.capabilities and policy.allowed_domains:
            url = args.get("url", "")
            if url:
                parsed = urlparse(url)
                hostname = parsed.hostname or ""
                if hostname not in policy.allowed_domains:
                    return PolicyDecision(
                        allowed=False,
                        reason=f"Domain '{hostname}' not in allowed_domains",
                    )

        # 5. Path validation via workspace_root
        if policy.workspace_root is not None:
            from seekflow.security import safe_join
            for key, val in args.items():
                if isinstance(val, str) and ("/" in val or "\\" in val):
                    # Resolve the raw value directly — absolute paths outside
                    # root will fail safe_join
                    try:
                        safe_join(policy.workspace_root, val)
                    except PermissionError as e:
                        return PolicyDecision(
                            allowed=False,
                            reason=str(e),
                        )

        # 6. Approval requirement
        if policy.requires_approval:
            return PolicyDecision(
                allowed=True,
                requires_approval=True,
                reason="Tool requires human approval",
            )

        return PolicyDecision(allowed=True)
