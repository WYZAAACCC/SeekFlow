"""MCPGatewayRunner — Lv3 MCP tool execution without Python callable.

MCP tools are NOT Python functions. They run via the MCPGateway's
long-lived server session. This runner bridges the ToolExecutor's
runner interface to the gateway's execute() method.
"""
from __future__ import annotations

import uuid
from typing import Any

from seekflow.tools.runners import ToolRunResult
from seekflow.types import ToolCall, ToolDefinition


class MCPGatewayRunner:
    """Runner for MCP tools registered through MCPGateway.

    MCP tools have func=None in their ToolDefinition. The actual execution
    happens through the MCPGateway — a long-lived server session, not a
    per-call container.
    """

    name = "mcp_gateway"

    def run(
        self,
        tool_def: ToolDefinition,
        arguments: dict,
        timeout_s: float,
        *,
        max_output_bytes: int = 100_000,
        **kwargs: Any,
    ) -> ToolRunResult:
        """Execute an MCP tool through its gateway.

        The gateway reference is stored in tool_def.metadata:
        - _mcp_gateway_id: server config name
        - _mcp_tool_name: tool name within the server
        """
        import time as _time

        gateway_id = (tool_def.metadata or {}).get("_mcp_gateway_id")
        mcp_tool_name = (tool_def.metadata or {}).get("_mcp_tool_name")

        if not gateway_id or not mcp_tool_name:
            return ToolRunResult(
                ok=False,
                error="MCP tool metadata missing _mcp_gateway_id or _mcp_tool_name",
                runner_name=self.name,
            )

        # Gateway lookup is deferred to avoid circular imports.
        # In production, the gateway registry is managed by the runtime.
        from seekflow.mcp.gateway import _gateway_registry
        gateway = _gateway_registry.get(gateway_id)
        if gateway is None:
            return ToolRunResult(
                ok=False,
                error=f"MCP gateway '{gateway_id}' not found",
                runner_name=self.name,
            )

        # Verify frozen tools before execution (mutation detection)
        try:
            gateway.verify_frozen()
        except Exception as e:
            return ToolRunResult(
                ok=False,
                error=f"MCP tool mutation detected: {e}",
                runner_name=self.name,
            )

        start = _time.monotonic()
        result = gateway.execute(
            ToolCall(
                id=str(uuid.uuid4()),
                name=mcp_tool_name,
                arguments=arguments,
            )
        )
        elapsed = int((_time.monotonic() - start) * 1000)

        if not result.ok:
            return ToolRunResult(
                ok=False,
                error=result.error or "MCP tool execution failed",
                runner_name=self.name,
                elapsed_ms=elapsed,
            )

        # Bound the output
        from seekflow.tools.limits import serialize_bounded
        bounded, truncated = serialize_bounded(
            result.result if result.result is not None else "",
            max_output_bytes,
        )

        return ToolRunResult(
            ok=True,
            result=bounded,
            runner_name=self.name,
            elapsed_ms=elapsed,
            output_truncated=truncated,
        )
