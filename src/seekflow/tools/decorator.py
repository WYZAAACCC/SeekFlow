"""@tool decorator for defining DeepSeek-compatible tools."""
from collections.abc import Callable
from typing import Any

from seekflow.tools.schema import function_to_parameters
from seekflow.types import ToolDefinition


def tool(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    cache: bool = True,
    keep_fields: list[str] | None = None,
    max_retries: int = 0,
    retry_delay: float = 1.0,
    sanitize: bool = True,
    trusted: bool = False,
) -> ToolDefinition:
    """Decorator that converts a Python function into a ToolDefinition.

    Args:
        sanitize: If False, skips prompt-injection filtering on this tool's
                  output. Use for high-trust tools (e.g., read_file) where
                  the content is explicitly requested by the user.

    Usage:
        @tool
        def add(a: int, b: int) -> int:
            '''Add two numbers.'''
            return a + b

        @tool(sanitize=False)
        def read_file(path: str) -> str:
            '''Read a file.'''
            return Path(path).read_text()
    """
    if func is None:
        def decorator(fn: Callable[..., Any]) -> ToolDefinition:
            return _make_tool_definition(fn, name=name, description=description,
                                         cache=cache, keep_fields=keep_fields,
                                         max_retries=max_retries, retry_delay=retry_delay,
                                         sanitize=sanitize, trusted=trusted)
        return decorator

    return _make_tool_definition(func, name=name, description=description,
                                 cache=cache, keep_fields=keep_fields,
                                 max_retries=max_retries, retry_delay=retry_delay,
                                 sanitize=sanitize, trusted=trusted)


def _make_tool_definition(
    fn: Callable[..., Any],
    name: str | None = None,
    description: str | None = None,
    cache: bool = True,
    keep_fields: list[str] | None = None,
    max_retries: int = 0,
    retry_delay: float = 1.0,
    sanitize: bool = True,
    trusted: bool = False,
) -> ToolDefinition:
    tool_name = name or fn.__name__
    tool_desc = description or (fn.__doc__ or "").strip()
    metadata: dict = {"cache": cache, "max_retries": max_retries,
                      "retry_delay": retry_delay, "sanitize": sanitize,
                      "trusted": trusted}
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
