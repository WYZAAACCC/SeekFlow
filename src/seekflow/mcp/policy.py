"""MCP-specific policy enforcement for Lv3 gateway.

Per-server and per-tool policy rules that go beyond the general
PolicyLinter — MCP has additional constraints around tool discovery,
schema freezing, and capability inheritance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from seekflow.mcp.config import MCPServerConfig, MCPTrustLevel
from seekflow.types import ToolPolicy

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class MCPServerLintIssue:
    severity: Severity
    code: str
    message: str
    path: str = "$"


def validate_server_config(cfg: MCPServerConfig) -> list[MCPServerLintIssue]:
    """Validate an MCPServerConfig before connection.

    Returns list of issues. Errors block connection.
    """
    issues: list[MCPServerLintIssue] = []

    # Untrusted server must have env_allowlist if env is set
    if cfg.trust_level == MCPTrustLevel.UNTRUSTED and cfg.env and not cfg.env_allowlist:
        issues.append(MCPServerLintIssue(
            severity="error",
            code="MCP001",
            message="UNTRUSTED server with env set requires env_allowlist",
            path="$.env_allowlist",
        ))

    # Untrusted server cannot use network capability without allowed_domains
    if cfg.trust_level == MCPTrustLevel.UNTRUSTED:
        caps = cfg.allowed_capabilities or set()
        if "network.public_http" in caps and not cfg.allowed_domains:
            issues.append(MCPServerLintIssue(
                severity="error",
                code="MCP002",
                message="UNTRUSTED server with network.public_http requires allowed_domains",
                path="$.allowed_domains",
            ))

    # code_exec requires sandbox for untrusted
    if cfg.trust_level == MCPTrustLevel.UNTRUSTED and cfg.max_risk == "code_exec":
        if cfg.sandbox is None:
            issues.append(MCPServerLintIssue(
                severity="error",
                code="MCP003",
                message="UNTRUSTED server with max_risk=code_exec requires sandbox",
                path="$.sandbox",
            ))

    # command_digest recommended for non-local servers
    if cfg.command_digest is None and cfg.trust_level != MCPTrustLevel.TRUSTED:
        issues.append(MCPServerLintIssue(
            severity="warning",
            code="MCP004",
            message="command_digest not set — command pinning recommended",
            path="$.command_digest",
        ))

    return issues


def validate_tool_under_server(
    tool_policy: ToolPolicy,
    server_config: MCPServerConfig,
) -> list[MCPServerLintIssue]:
    """Validate that a tool's compiled policy does not exceed its server's ceiling.

    Returns issues — errors mean the tool must not be registered.
    """
    issues: list[MCPServerLintIssue] = []

    # Tool cannot have risk higher than server ceiling
    risk_order = {"read": 0, "network": 1, "write": 2, "code_exec": 3, "destructive": 4}
    tool_risk_level = risk_order.get(tool_policy.risk, 0)
    server_risk_level = risk_order.get(server_config.max_risk, 0)
    if tool_risk_level > server_risk_level:
        issues.append(MCPServerLintIssue(
            severity="error",
            code="MCP101",
            message=f"Tool risk {tool_policy.risk} exceeds server ceiling {server_config.max_risk}",
            path="$.risk",
        ))

    # Tool cannot have capabilities not in server allowlist
    server_caps = server_config.allowed_capabilities
    if server_caps is not None:
        extra = tool_policy.capabilities - server_caps
        if extra:
            issues.append(MCPServerLintIssue(
                severity="error",
                code="MCP102",
                message=f"Tool capabilities {sorted(extra)} not in server allowlist",
                path="$.capabilities",
            ))

    # Tool cannot use network domains not in server allowlist
    if tool_policy.allowed_domains and server_config.allowed_domains:
        extra_domains = tool_policy.allowed_domains - server_config.allowed_domains
        if extra_domains:
            issues.append(MCPServerLintIssue(
                severity="error",
                code="MCP103",
                message=f"Tool domains {extra_domains} not in server allowed_domains",
                path="$.allowed_domains",
            ))

    return issues
