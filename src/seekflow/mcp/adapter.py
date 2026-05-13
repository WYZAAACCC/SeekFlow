"""Convert MCP tools to DeepSeek-compatible tool schemas."""
from __future__ import annotations

from typing import Any


def mcp_tool_to_deepseek_tool(
    server_name: str,
    mcp_tool: Any,
    strict: bool = False,
) -> dict:
    """Convert an MCP tool definition to DeepSeek tools schema format.

    Tool names are namespaced as ``{server_name}.{tool_name}``.
    """
    # Copy inputSchema so we don't mutate the original
    params: dict[str, Any] = dict(mcp_tool.inputSchema) if mcp_tool.inputSchema else {
        "type": "object",
        "properties": {},
    }

    # Ensure it has type: object at minimum
    if "type" not in params:
        params["type"] = "object"

    return {
        "type": "function",
        "function": {
            "name": f"{server_name}.{mcp_tool.name}",
            "description": mcp_tool.description or "",
            "parameters": params,
        },
    }
