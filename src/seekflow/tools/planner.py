"""Execution planner — selects the appropriate runner for each tool call.

Routes tools to InProcessRunner (trusted reads only), ProcessRunner (default
untrusted isolation), or ContainerRunner (code_exec/destructive).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from seekflow.types import ToolDefinition


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
    1. Explicit runner override on ToolPolicy (not "auto")
    2. code_exec / destructive → container (ProcessRunner fallback)
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

    # 1. Explicit runner override
    if policy is not None and policy.runner != "auto":
        return ExecutionPlan(
            runner=policy.runner,
            timeout_s=effective_timeout,
            requires_hard_timeout=policy.runner != "in_process",
            allow_parallel=policy.parallel_safe,
            cache_allowed=policy.risk == "read",
            reason=f"explicit policy runner: {policy.runner}",
        )

    risk = policy.risk if policy else "read"
    capabilities = policy.capabilities if policy else set()
    trusted = policy.trusted if policy else bool(tool_def.metadata.get("trusted", False) if tool_def.metadata else False)
    parallel_safe = policy.parallel_safe if policy else False

    # 2. code_exec / destructive → container (with process fallback)
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
