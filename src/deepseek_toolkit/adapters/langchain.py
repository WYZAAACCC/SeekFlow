"""Minimal LangChain schema export — no hard dependency on langchain."""
from __future__ import annotations

from deepseek_toolkit.tools.registry import ToolRegistry


def export_langchain_tool_schemas(registry: ToolRegistry) -> list[dict]:
    """Export tools in a LangChain-compatible format.

    Returns a list of schema dicts with 'name', 'description',
    and 'parameters' keys. Does not require LangChain to be installed.
    """
    schemas: list[dict] = []
    for td in registry.list():
        schemas.append({
            "name": td.name,
            "description": td.description,
            "parameters": td.parameters,
        })
    return schemas
