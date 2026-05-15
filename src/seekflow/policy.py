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


@dataclass(frozen=True)
class _NormalizedPolicyContext:
    """Normalized context — single source of truth for all policy checks.

    Abstracts away the distinction between ToolExecutionContext, dict, and None.
    """

    dangerous_tools_enabled: bool = False
    allowed_capabilities: set[str] = field(default_factory=lambda: {"read"})
    max_risk: str = "read"
    workspace_root: Any | None = None
    allowed_domains: set[str] = field(default_factory=set)
    sandbox: Any | None = None
    run_id: str | None = None


_DEFAULT_UNTRUSTED_POLICY = ToolPolicy(
    capabilities=set(),
    risk="destructive",
    parallel_safe=False,
    requires_approval=True,
)


def _normalize_context(context: Any) -> _NormalizedPolicyContext:
    """Convert any context type into a _NormalizedPolicyContext.

    context=None is treated as conservative defaults (no dangerous tools,
    read-only, no workspace, empty domains, no sandbox).
    """
    if context is None:
        return _NormalizedPolicyContext()

    if isinstance(context, dict):
        import warnings
        warnings.warn(
            "dict policy context is deprecated; use ToolExecutionContext",
            DeprecationWarning,
            stacklevel=3,
        )
        return _NormalizedPolicyContext(
            dangerous_tools_enabled=bool(context.get("dangerous_tools_enabled", False)),
            allowed_capabilities=set(context.get("allowed_capabilities", {"read"})),
            max_risk=context.get("max_risk", "read"),
            workspace_root=context.get("workspace_root"),
            allowed_domains=set(context.get("allowed_domains", set())),
            sandbox=context.get("sandbox"),
            run_id=context.get("run_id"),
        )

    # ToolExecutionContext or similar object
    return _NormalizedPolicyContext(
        dangerous_tools_enabled=bool(getattr(context, "dangerous_tools_enabled", False)),
        allowed_capabilities=set(getattr(context, "allowed_capabilities", {"read"})),
        max_risk=getattr(context, "max_risk", "read"),
        workspace_root=getattr(context, "workspace_root", None),
        allowed_domains=set(getattr(context, "allowed_domains", set())),
        sandbox=getattr(context, "sandbox", None),
        run_id=getattr(context, "run_id", None),
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
        """Authorize using ToolPolicyContext (simpler, context-based check).

        .. deprecated::
            This method does NOT validate tool arguments (URLs, paths,
            workspace). Use :meth:`authorize` for full policy enforcement.
        """
        import warnings
        warnings.warn(
            "authorize_with_context() is deprecated — it does not validate tool arguments "
            "(URLs, paths, workspace). Use authorize(tool_def, args, context) for full "
            "policy enforcement.",
            DeprecationWarning,
            stacklevel=2,
        )

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

        All context types (None, dict, ToolExecutionContext) are normalized
        to _NormalizedPolicyContext so security checks are consistent.
        """
        policy = tool_def.policy or _DEFAULT_UNTRUSTED_POLICY
        ctx = _normalize_context(context)

        # 0. No-policy tools: deny unless explicitly allowed
        if tool_def.policy is None and not self._allow_no_policy:
            return PolicyDecision(
                allowed=False,
                reason="Tool has no policy configured. All tools require an explicit ToolPolicy.",
                requires_approval=True,
            )

        # 1. Dangerous tools gate
        if policy.risk != "read" and not ctx.dangerous_tools_enabled:
            return PolicyDecision(
                allowed=False,
                reason=f"Dangerous tools (risk={policy.risk}) are disabled.",
            )

        # 2. Risk ceiling
        if self.RISK_ORDER.get(policy.risk, 0) > self.RISK_ORDER.get(ctx.max_risk, 0):
            return PolicyDecision(
                allowed=False,
                reason=f"Tool risk {policy.risk} exceeds allowed risk {ctx.max_risk}.",
            )

        # 3. Capability gate — always enforced, even with context=None
        missing = policy.capabilities - ctx.allowed_capabilities
        if missing:
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
            if ctx.sandbox is None:
                return PolicyDecision(allowed=False,
                    reason="code_exec requires a configured sandbox")
            sandbox_name = getattr(ctx.sandbox, "name", "")
            if sandbox_name in ("no_sandbox", "abstract", ""):
                return PolicyDecision(allowed=False,
                    reason=f"code_exec denied: sandbox '{sandbox_name}' is not real")

        # 6. Filesystem requires workspace_root
        if "filesystem.read" in policy.capabilities or "filesystem.write" in policy.capabilities:
            root = policy.workspace_root or ctx.workspace_root
            if root is None:
                return PolicyDecision(allowed=False,
                    reason="filesystem capability requires workspace_root")

        # 7. Network requires non-empty allowed_domains + SSRF validation
        if "network.public_http" in policy.capabilities:
            domains = policy.allowed_domains or ctx.allowed_domains
            if not domains:
                return PolicyDecision(allowed=False,
                    reason="network.public_http requires non-empty allowed_domains")

            url_params = list(policy.url_params) if policy.url_params else ["url"]
            if not url_params:
                url_params = ["url"]

            from seekflow.security.http import NetworkPolicy, validate_url_strict
            for param in url_params:
                value = args.get(param)
                if not isinstance(value, str) or not value:
                    return PolicyDecision(allowed=False,
                        reason=f"network.public_http requires URL parameter '{param}'")
                try:
                    validate_url_strict(value, NetworkPolicy(allowed_domains=domains))
                except ValueError as e:
                    return PolicyDecision(allowed=False,
                        reason=f"SSRF blocked for '{param}': {e}")

        # 8. Path validation via path_params + workspace_root
        effective_root = policy.workspace_root or ctx.workspace_root
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
        # (for tools that accept URLs but aren't network.public_http)
        if "network.public_http" not in policy.capabilities:
            effective_domains = policy.allowed_domains or ctx.allowed_domains
            if policy.url_params and effective_domains:
                from seekflow.security.http import NetworkPolicy, validate_url_strict
                for name in policy.url_params:
                    val = args.get(name)
                    if isinstance(val, str) and val:
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
