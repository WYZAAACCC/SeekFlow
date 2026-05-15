"""Phase D: MCPGateway — zero-trust MCP server sandbox tests."""
import json
import hashlib
from pathlib import Path
from unittest import mock

import pytest

from seekflow.mcp.config import MCPServerConfig, MCPTrustLevel
from seekflow.mcp.gateway import (
    MCPGateway, MCPGatewayError, GatewayAuditRecord, FrozenTool,
)
from seekflow.mcp.policy import (
    validate_server_config, validate_tool_under_server,
    MCPServerLintIssue,
)
from seekflow.types import ToolPolicy


class TestMCPServerConfig:
    """Lv3 MCPServerConfig hardening."""

    def test_default_trust_level_is_untrusted(self):
        cfg = MCPServerConfig(name="test", command="python")
        assert cfg.trust_level == MCPTrustLevel.UNTRUSTED

    def test_command_digest_field(self):
        cfg = MCPServerConfig(name="test", command="python",
                              command_digest="sha256:abc123")
        assert cfg.command_digest == "sha256:abc123"

    def test_env_allowlist_defaults_to_empty(self):
        cfg = MCPServerConfig(name="test", command="python")
        assert cfg.env_allowlist == set()

    def test_freeze_tools_defaults_to_true(self):
        cfg = MCPServerConfig(name="test", command="python")
        assert cfg.freeze_tools is True

    def test_to_stdio_params_filters_env(self):
        cfg = MCPServerConfig(
            name="test", command="python",
            env_allowlist={"PATH", "HOME"},
            env={"SECRET": "should_be_filtered"},
        )
        with mock.patch.dict("os.environ", {"PATH": "/usr/bin", "HOME": "/home/user"}):
            params = cfg.to_stdio_params()
        assert params.env is not None
        assert "PATH" in params.env
        assert "SECRET" not in params.env  # not in allowlist

    def test_to_stdio_params_no_allowlist_raises(self):
        """Lv3: env without allowlist raises ValueError."""
        cfg = MCPServerConfig(
            name="test", command="python",
            env={"MY_VAR": "value"},
        )
        with pytest.raises(ValueError, match="env_allowlist"):
            cfg.to_stdio_params()


class TestServerConfigValidation:
    """validate_server_config rules."""

    def test_untrusted_with_env_requires_allowlist(self):
        cfg = MCPServerConfig(
            name="test", command="python",
            trust_level=MCPTrustLevel.UNTRUSTED,
            env={"SECRET": "x"},
        )
        issues = validate_server_config(cfg)
        assert any(i.code == "MCP001" for i in issues)

    def test_untrusted_network_requires_domains(self):
        cfg = MCPServerConfig(
            name="test", command="python",
            trust_level=MCPTrustLevel.UNTRUSTED,
            allowed_capabilities={"network.public_http"},
        )
        issues = validate_server_config(cfg)
        assert any(i.code == "MCP002" for i in issues)

    def test_untrusted_code_exec_requires_sandbox(self):
        cfg = MCPServerConfig(
            name="test", command="python",
            trust_level=MCPTrustLevel.UNTRUSTED,
            max_risk="code_exec",
        )
        issues = validate_server_config(cfg)
        assert any(i.code == "MCP003" for i in issues)

    def test_missing_command_digest_warns(self):
        cfg = MCPServerConfig(
            name="test", command="python",
            trust_level=MCPTrustLevel.UNTRUSTED,
        )
        issues = validate_server_config(cfg)
        assert any(i.code == "MCP004" and i.severity == "warning" for i in issues)

    def test_valid_config_passes(self):
        cfg = MCPServerConfig(
            name="test", command="python",
            trust_level=MCPTrustLevel.UNTRUSTED,
            env_allowlist={"PATH"},
            env={"PATH": "/usr/bin"},
            command_digest="sha256:abc",
        )
        issues = validate_server_config(cfg)
        assert not any(i.severity == "error" for i in issues)


class TestToolUnderServer:
    """validate_tool_under_server — per-tool ceiling enforcement."""

    def test_tool_risk_exceeds_server_ceiling(self):
        cfg = MCPServerConfig(name="test", command="python", max_risk="read")
        policy = ToolPolicy(risk="network")
        issues = validate_tool_under_server(policy, cfg)
        assert any(i.code == "MCP101" for i in issues)

    def test_tool_capability_not_in_server_allowlist(self):
        cfg = MCPServerConfig(
            name="test", command="python",
            allowed_capabilities={"read"},
        )
        policy = ToolPolicy(capabilities={"network.public_http"})
        issues = validate_tool_under_server(policy, cfg)
        assert any(i.code == "MCP102" for i in issues)

    def test_tool_domains_not_in_server_allowlist(self):
        cfg = MCPServerConfig(
            name="test", command="python",
            allowed_domains={"example.com"},
        )
        policy = ToolPolicy(allowed_domains={"evil.com"})
        issues = validate_tool_under_server(policy, cfg)
        assert any(i.code == "MCP103" for i in issues)

    def test_tool_within_server_ceiling_passes(self):
        cfg = MCPServerConfig(
            name="test", command="python",
            max_risk="network",
            allowed_capabilities={"network.public_http"},
            allowed_domains={"api.example.com"},
        )
        policy = ToolPolicy(
            risk="network",
            capabilities={"network.public_http"},
            allowed_domains={"api.example.com"},
        )
        issues = validate_tool_under_server(policy, cfg)
        assert not any(i.severity == "error" for i in issues)


class TestFrozenTool:
    """Tool freezing and mutation detection."""

    def test_frozen_tool_closes_schema(self):
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        ft = FrozenTool.from_discovery("t", "desc", schema)
        assert "additionalProperties" in ft.schema
        assert ft.schema["additionalProperties"] is False

    def test_same_schema_same_hash(self):
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        ft1 = FrozenTool.from_discovery("t", "desc", schema)
        ft2 = FrozenTool.from_discovery("t", "desc", schema)
        assert ft1.schema_hash == ft2.schema_hash

    def test_different_schema_different_hash(self):
        ft1 = FrozenTool.from_discovery("t", "desc", {"type": "object", "properties": {"x": {"type": "string"}}})
        ft2 = FrozenTool.from_discovery("t", "desc", {"type": "object", "properties": {"y": {"type": "integer"}}})
        assert ft1.schema_hash != ft2.schema_hash


class TestMutationDetection:
    """detect_mutation — tool list and schema change detection."""

    def test_no_mutation(self):
        gateway = MCPGateway(MCPServerConfig(name="test", command="python"))
        tools = [("echo", "desc", {"type": "object", "properties": {}})]
        gateway._freeze_tools(tools)
        issues = gateway.detect_mutation(tools)
        assert len(issues) == 0

    def test_tool_added_detected(self):
        gateway = MCPGateway(MCPServerConfig(name="test", command="python"))
        tools = [("echo", "desc", {"type": "object", "properties": {}})]
        gateway._freeze_tools(tools)
        new_tools = tools + [("new_tool", "desc", {"type": "object", "properties": {}})]
        issues = gateway.detect_mutation(new_tools)
        assert any("Tool added: new_tool" in i for i in issues)

    def test_tool_removed_detected(self):
        gateway = MCPGateway(MCPServerConfig(name="test", command="python"))
        tools = [("echo", "desc", {"type": "object", "properties": {}})]
        gateway._freeze_tools(tools)
        issues = gateway.detect_mutation([])
        assert any("Tool removed: echo" in i for i in issues)

    def test_schema_change_detected(self):
        gateway = MCPGateway(MCPServerConfig(name="test", command="python"))
        tools = [("echo", "desc", {"type": "object", "properties": {"msg": {"type": "string"}}})]
        gateway._freeze_tools(tools)
        changed = [("echo", "desc", {"type": "object", "properties": {"new_field": {"type": "integer"}}})]
        issues = gateway.detect_mutation(changed)
        assert any("Schema changed" in i for i in issues)


class TestGatewayAudit:
    """GatewayAuditRecord and audit trail."""

    def test_audit_record_fields(self):
        record = GatewayAuditRecord(
            server_name="test", tool_name="echo", call_id="1",
            request_hash="abc", response_hash="def",
            latency_ms=100, ok=True, command_digest="sha256:xyz",
        )
        assert record.server_name == "test"
        assert record.command_digest == "sha256:xyz"

    def test_gateway_audit_trail_starts_empty(self):
        gateway = MCPGateway(MCPServerConfig(name="test", command="python"))
        assert len(gateway.audit_trail) == 0

    def test_execute_not_connected(self):
        gateway = MCPGateway(MCPServerConfig(name="test", command="python"))
        from seekflow.types import ToolCall
        result = gateway.execute(ToolCall(name="echo", arguments={}))
        assert not result.ok
        assert "not connected" in result.error
