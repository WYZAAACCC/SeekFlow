"""Configuration for MCP server connections."""
from __future__ import annotations

from enum import Enum

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
    allowed_capabilities: set[str] | None = None
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
        )

    def to_stdio_params(self):
        """Convert to mcp StdioServerParameters (lazy import)."""
        from mcp.client.stdio import StdioServerParameters

        return StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env if self.env else None,
        )
