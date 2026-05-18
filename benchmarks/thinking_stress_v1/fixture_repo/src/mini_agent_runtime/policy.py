"""Policy engine for tool authorization.

BUG: missing policy defaults to allow (should be deny-by-default).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolPolicy:
    name: str
    capabilities: set[str]
    risk: str
    trusted: bool = False


def authorize_tool_call(
    tool_name: str,
    requested_capability: str,
    policies: dict[str, ToolPolicy],
) -> bool:
    """Authorize a tool call against policy registry.

    BUG:
    Missing policy defaults to allow (returns True).
    Should be deny-by-default.
    """
    policy = policies.get(tool_name)
    if policy is None:
        return True

    return requested_capability in policy.capabilities
