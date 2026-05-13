"""Export tools in OpenAI-compatible format."""
from __future__ import annotations

from seekflow.tools.registry import ToolRegistry


def to_openai_tools(registry: ToolRegistry, strict: bool = False) -> list[dict]:
    """Export all registered tools in OpenAI-compatible tools format.

    This is identical to the DeepSeek format since DeepSeek uses the
    OpenAI-compatible function calling schema.
    """
    return registry.to_deepseek_tools(strict=strict)
