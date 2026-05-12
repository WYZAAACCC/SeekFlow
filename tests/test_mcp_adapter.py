"""Tests for MCP tool adapter."""

from deepseek_toolkit.mcp.adapter import mcp_tool_to_deepseek_tool


class TestMCPToolAdapter:
    def test_basic_conversion(self):
        """MCP tool with simple inputSchema should convert to DeepSeek format."""
        mcp_tool = _make_mcp_tool(
            name="read_file",
            description="Read a file",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                },
                "required": ["path"],
            },
        )

        result = mcp_tool_to_deepseek_tool("fs", mcp_tool)

        assert result["type"] == "function"
        assert result["function"]["name"] == "fs.read_file"
        assert result["function"]["description"] == "Read a file"
        assert result["function"]["parameters"]["type"] == "object"
        assert "path" in result["function"]["parameters"]["properties"]

    def test_namespace_prefix(self):
        """Tool name is prefixed with server name."""
        mcp_tool = _make_mcp_tool(
            name="search",
            description="Search docs",
            input_schema={"type": "object", "properties": {}},
        )

        result = mcp_tool_to_deepseek_tool("docs", mcp_tool)
        assert result["function"]["name"] == "docs.search"

    def test_no_input_schema(self):
        """Tool without inputSchema gets default empty object schema."""
        mcp_tool = _make_mcp_tool(
            name="ping",
            description="Ping server",
            input_schema={"type": "object", "properties": {}},
        )

        result = mcp_tool_to_deepseek_tool("server", mcp_tool)
        assert result["function"]["parameters"]["type"] == "object"

    def test_complex_schema_with_nested_objects(self):
        """Nested object properties should survive conversion."""
        mcp_tool = _make_mcp_tool(
            name="create_user",
            description="Create a user",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "address": {
                        "type": "object",
                        "properties": {
                            "city": {"type": "string"},
                            "zip": {"type": "integer"},
                        },
                    },
                },
                "required": ["name"],
            },
        )

        result = mcp_tool_to_deepseek_tool("app", mcp_tool)
        params = result["function"]["parameters"]
        assert "address" in params["properties"]
        assert params["properties"]["address"]["type"] == "object"
        assert "city" in params["properties"]["address"]["properties"]

    def test_multiple_mcp_tools(self):
        """Each MCP tool converts independently."""
        tool_a = _make_mcp_tool(name="a", input_schema={"type": "object", "properties": {}})
        tool_b = _make_mcp_tool(name="b", input_schema={"type": "object", "properties": {}})

        result_a = mcp_tool_to_deepseek_tool("srv", tool_a)
        result_b = mcp_tool_to_deepseek_tool("srv", tool_b)

        assert result_a["function"]["name"] == "srv.a"
        assert result_b["function"]["name"] == "srv.b"


def _make_mcp_tool(name: str, description: str = "", input_schema: dict | None = None):
    """Helper to create a mock MCP tool object."""
    from unittest.mock import MagicMock

    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = input_schema or {"type": "object", "properties": {}}
    return tool
