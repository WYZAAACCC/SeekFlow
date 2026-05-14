"""Policy Engine — centralized authorization for tool calls."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from seekflow.types import ToolDefinition, ToolPolicy


@dataclass
class ToolPolicyContext:
    """Runtime context for policy authorization decisions."""

    dangerous_tools_enabled: bool = False
    allowed_capabilities: set[str] = field(default_factory=set)
    max_risk: Literal["read", "write", "network", "code_exec", "destructive"] = "read"


@dataclass
class PolicyDecision:
    """Result of a policy authorization check."""

    allowed: bool
    reason: str = ""
    requires_approval: bool = False
    approval_context: dict | None = None
    sanitized_args: dict | None = None


_DEFAULT_UNTRUSTED_POLICY = ToolPolicy(
    capabilities=set(),
    risk="destructive",
    parallel_safe=False,
    requires_approval=True,
)


class PolicyEngine:
    """Centralized authorization gate for tool execution.

    Every tool call passes through ``authorize()`` before execution.
    Checks capabilities, workspace boundaries, URL domains, risk gating,
    sandbox requirements, and human-approval requirements.
    """

    RISK_ORDER: dict[str, int] = {
        "read": 0, "network": 1, "write": 2, "code_exec": 3, "destructive": 4,
    }

    def __init__(
        self, allow_no_policy: bool = False,
        mode: Literal["strict", "compat"] = "strict",
    ):
        self._allow_no_policy = allow_no_policy
        self._mode = mode

    def authorize_with_context(
        self, policy: ToolPolicy, context: ToolPolicyContext,
    ) -> PolicyDecision:
        """Authorize using ToolPolicyContext (simpler, context-based check)."""
        if policy.risk != "read" and not context.dangerous_tools_enabled:
            return PolicyDecision(False, "Dangerous tools are disabled by default.")

        if self.RISK_ORDER.get(policy.risk, 0) > self.RISK_ORDER.get(context.max_risk, 0):
            return PolicyDecision(
                False,
                f"Tool risk {policy.risk} exceeds allowed risk {context.max_risk}.",
            )

        missing = policy.capabilities - context.allowed_capabilities
        if missing:
            return PolicyDecision(
                False, f"Missing capabilities: {sorted(missing)}",
            )

        if policy.requires_approval:
            return PolicyDecision(
                True, "requires human approval", requires_approval=True,
            )

        return PolicyDecision(True, "allowed")

    def authorize(
        self,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        context: Any = None,
    ) -> PolicyDecision:
        """Check whether *tool_def* may execute with *args*.

        When *context* is a ToolExecutionContext, performs full capability,
        risk, dangerous_tools_enabled, workspace, domain, and sandbox checks.
        Falls back to legacy dict-based checks when context is a plain dict.
        """
        policy = tool_def.policy or _DEFAULT_UNTRUSTED_POLICY

        # Support both ToolExecutionContext (object) and dict (legacy)
        if context is not None and isinstance(context, dict):
            if self._mode == "compat":
                dangerous_enabled = context.get("dangerous_tools_enabled", True)
                allowed_caps = context.get("allowed_capabilities", set())
                max_risk = context.get("max_risk", "destructive")
            else:
                # strict: dict context must be explicit
                dangerous_enabled = context.get("dangerous_tools_enabled", False)
                allowed_caps = context.get("allowed_capabilities", {"read"})
                max_risk = context.get("max_risk", "read")
            has_context = True
        elif context is not None and hasattr(context, "dangerous_tools_enabled"):
            dangerous_enabled = context.dangerous_tools_enabled
            allowed_caps = context.allowed_capabilities
            max_risk = context.max_risk
            has_context = True
        else:
            if self._mode == "compat":
                dangerous_enabled = True
                allowed_caps = set()
                max_risk = "destructive"
            else:
                dangerous_enabled = False
                allowed_caps = {"read"}
                max_risk = "read"
            has_context = False

        # 0. No-policy tools: deny unless explicitly allowed
        if tool_def.policy is None and not self._allow_no_policy:
            return PolicyDecision(
                allowed=False,
                reason="Tool has no policy configured. All tools require an explicit ToolPolicy.",
                requires_approval=True,
            )

        # 1. Dangerous tools gate
        if policy.risk != "read" and not dangerous_enabled:
            return PolicyDecision(
                allowed=False,
                reason=f"Dangerous tools (risk={policy.risk}) are disabled.",
            )

        # 2. Risk ceiling
        if self.RISK_ORDER.get(policy.risk, 0) > self.RISK_ORDER.get(max_risk, 0):
            return PolicyDecision(
                allowed=False,
                reason=f"Tool risk {policy.risk} exceeds allowed risk {max_risk}.",
            )

        # 3. Capability gate (only for proper ToolExecutionContext, not dict)
        missing = policy.capabilities - allowed_caps
        if has_context and not isinstance(context, dict) and missing:
            return PolicyDecision(
                allowed=False,
                reason=f"Missing capabilities: {sorted(missing)}",
            )

        # 4. Destructive always requires approval
        if policy.risk == "destructive":
            return PolicyDecision(allowed=True, requires_approval=True,
                                  reason="Destructive tool requires human approval")

        # 5. Code execution requires sandbox
        if "code.exec" in policy.capabilities:
            sandbox = getattr(context, "sandbox", None) if has_context else (context or {}).get("sandbox")
            if sandbox is None:
                return PolicyDecision(allowed=False,
                    reason="code_exec requires a configured sandbox")
            if getattr(sandbox, "name", "") in ("no_sandbox", "abstract"):
                return PolicyDecision(allowed=False,
                    reason=f"code_exec denied: sandbox '{getattr(sandbox, 'name' ,'')}' is not real")

        # 6. Filesystem requires workspace_root
        if "filesystem.read" in policy.capabilities or "filesystem.write" in policy.capabilities:
            if isinstance(context, dict):
                root = policy.workspace_root or context.get("workspace_root")
            elif has_context:
                root = policy.workspace_root or getattr(context, "workspace_root", None)
            else:
                root = policy.workspace_root
            if root is None:
                return PolicyDecision(allowed=False,
                    reason="filesystem capability requires workspace_root")

        # 7. Network requires allowed_domains + strict SSRF validation
        if "network.public_http" in policy.capabilities:
            domains = policy.allowed_domains or (
                getattr(context, "allowed_domains", set()) if has_context and not isinstance(context, dict) else set()
            )
            url = args.get("url", "")
            if not url:
                return PolicyDecision(allowed=False,
                    reason="network.public_http requires a URL argument")
            if domains:
                from seekflow.security.http import NetworkPolicy, validate_url_strict
                try:
                    validate_url_strict(url, NetworkPolicy(allowed_domains=domains))
                except ValueError as e:
                    return PolicyDecision(allowed=False,
                        reason=f"SSRF blocked: {e}")

        # 8. Path validation via path_params + workspace_root
        effective_root = policy.workspace_root or (
            getattr(context, "workspace_root", None) if has_context and not isinstance(context, dict) else None
        )
        if effective_root is not None and policy.path_params:
            from seekflow.security import safe_join
            for name in policy.path_params:
                val = args.get(name)
                if isinstance(val, str):
                    try:
                        safe_join(effective_root, val)
                    except PermissionError as e:
                        return PolicyDecision(allowed=False, reason=str(e))

        # 9. URL validation via url_params + allowed_domains
        effective_domains = policy.allowed_domains or (
            getattr(context, "allowed_domains", set()) if has_context and not isinstance(context, dict) else set()
        )
        if policy.url_params and effective_domains:
            for name in policy.url_params:
                val = args.get(name)
                if isinstance(val, str) and val:
                    from seekflow.security.http import NetworkPolicy, validate_url_strict
                    try:
                        validate_url_strict(val, NetworkPolicy(allowed_domains=effective_domains))
                    except ValueError as e:
                        return PolicyDecision(allowed=False,
                            reason=f"URL validation blocked: {e}")

        # 10. Approval requirement
        if policy.requires_approval:
            return PolicyDecision(allowed=True, requires_approval=True,
                                  reason="Tool requires human approval")

        return PolicyDecision(allowed=True)
