"""Minimal PydanticAI schema export — no hard dependency on pydantic_ai."""
from __future__ import annotations

from deepseek_toolkit.tools.registry import ToolRegistry


def export_pydantic_ai_tool_schemas(registry: ToolRegistry) -> list[dict]:
    """Export tools in a format compatible with PydanticAI.

    Returns a list of schema dicts with 'name', 'description',
    and 'parameters' keys. Does not require PydanticAI to be installed.
    """
    schemas: list[dict] = []
    for td in registry.list():
        schemas.append({
            "name": td.name,
            "description": td.description,
            "parameters": td.parameters,
        })
    return schemas
