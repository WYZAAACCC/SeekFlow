"""Example 4: MCP filesystem integration.

Requires: pip install deepseek-toolkit[mcp]
Also requires Node.js and npx for @modelcontextprotocol/server-filesystem.

Security Note:
  Only connect to trusted MCP servers. MCP servers can access local files,
  network resources, and system services. Review server permissions before
  connecting.
"""
import asyncio

from deepseek_toolkit.mcp.config import MCPServerConfig
from deepseek_toolkit.mcp.adapter import mcp_tool_to_deepseek_tool


def show_config():
    """Show how to configure an MCP server connection."""
    config = MCPServerConfig.stdio(
        name="fs",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "."],
        env={},
    )

    print("MCP Server Config:")
    print(f"  Name: {config.name}")
    print(f"  Transport: {config.transport}")
    print(f"  Command: {config.command}")
    print(f"  Args: {config.args}")

    # Convert to MCP stdio parameters
    params = config.to_stdio_params()
    print(f"\nStdioServerParameters:")
    print(f"  command: {params.command}")
    print(f"  args: {params.args}")


def show_tool_conversion():
    """Show how MCP tools are converted to DeepSeek format."""
    from unittest.mock import MagicMock

    # Simulate MCP tools from a filesystem server
    mock_read = MagicMock()
    mock_read.name = "read_file"
    mock_read.description = "Read the contents of a file"
    mock_read.inputSchema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to read",
            },
        },
        "required": ["path"],
    }

    mock_write = MagicMock()
    mock_write.name = "write_file"
    mock_write.description = "Write content to a file"
    mock_write.inputSchema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path"},
            "content": {"type": "string", "description": "Content to write"},
        },
        "required": ["path", "content"],
    }

    import json

    print("\nConverted DeepSeek tools:")
    for tool in [mock_read, mock_write]:
        ds_tool = mcp_tool_to_deepseek_tool("fs", tool)
        print(f"  {ds_tool['function']['name']}")
        print(f"  {json.dumps(ds_tool['function']['parameters'], indent=4)}")
        print()


def main():
    show_config()
    show_tool_conversion()

    print("To connect to a real MCP server:")
    print("  1. Install: pip install deepseek-toolkit[mcp]")
    print("  2. Install Node.js (required for npx-based MCP servers)")
    print("  3. Run the async connection code (see MCPToolExecutor)")
    print()
    print("SECURITY: Only connect to trusted MCP servers.")


if __name__ == "__main__":
    main()
