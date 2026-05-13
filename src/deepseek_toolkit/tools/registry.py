"""Tool registry for managing registered tools."""
from __future__ import annotations

from collections.abc import Callable

from deepseek_toolkit.errors import ToolSchemaError
from deepseek_toolkit.types import ToolDefinition


class ToolRegistry:
    """Registry for local and MCP tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: Callable | ToolDefinition) -> ToolDefinition:
        """Register a tool. Accepts either a callable (auto-wrapped with @tool)
        or a pre-built ToolDefinition."""
        from deepseek_toolkit.tools.decorator import _make_tool_definition

        if not isinstance(tool, ToolDefinition):
            td = _make_tool_definition(tool)
        else:
            td = tool

        if td.name in self._tools:
            raise ToolSchemaError(f"Tool '{td.name}' is already registered")
        self._tools[td.name] = td
        return td

    def get(self, name: str) -> ToolDefinition:
        """Get a tool by name."""
        return self._tools[name]

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def list(self) -> list[ToolDefinition]:
        """List all registered tools."""
        return list(self._tools.values())

    def unregister(self, name: str) -> bool:
        """Remove a tool by name. Returns True if the tool was removed."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def get_by_source(self, source: str) -> list[ToolDefinition]:
        """List all tools from a given source ('local' or MCP server name)."""
        return [td for td in self._tools.values() if td.source == source]

    def to_deepseek_tools(self, strict: bool = False) -> list[dict]:
        """Export all tools in DeepSeek-compatible format.

        Tools are sorted by name for deterministic JSON serialization.
        This is CRITICAL for prompt cache stability — non-deterministic
        key ordering invalidates the DeepSeek byte-prefix cache.
        """
        tools = [
            {
                "type": "function",
                "function": {
                    "name": td.name,
                    "description": td.description,
                    "parameters": td.parameters,
                },
            }
            for td in sorted(self._tools.values(), key=lambda t: t.name)
        ]
        return tools
