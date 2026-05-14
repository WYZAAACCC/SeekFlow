"""Configuration for MCP server connections with security profiles."""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class MCPTrustLevel(str, Enum):
    TRUSTED = "trusted"
    SANDBOXED = "sandboxed"
    UNTRUSTED = "untrusted"


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server via stdio transport."""

    name: str
    transport: str = "stdio"
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    trust_level: MCPTrustLevel = MCPTrustLevel.SANDBOXED

    # Security profile
    allowed_capabilities: set[str] | None = None
    max_risk: str = "read"
    allowed_domains: set[str] = Field(default_factory=set)
    workspace_root: Path | None = None
    requires_approval: bool = False

    # Sandbox / isolation
    sandbox: Any | None = None
    env_allowlist: set[str] = Field(default_factory=set)
    cwd: Path | None = None

    # Connection
    startup_timeout: float = 10.0
    fail_fast: bool = False

    @classmethod
    def stdio(
        cls,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        trust_level: MCPTrustLevel = MCPTrustLevel.SANDBOXED,
        startup_timeout: float = 10.0,
        capabilities: set[str] | None = None,
    ) -> "MCPServerConfig":
        """Create a stdio MCP server configuration."""
        return cls(
            name=name,
            transport="stdio",
            command=command,
            args=args or [],
            env=env or {},
            trust_level=trust_level,
            startup_timeout=startup_timeout,
            allowed_capabilities=capabilities,
        )

    def to_stdio_params(self):
        """Convert to mcp StdioServerParameters (lazy import)."""
        from mcp.client.stdio import StdioServerParameters

        return StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env if self.env else None,
        )
