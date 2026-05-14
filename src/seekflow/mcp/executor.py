"""MCP tool executor — connection, discovery, registration, and execution."""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
from typing import Any

from seekflow.mcp.config import MCPServerConfig, MCPTrustLevel
from seekflow.mcp.adapter import mcp_tool_to_deepseek_tool
from seekflow.types import ToolCall, ToolExecutionResult

logger = logging.getLogger("seekflow.mcp")


class MCPToolExecutor:
    """Manages MCP server connections and tool execution.

    Two transport paths:
    1. mcp SDK available → async stdio sessions (preferred)
    2. mcp SDK unavailable → subprocess-based manual JSON-RPC (fallback)

    Usage:
        executor = MCPToolExecutor([MCPServerConfig.stdio(...)])
        executor.connect_and_register(registry)  # discover + register wrappers
        result = executor.execute_sync(tool_call)  # execute a tool
        executor.disconnect()  # clean up
    """

    def __init__(self, configs: list[MCPServerConfig]) -> None:
        self._configs = {c.name: c for c in configs}
        # server_name → (read, write, session) | subprocess.Popen
        self._sessions: dict[str, Any] = {}
        self._has_sdk = False
        self.connection_errors: dict[str, str] = {}

    # ── Connection & Discovery ──────────────────────────────────────

    def connect_and_register(self, registry) -> list[str]:
        """Connect to all configured MCP servers, discover tools,
        and register functional wrappers in the given ToolRegistry.

        Returns list of registered tool names (server.tool_name).
        """
        if not self._configs:
            return []

        self._has_sdk = False
        try:
            from mcp.client.stdio import stdio_client, StdioServerParameters
            from mcp import ClientSession
            self._has_sdk = True
        except ImportError:
            pass

        all_tools: list[str] = []
        for cfg in self._configs.values():
            try:
                if self._has_sdk:
                    tools = asyncio.run(
                        asyncio.wait_for(self._discover_via_sdk(cfg), timeout=cfg.startup_timeout)
                    )
                else:
                    tools = self._discover_via_manual(cfg)
            except asyncio.TimeoutError:
                msg = f"MCP server '{cfg.name}' startup timed out after {cfg.startup_timeout}s"
                logger.error(msg)
                self.connection_errors[cfg.name] = msg
                if cfg.fail_fast:
                    raise TimeoutError(msg) from None
                continue
            except Exception as e:
                msg = f"MCP server '{cfg.name}' connection failed: {e}"
                logger.error(msg)
                self.connection_errors[cfg.name] = msg
                if cfg.fail_fast:
                    raise
                continue

            for name, desc, schema in tools:
                full_name = f"{cfg.name}__{name}"
                wrapper = self._make_wrapper(cfg.name, name)
                from seekflow.types import ToolDefinition
                mt_obj = type("MCPTool", (), {
                    "name": name,
                    "description": desc or "",
                    "inputSchema": schema or {},
                })()
                ds_tool = mcp_tool_to_deepseek_tool(cfg.name, mt_obj)
                # Derive ToolPolicy from MCP server config
                from seekflow.types import ToolPolicy
                policy = ToolPolicy(
                    capabilities=cfg.allowed_capabilities or set(),
                    risk=cfg.max_risk,
                    allowed_domains=cfg.allowed_domains,
                    workspace_root=cfg.workspace_root,
                    requires_approval=cfg.requires_approval,
                    parallel_safe=(cfg.max_risk == "read"),
                )

                td = ToolDefinition(
                    name=full_name,
                    description=desc or "",
                    parameters=ds_tool["function"]["parameters"],
                    func=wrapper,
                    source=cfg.name,
                    policy=policy,
                )
                registry.register(td)
                all_tools.append(full_name)
        return all_tools

    async def _discover_via_sdk(self, cfg: MCPServerConfig) -> list:
        from mcp.client.stdio import stdio_client, StdioServerParameters
        from mcp import ClientSession
        params = StdioServerParameters(command=cfg.command, args=cfg.args)
        read, write = await stdio_client(params).__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()
        result = await session.list_tools()
        self._sessions[cfg.name] = (read, write, session)
        return [(t.name, t.description, t.inputSchema) for t in result.tools]

    def _discover_via_manual(self, cfg: MCPServerConfig) -> list:
        proc = subprocess.Popen(
            [cfg.command] + cfg.args,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, shell=False,
        )

        def _rpc(method, params=None, rid=1):
            req = {"jsonrpc": "2.0", "id": rid, "method": method,
                   "params": params or {}}
            proc.stdin.write((json.dumps(req) + "\n").encode())
            proc.stdin.flush()
            line = proc.stdout.readline().decode().strip()
            return json.loads(line) if line else None

        _rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "seekflow", "version": "3.0.0"},
        })
        proc.stdin.write((json.dumps({
            "jsonrpc": "2.0", "method": "notifications/initialized",
        }) + "\n").encode())
        proc.stdin.flush()
        resp = _rpc("tools/list")
        self._sessions[cfg.name] = proc
        if resp and "result" in resp:
            return [(t["name"], t.get("description", ""),
                     t.get("inputSchema", {}))
                    for t in resp["result"].get("tools", [])]
        return []

    # ── Wrapper Factory ─────────────────────────────────────────────

    def _make_wrapper(self, server_name: str, tool_name: str):
        """Create a callable that routes tool execution to the correct MCP server."""
        executor_ref = self

        def _mcp_exec(**kwargs):
            session_or_proc = executor_ref._sessions.get(server_name)
            if session_or_proc is None:
                return json.dumps({
                    "error": f"MCP server '{server_name}' is not connected",
                })
            if isinstance(session_or_proc, tuple):
                # SDK path: (read, write, session)
                _, _, session = session_or_proc

                async def _call():
                    result = await session.call_tool(tool_name, arguments=kwargs)
                    if result.isError:
                        return json.dumps({"error": str(result.content)})
                    return json.dumps({
                        "content": [
                            c.text if hasattr(c, "text")
                            else c.get("text", str(c))
                            for c in (result.content or [])
                        ],
                    })

                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop and loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        return pool.submit(asyncio.run, _call()).result()
                return asyncio.run(_call())
            else:
                # Manual subprocess path
                proc = session_or_proc
                req = json.dumps({
                    "jsonrpc": "2.0", "id": 200,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": kwargs},
                }) + "\n"
                proc.stdin.write(req.encode())
                proc.stdin.flush()
                resp_line = proc.stdout.readline().decode().strip()
                if resp_line:
                    resp = json.loads(resp_line)
                    result_data = resp.get("result", {})
                    content = result_data.get("content", [{}])
                    return " ".join(
                        c.get("text", "") for c in content
                        if isinstance(c, dict)
                    ) or str(result_data)
                return ""

        _mcp_exec.__name__ = f"{server_name}.{tool_name}"
        return _mcp_exec

    # ── Tool Execution ──────────────────────────────────────────────

    async def execute(self, tool_call: ToolCall) -> ToolExecutionResult:
        """Execute a tool call on the appropriate MCP server (async)."""
        start = time.time()
        server_name, tool_name = self._parse_tool_name(tool_call.name)

        session_or_proc = self._sessions.get(server_name)
        if session_or_proc is None:
            elapsed = int((time.time() - start) * 1000)
            return ToolExecutionResult(
                tool_call_id=tool_call.id, name=tool_call.name,
                arguments=tool_call.arguments, ok=False,
                error=f"MCP server '{server_name}' not connected",
                elapsed_ms=elapsed,
            )

        # Resolve session: tuple (read, write, session) → session; or direct session object
        session = session_or_proc
        if isinstance(session_or_proc, tuple):
            session = session_or_proc[2]

        if hasattr(session, "call_tool"):
            # SDK path or mock session with call_tool
            args: dict[str, Any] = tool_call.arguments
            try:
                result = await session.call_tool(tool_name, arguments=args)
                elapsed = int((time.time() - start) * 1000)
                if result.isError:
                    return ToolExecutionResult(
                        tool_call_id=tool_call.id, name=tool_call.name,
                        arguments=args, ok=False,
                        error=_extract_text_content(result.content) or "MCP tool error",
                        elapsed_ms=elapsed,
                    )
                return ToolExecutionResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    arguments=args, ok=True,
                    result=result.structuredContent or _extract_text_content(result.content),
                    elapsed_ms=elapsed,
                )
            except Exception as e:
                return ToolExecutionResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    arguments=args, ok=False, error=str(e),
                    elapsed_ms=int((time.time() - start) * 1000),
                )
        else:
            # Manual subprocess path — delegate to the registered wrapper
            # which already handles subprocess communication
            proc = session_or_proc
            args: dict[str, Any] = tool_call.arguments
            try:
                req = json.dumps({
                    "jsonrpc": "2.0", "id": 200,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": args},
                }) + "\n"
                proc.stdin.write(req.encode())
                proc.stdin.flush()
                resp_line = proc.stdout.readline().decode().strip()
                elapsed = int((time.time() - start) * 1000)
                if resp_line:
                    resp = json.loads(resp_line)
                    result_data = resp.get("result", {})
                    is_error = result_data.get("isError", False)
                    content = result_data.get("content", [{}])
                    text = " ".join(
                        c.get("text", "") for c in content if isinstance(c, dict)
                    ) or str(result_data)
                    return ToolExecutionResult(
                        tool_call_id=tool_call.id, name=tool_call.name,
                        arguments=args, ok=not is_error,
                        result=text, elapsed_ms=elapsed,
                    )
                return ToolExecutionResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    arguments=args, ok=False,
                    error="No response from MCP server",
                    elapsed_ms=elapsed,
                )
            except Exception as e:
                return ToolExecutionResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    arguments=args, ok=False, error=str(e),
                    elapsed_ms=int((time.time() - start) * 1000),
                )

    def execute_sync(self, tool_call: ToolCall) -> ToolExecutionResult:
        """Synchronous wrapper around execute()."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, self.execute(tool_call)).result()
        return asyncio.run(self.execute(tool_call))

    # ── Cleanup ─────────────────────────────────────────────────────

    def disconnect(self) -> None:
        """Close all MCP server connections."""
        for name, session_or_proc in list(self._sessions.items()):
            try:
                if isinstance(session_or_proc, tuple):
                    read, write, session = session_or_proc

                    async def _close():
                        try:
                            await session.__aexit__(None, None, None)
                        except Exception:
                            pass
                        try:
                            await write.aclose()
                        except Exception:
                            pass

                    asyncio.run(_close())
                else:
                    proc = session_or_proc
                    try:
                        proc.stdin.close()
                    except Exception:
                        pass
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
            except Exception:
                pass
        self._sessions.clear()

    # ── Helpers ─────────────────────────────────────────────────────

    def _parse_tool_name(self, full_name: str) -> tuple[str, str]:
        parts = full_name.split(".", 1)
        if len(parts) == 2:
            return parts[0], parts[1]
        return "", full_name


def _extract_text_content(content: list) -> str:
    if not content:
        return ""
    parts = []
    for block in content:
        if hasattr(block, "text"):
            parts.append(block.text)
        elif isinstance(block, dict) and "text" in block:
            parts.append(block["text"])
    return "\n".join(parts)
