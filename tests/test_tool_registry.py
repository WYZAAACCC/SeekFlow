"""Tests for ToolRegistry."""
import pytest
from deepseek_toolkit.tools import ToolRegistry
from deepseek_toolkit.errors import ToolSchemaError
from deepseek_toolkit.types import ToolDefinition


class TestToolRegistry:
    def test_register_tool_definition(self):
        reg = ToolRegistry()
        td = ToolDefinition(name="add", description="Add", parameters={"type": "object"})
        result = reg.register(td)
        assert result is td
        assert reg.has("add")

    def test_register_callable(self):
        reg = ToolRegistry()

        def add(a: int, b: int) -> int:
            return a + b

        td = reg.register(add)
        assert isinstance(td, ToolDefinition)
        assert td.name == "add"

    def test_register_duplicate_raises(self):
        reg = ToolRegistry()

        def add(a: int, b: int) -> int:
            return a + b

        reg.register(add)
        with pytest.raises(ToolSchemaError, match="already registered"):
            reg.register(add)

    def test_get_existing_tool(self):
        reg = ToolRegistry()
        td = ToolDefinition(name="echo", description="Echo", parameters={"type": "object"})
        reg.register(td)
        assert reg.get("echo") is td

    def test_get_missing_raises_key_error(self):
        reg = ToolRegistry()
        with pytest.raises(KeyError):
            reg.get("nonexistent")

    def test_has_returns_false_for_missing(self):
        reg = ToolRegistry()
        assert not reg.has("nonexistent")

    def test_list_returns_all(self):
        reg = ToolRegistry()
        td1 = ToolDefinition(name="a", description="A", parameters={})
        td2 = ToolDefinition(name="b", description="B", parameters={})
        reg.register(td1)
        reg.register(td2)
        tools = reg.list()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert names == {"a", "b"}

    def test_to_deepseek_tools_format(self):
        reg = ToolRegistry()
        td = ToolDefinition(
            name="add",
            description="Add two numbers",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                },
                "required": ["a", "b"],
            },
        )
        reg.register(td)
        tools = reg.to_deepseek_tools()
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "add"
        assert tools[0]["function"]["parameters"]["type"] == "object"

    def test_registry_starts_empty(self):
        reg = ToolRegistry()
        assert reg.list() == []
