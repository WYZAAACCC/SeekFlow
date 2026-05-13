"""Configuration for MCP server connections."""
from __future__ import annotations

from pydantic import BaseModel, Field


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server via stdio transport."""

    name: str
    transport: str = "stdio"
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def stdio(
        cls,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> "MCPServerConfig":
        """Create a stdio MCP server configuration."""
        return cls(
            name=name,
            transport="stdio",
            command=command,
            args=args or [],
            env=env or {},
        )

    def to_stdio_params(self):
        """Convert to mcp StdioServerParameters (lazy import)."""
        from mcp.client.stdio import StdioServerParameters

        return StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env if self.env else None,
        )
