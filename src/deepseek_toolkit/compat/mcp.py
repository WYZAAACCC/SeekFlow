"""MCP compatibility — convenience wrappers for MCP protocol integration."""
from __future__ import annotations

from deepseek_toolkit.mcp.config import MCPServerConfig
from deepseek_toolkit.mcp.adapter import mcp_tool_to_deepseek_tool


def create_mcp_config(name: str, command: str, args: list[str] | None = None) -> MCPServerConfig:
    """Create an MCP server configuration for stdio transport."""
    return MCPServerConfig.stdio(name=name, command=command, args=args or [])


__all__ = ["create_mcp_config", "mcp_tool_to_deepseek_tool", "MCPServerConfig"]
