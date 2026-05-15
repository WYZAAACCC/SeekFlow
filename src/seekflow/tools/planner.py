"""Execution planner — selects the appropriate runner for each tool call.

Routes tools to InProcessRunner (trusted reads only), ProcessRunner (default
untrusted isolation), or ContainerRunner (code_exec/destructive).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seekflow.types import ToolDefinition, ToolPolicy

# Runner isolation levels: higher = stronger isolation.
# An explicit runner override may only *increase* isolation, never decrease it.
RUNNER_ORDER: dict[str, int] = {"in_process": 0, "process": 1, "container": 2, "external_container": 3, "mcp_gateway": 3}


def _required_runner(policy: "ToolPolicy | None", tool_def: "ToolDefinition | None" = None) -> str:
    """Minimum isolation level required by this tool's risk/capabilities.

    Lv3: non-local tools (source != "local") always require external_container.
    """
    source = tool_def.source if tool_def else "local"
    caps = policy.capabilities if policy else set()
    risk = policy.risk if policy else "destructive"

    # Lv3: third-party tools must run in external containers
    if source != "local":
        return "external_container"

    if risk in {"code_exec", "destructive"} or "code.exec" in caps:
        return "container"
    if risk in {"network", "write"} or "network.public_http" in caps or "filesystem.write" in caps:
        return "process"
    if policy and policy.trusted and risk == "read" and policy.parallel_safe:
        return "in_process"
    return "process"


@dataclass
class ExecutionPlan:
    """Selected execution strategy for a tool call."""

    runner: str  # "in_process", "process", "container"
    timeout_s: float
    requires_hard_timeout: bool
    allow_parallel: bool
    cache_allowed: bool
    reason: str


def plan_execution(
    tool_def: "ToolDefinition",
    timeout: float | None,
) -> ExecutionPlan:
    """Select the appropriate runner for *tool_def* based on risk/trust/capabilities.

    Rules (first match wins):
    1. Explicit runner override on ToolPolicy (not "auto") — may only increase isolation
    2. code_exec / destructive → container only; if ContainerSandbox unavailable, executor denies
    3. network / write / filesystem.write → process
    4. trusted=True + risk="read" + parallel_safe=True → in_process
    5. Everything else → process (default untrusted isolation)
    """
    policy = tool_def.policy
    effective_timeout = timeout or 30.0

    # Use policy timeout as ceiling; caller timeout can be more restrictive
    if policy is not None and policy.timeout_s:
        effective_timeout = min(effective_timeout, policy.timeout_s)
    if tool_def.metadata and tool_def.metadata.get("timeout") is not None:
        effective_timeout = min(effective_timeout, float(tool_def.metadata["timeout"]))

    # 0. Lv3: non-local tools always run in external containers — hard gate
    if tool_def.source == "mcp":
        return ExecutionPlan(
            runner="mcp_gateway",
            timeout_s=effective_timeout,
            requires_hard_timeout=True,
            allow_parallel=False,
            cache_allowed=False,
            reason=f"source=mcp requires MCP gateway isolation",
        )
    if tool_def.source not in {"local", ""}:
        return ExecutionPlan(
            runner="external_container",
            timeout_s=effective_timeout,
            requires_hard_timeout=True,
            allow_parallel=False,
            cache_allowed=False,
            reason=f"source={tool_def.source} requires external container isolation",
        )

    # 1. Explicit runner override — may only increase isolation, never weaken it
    if policy is not None and policy.runner != "auto":
        required = _required_runner(policy, tool_def)
        requested = policy.runner
        if RUNNER_ORDER.get(requested, 0) < RUNNER_ORDER.get(required, 0):
            # Requested runner is weaker than required → upgrade to required
            return ExecutionPlan(
                runner=required,
                timeout_s=effective_timeout,
                requires_hard_timeout=required != "in_process",
                allow_parallel=False,
                cache_allowed=policy.risk == "read",
                reason=f"policy.runner={requested} upgraded to required runner={required} (minimum isolation)",
            )
        # Requested runner equals or exceeds required → use it
        return ExecutionPlan(
            runner=requested,
            timeout_s=effective_timeout,
            requires_hard_timeout=requested != "in_process",
            allow_parallel=requested == "in_process" and policy.parallel_safe,
            cache_allowed=policy.risk == "read",
            reason=f"explicit runner={requested}, required={required}",
        )

    risk = policy.risk if policy else "read"
    capabilities = policy.capabilities if policy else set()
    trusted = policy.trusted if policy else bool(tool_def.metadata.get("trusted", False) if tool_def.metadata else False)
    parallel_safe = policy.parallel_safe if policy else False

    # 2. code_exec / destructive → container only (fail-closed, no fallback)
    if risk in ("code_exec", "destructive") or "code.exec" in capabilities:
        return ExecutionPlan(
            runner="container",
            timeout_s=effective_timeout,
            requires_hard_timeout=True,
            allow_parallel=False,
            cache_allowed=False,
            reason=f"risk={risk} requires container isolation",
        )

    # 3. network / write / filesystem.write → process
    if risk in ("network", "write") or "filesystem.write" in capabilities:
        return ExecutionPlan(
            runner="process",
            timeout_s=effective_timeout,
            requires_hard_timeout=True,
            allow_parallel=False,
            cache_allowed=False,
            reason=f"risk={risk} requires process isolation",
        )

    # 4. trusted read + parallel_safe → in_process
    # When no policy exists but metadata declares trusted, allow in_process
    # without requiring parallel_safe (the tool owner explicitly opted in).
    if trusted and risk == "read":
        if parallel_safe or policy is None:
            return ExecutionPlan(
                runner="in_process",
                timeout_s=effective_timeout,
                requires_hard_timeout=False,
                allow_parallel=bool(parallel_safe),
                cache_allowed=True,
                reason="trusted read tool, safe for in-process execution",
            )

    # 5. Default: process isolation
    return ExecutionPlan(
        runner="process",
        timeout_s=effective_timeout,
        requires_hard_timeout=True,
        allow_parallel=False,
        cache_allowed=False,
        reason="default untrusted isolation",
    )
