"""Tests for MCPToolExecutor."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from deepseek_toolkit.errors import MCPConnectionError
from deepseek_toolkit.mcp.config import MCPServerConfig
from deepseek_toolkit.types import ToolCall, ToolExecutionResult


class TestMCPToolExecutor:
    @pytest.fixture
    def configs(self):
        return [
            MCPServerConfig.stdio(name="fs", command="npx", args=["-y", "server-fs"]),
        ]

    @pytest.fixture
    def mock_mcp_session(self):
        """Mock an MCP ClientSession with basic tool listing and calling."""
        session = AsyncMock()
        session.initialize = AsyncMock()

        # Mock tool listing
        list_tools_result = MagicMock()
        list_tools_result.tools = [
            _make_mcp_tool("read_file", "Read a file", {"type": "object", "properties": {"path": {"type": "string"}}}),
            _make_mcp_tool("write_file", "Write a file", {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}),
        ]
        session.list_tools = AsyncMock(return_value=list_tools_result)

        # Mock tool calling
        call_result = MagicMock()
        call_result.content = []
        call_result.structuredContent = {"result": "file content here"}
        call_result.isError = False
        session.call_tool = AsyncMock(return_value=call_result)

        return session

    def test_execute_successful_mcp_tool(self, configs, mock_mcp_session):
        """Execute an MCP tool and get a successful result."""
        from deepseek_toolkit.mcp.executor import MCPToolExecutor

        executor = MCPToolExecutor(configs)
        executor._sessions = {"fs": mock_mcp_session}

        result = executor.execute_sync(
            ToolCall(id="call_1", name="fs.read_file", arguments={"path": "/tmp/test.txt"})
        )

        assert isinstance(result, ToolExecutionResult)
        assert result.ok is True
        assert result.name == "fs.read_file"

    def test_execute_unknown_server(self, configs):
        """Tool call to an unknown server returns error result."""
        from deepseek_toolkit.mcp.executor import MCPToolExecutor

        executor = MCPToolExecutor(configs)

        result = executor.execute_sync(
            ToolCall(id="call_2", name="unknown.read_file", arguments={})
        )

        assert result.ok is False
        assert "unknown" in result.error.lower()

    def test_execute_unknown_tool(self, configs, mock_mcp_session):
        """Tool call to a known server but unknown tool returns error."""
        from deepseek_toolkit.mcp.executor import MCPToolExecutor

        mock_mcp_session.call_tool.side_effect = Exception("Tool not found")
        executor = MCPToolExecutor(configs)
        executor._sessions = {"fs": mock_mcp_session}

        result = executor.execute_sync(
            ToolCall(id="call_3", name="fs.nonexistent", arguments={})
        )

        assert result.ok is False
        assert result.error is not None

    def test_execute_with_error_response(self, configs, mock_mcp_session):
        """MCP server returns isError=True."""
        from deepseek_toolkit.mcp.executor import MCPToolExecutor

        call_result = MagicMock()
        call_result.content = []
        call_result.structuredContent = None
        call_result.isError = True
        mock_mcp_session.call_tool = AsyncMock(return_value=call_result)

        executor = MCPToolExecutor(configs)
        executor._sessions = {"fs": mock_mcp_session}

        result = executor.execute_sync(
            ToolCall(id="call_4", name="fs.read_file", arguments={"path": "/bad"})
        )

        assert result.ok is False

    def test_executor_stores_last_error(self, configs, mock_mcp_session):
        """Connection errors should be captured."""
        from deepseek_toolkit.mcp.executor import MCPToolExecutor

        mock_mcp_session.call_tool.side_effect = MCPConnectionError("Connection lost")
        executor = MCPToolExecutor(configs)
        executor._sessions = {"fs": mock_mcp_session}

        result = executor.execute_sync(
            ToolCall(id="call_5", name="fs.read_file", arguments={})
        )

        assert result.ok is False
        assert "Connection lost" in result.error


def _make_mcp_tool(name: str, description: str, input_schema: dict):
    """Helper to create a mock MCP tool."""
    tool = MagicMock()
    tool.name = name
    tool.description = description
    tool.inputSchema = input_schema
    return tool
