"""MCP (Model Context Protocol) integration via stdio transport."""
from deepseek_toolkit.mcp.config import MCPServerConfig
from deepseek_toolkit.mcp.adapter import mcp_tool_to_deepseek_tool
from deepseek_toolkit.mcp.executor import MCPToolExecutor

__all__ = ["MCPServerConfig", "mcp_tool_to_deepseek_tool", "MCPToolExecutor"]
