"""Phase 3 tests: MCPGateway registry isolation + output schema validation."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from seekflow.mcp.gateway import MCPGatewayRegistry
from seekflow.mcp.runner import MCPGatewayRunner
from seekflow.tools.runners import ToolRunResult
from seekflow.types import ToolDefinition


def _make_tool_def(*, gateway_id="test-server", tool_name="test_tool", output_schema=None):
    metadata = {
        "_mcp_gateway_id": gateway_id,
        "_mcp_tool_name": tool_name,
        "_mcp_schema_hash": "abc123",
    }
    if output_schema is not None:
        metadata["_mcp_output_schema"] = output_schema
    return ToolDefinition(
        name=f"{gateway_id}__{tool_name}",
        description="test tool",
        parameters={"type": "object", "properties": {"x": {"type": "integer"}}},
        func=None,
        source="mcp",
        metadata=metadata,
    )


def test_mcp_gateway_runner_uses_injected_registry():
    """MCPGatewayRunner使用注入的registry而非全局变量"""
    registry = MCPGatewayRegistry()
    runner = MCPGatewayRunner(registry)
    assert runner.gateway_registry is registry


def test_two_registries_are_independent():
    """两个registry各自独立"""
    r1 = MCPGatewayRegistry()
    r2 = MCPGatewayRegistry()

    mock_gw = MagicMock()
    mock_gw.server_name = "test-server"
    r1.register(mock_gw)

    assert r1.get("test-server") is mock_gw
    assert r2.get("test-server") is None


def test_missing_gateway_fails_closed():
    """registry中无gateway→返回error"""
    registry = MCPGatewayRegistry()
    runner = MCPGatewayRunner(registry)
    tool_def = _make_tool_def()

    result = runner.run(tool_def, {"x": 1}, 30.0)
    assert result.ok is False
    assert "not found" in (result.error or "")


def test_mcp_output_schema_valid_passes():
    """输出符合schema→通过"""
    registry = MCPGatewayRegistry()
    mock_gw = MagicMock()
    mock_gw.server_name = "test-server"
    mock_gw.verify_frozen.return_value = None
    mock_result = MagicMock()
    mock_result.ok = True
    mock_result.result = {"status": "ok", "count": 42}
    mock_gw.execute.return_value = mock_result
    registry.register(mock_gw)

    runner = MCPGatewayRunner(registry)
    output_schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "count": {"type": "integer"},
        },
    }
    tool_def = _make_tool_def(output_schema=output_schema)

    result = runner.run(tool_def, {"x": 1}, 30.0)
    assert result.ok is True


def test_mcp_output_schema_invalid_fails_closed():
    """输出不符合schema→拒绝"""
    registry = MCPGatewayRegistry()
    mock_gw = MagicMock()
    mock_gw.server_name = "test-server"
    mock_gw.verify_frozen.return_value = None
    mock_result = MagicMock()
    mock_result.ok = True
    mock_result.result = {"status": "ok", "count": "not_a_number"}  # wrong type
    mock_gw.execute.return_value = mock_result
    registry.register(mock_gw)

    runner = MCPGatewayRunner(registry)
    output_schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "count": {"type": "integer"},
        },
    }
    tool_def = _make_tool_def(output_schema=output_schema)

    result = runner.run(tool_def, {"x": 1}, 30.0)
    assert result.ok is False
    assert "output schema validation failed" in (result.error or "")


def test_mcp_output_json_string_parsed_for_validation():
    """JSON字符串输出被解析而后校验"""
    registry = MCPGatewayRegistry()
    mock_gw = MagicMock()
    mock_gw.server_name = "test-server"
    mock_gw.verify_frozen.return_value = None
    mock_result = MagicMock()
    mock_result.ok = True
    mock_result.result = '{"status": "ok", "count": 42}'  # JSON string
    mock_gw.execute.return_value = mock_result
    registry.register(mock_gw)

    runner = MCPGatewayRunner(registry)
    output_schema = {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "count": {"type": "integer"},
        },
    }
    tool_def = _make_tool_def(output_schema=output_schema)

    result = runner.run(tool_def, {"x": 1}, 30.0)
    assert result.ok is True


def test_mcp_output_no_schema_passes_through():
    """无output_schema时直接通过"""
    registry = MCPGatewayRegistry()
    mock_gw = MagicMock()
    mock_gw.server_name = "test-server"
    mock_gw.verify_frozen.return_value = None
    mock_result = MagicMock()
    mock_result.ok = True
    mock_result.result = "anything goes"
    mock_gw.execute.return_value = mock_result
    registry.register(mock_gw)

    runner = MCPGatewayRunner(registry)
    tool_def = _make_tool_def()  # no output_schema

    result = runner.run(tool_def, {"x": 1}, 30.0)
    assert result.ok is True
