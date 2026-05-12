"""MCP tool executor — calls MCP servers to execute tools."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from deepseek_toolkit.mcp.config import MCPServerConfig
from deepseek_toolkit.types import ToolCall, ToolExecutionResult


class MCPToolExecutor:
    """Executes tool calls against MCP servers.

    Manages MCP sessions indexed by server name.
    """

    def __init__(self, configs: list[MCPServerConfig]) -> None:
        self._configs = {c.name: c for c in configs}
        self._sessions: dict[str, Any] = {}

    async def execute(self, tool_call: ToolCall) -> ToolExecutionResult:
        """Execute a tool call on the appropriate MCP server (async)."""
        start = time.time()

        server_name, tool_name = self._parse_tool_name(tool_call.name)

        session = self._sessions.get(server_name)
        if session is None:
            elapsed = int((time.time() - start) * 1000)
            return ToolExecutionResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                arguments=tool_call.arguments if isinstance(tool_call.arguments, dict)
                else {},
                ok=False,
                error=f"MCP server '{server_name}' not connected",
                elapsed_ms=elapsed,
            )

        try:
            result = await session.call_tool(tool_name, arguments=tool_call.arguments)

            elapsed = int((time.time() - start) * 1000)

            if result.isError:
                error_text = _extract_text_content(result.content)
                return ToolExecutionResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    arguments=tool_call.arguments if isinstance(tool_call.arguments, dict)
                    else {},
                    ok=False,
                    error=error_text or "MCP tool returned an error",
                    elapsed_ms=elapsed,
                )

            return ToolExecutionResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                arguments=tool_call.arguments if isinstance(tool_call.arguments, dict)
                else {},
                ok=True,
                result=result.structuredContent or _extract_text_content(result.content),
                elapsed_ms=elapsed,
            )

        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            return ToolExecutionResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                arguments=tool_call.arguments if isinstance(tool_call.arguments, dict)
                else {},
                ok=False,
                error=str(e),
                elapsed_ms=elapsed,
            )

    def execute_sync(self, tool_call: ToolCall) -> ToolExecutionResult:
        """Synchronous wrapper around execute()."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # Already in an event loop — use a nested approach
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self.execute(tool_call))
                return future.result()
        else:
            return asyncio.run(self.execute(tool_call))

    def _parse_tool_name(self, full_name: str) -> tuple[str, str]:
        """Split 'server.tool_name' into ('server', 'tool_name')."""
        parts = full_name.split(".", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return "", full_name


def _extract_text_content(content: list) -> str:
    """Extract text from MCP content blocks."""
    if not content:
        return ""
    parts = []
    for block in content:
        if hasattr(block, "text"):
            parts.append(block.text)
        elif isinstance(block, dict) and "text" in block:
            parts.append(block["text"])
    return "\n".join(parts)
