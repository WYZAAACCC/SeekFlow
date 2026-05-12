"""Tests for MCPServerConfig."""

from deepseek_toolkit.mcp.config import MCPServerConfig


class TestMCPServerConfig:
    def test_default_transport(self):
        cfg = MCPServerConfig(name="fs", command="npx", args=["-y", "server"])
        assert cfg.transport == "stdio"
        assert cfg.name == "fs"
        assert cfg.command == "npx"
        assert cfg.args == ["-y", "server"]
        assert cfg.env == {}

    def test_stdio_factory_method(self):
        cfg = MCPServerConfig.stdio(
            name="fs",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "."],
            env={"NODE_ENV": "production"},
        )
        assert cfg.name == "fs"
        assert cfg.transport == "stdio"
        assert cfg.command == "npx"
        assert cfg.args == ["-y", "@modelcontextprotocol/server-filesystem", "."]
        assert cfg.env == {"NODE_ENV": "production"}

    def test_model_dump(self):
        cfg = MCPServerConfig.stdio(name="test", command="python", args=["script.py"])
        d = cfg.model_dump()
        assert d["name"] == "test"
        assert d["transport"] == "stdio"
        assert d["command"] == "python"
        assert d["args"] == ["script.py"]
        assert d["env"] == {}

    def test_to_stdio_params(self):
        """Convert to mcp StdioServerParameters."""
        cfg = MCPServerConfig.stdio(
            name="fs",
            command="npx",
            args=["-y", "server-filesystem"],
        )
        params = cfg.to_stdio_params()
        assert params.command == "npx"
        assert params.args == ["-y", "server-filesystem"]
        assert params.env is None
