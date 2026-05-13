"""MCP (Model Context Protocol) integration via stdio transport."""
from seekflow.mcp.config import MCPServerConfig
from seekflow.mcp.adapter import mcp_tool_to_deepseek_tool
from seekflow.mcp.executor import MCPToolExecutor

__all__ = ["MCPServerConfig", "mcp_tool_to_deepseek_tool", "MCPToolExecutor"]
