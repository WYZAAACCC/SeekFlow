"""Test MCP executor security — naming, env isolation, policy enforcement."""
import pytest
from seekflow.mcp.config import MCPServerConfig, MCPTrustLevel


def test_mcp_config_default_env_empty():
    """MCP server env should default to empty dict for security."""
    config = MCPServerConfig(name="test", command="python", args=["-m", "test"])
    assert config.env == {}


def test_mcp_config_uses_profiles():
    profiles = [
        MCPServerConfig(name="s1", command="python", args=["-m", "server1"]),
        MCPServerConfig(name="s2", command="python", args=["-m", "server2"]),
    ]
    assert all(p.name for p in profiles)


def test_mcp_config_trust_levels():
    profile = MCPServerConfig(name="test", command="python", args=["-m", "test"])
    assert profile.trust_level in MCPTrustLevel


def test_mcp_server_config_stdio():
    config = MCPServerConfig.stdio(
        name="test-server",
        command="python",
        args=["-m", "test_module"],
    )
    assert config.name == "test-server"
    assert config.command == "python"


def test_mcp_untrusted_has_restrictions():
    config = MCPServerConfig(
        name="untrusted",
        command="python",
        args=["-m", "malicious"],
        trust_level=MCPTrustLevel.UNTRUSTED,
        max_risk="read",
    )
    assert config.trust_level == MCPTrustLevel.UNTRUSTED
    assert config.max_risk == "read"
