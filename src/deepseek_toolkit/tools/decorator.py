"""@tool decorator for defining DeepSeek-compatible tools."""
from collections.abc import Callable
from typing import Any

from deepseek_toolkit.tools.schema import function_to_parameters
from deepseek_toolkit.types import ToolDefinition


def tool(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    cache: bool = True,
    keep_fields: list[str] | None = None,
    max_retries: int = 0,
    retry_delay: float = 1.0,
) -> ToolDefinition:
    """Decorator that converts a Python function into a ToolDefinition.

    Usage:
        @tool
        def add(a: int, b: int) -> int:
            '''Add two numbers.'''
            return a + b

        @tool(name="weather", description="Query weather")
        def get_weather(city: str) -> str:
            return f"{city}: sunny"

        @tool(cache=False)
        def non_deterministic() -> int:
            return random.randint(1, 100)

        @tool(keep_fields=["temperature"])
        def weather(city: str) -> str:
            return '{"temperature": 25, "wind": 10}'
    """
    if func is None:
        # Called with parentheses
        def decorator(fn: Callable[..., Any]) -> ToolDefinition:
            return _make_tool_definition(fn, name=name, description=description,
                                         cache=cache, keep_fields=keep_fields,
                                         max_retries=max_retries, retry_delay=retry_delay)
        return decorator

    # Called without parentheses
    return _make_tool_definition(func, name=name, description=description,
                                 cache=cache, keep_fields=keep_fields,
                                 max_retries=max_retries, retry_delay=retry_delay)


def _make_tool_definition(
    fn: Callable[..., Any],
    name: str | None = None,
    description: str | None = None,
    cache: bool = True,
    keep_fields: list[str] | None = None,
    max_retries: int = 0,
    retry_delay: float = 1.0,
) -> ToolDefinition:
    tool_name = name or fn.__name__
    tool_desc = description or (fn.__doc__ or "").strip()
    metadata: dict = {"cache": cache, "max_retries": max_retries, "retry_delay": retry_delay}
    if keep_fields is not None:
        metadata["keep_fields"] = keep_fields
    else:
        metadata["keep_fields"] = None
    return ToolDefinition(
        name=tool_name,
        description=tool_desc,
        parameters=function_to_parameters(fn),
        func=fn,
        metadata=metadata,
    )
