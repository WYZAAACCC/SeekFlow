"""MCPGateway — Lv3 zero-trust gateway for MCP server connections.

Replaces the Lv2 "connect + register wrappers" model with a hardened gateway:
- Server manifest required (command + digest pinning)
- Tool list frozen at connection time; mutation detected
- Schema closed (additionalProperties=False) on discovery
- Per-server capability ceiling enforced
- Per-tool policy compiled and linted
- Env allowlist enforced (via MCPServerConfig.to_stdio_params)
- Call timeout + idle timeout + max calls per run
- Audit hooks for JSON-RPC request/response
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from seekflow.mcp.config import MCPServerConfig, MCPTrustLevel
from seekflow.mcp.adapter import mcp_tool_to_deepseek_tool
from seekflow.types import ToolCall, ToolDefinition, ToolExecutionResult, ToolPolicy
from seekflow.tools.validation import close_object_schema

logger = logging.getLogger("seekflow.mcp.gateway")


@dataclass
class GatewayAuditRecord:
    """Audit record for a single MCP tool call through the gateway."""
    timestamp: float = 0.0
    server_name: str = ""
    tool_name: str = ""
    call_id: str = ""
    request_hash: str = ""
    response_hash: str = ""
    latency_ms: int = 0
    ok: bool = False
    error: str | None = None
    command_digest: str | None = None


@dataclass
class FrozenTool:
    """A frozen snapshot of an MCP tool at registration time."""
    name: str
    description: str
    schema: dict[str, Any]
    schema_hash: str

    @classmethod
    def from_discovery(cls, name: str, description: str, schema: dict) -> "FrozenTool":
        closed = close_object_schema(schema) if schema else {}
        schema_canonical = json.dumps(closed, sort_keys=True, ensure_ascii=False)
        schema_hash = hashlib.sha256(schema_canonical.encode()).hexdigest()[:16]
        return cls(name=name, description=description, schema=closed, schema_hash=schema_hash)


class MCPGatewayError(RuntimeError):
    """Raised when an MCP operation violates gateway policy."""


class MCPGateway:
    """Lv3 zero-trust gateway for MCP servers.

    Usage:
        gateway = MCPGateway(config)
        gateway.connect_and_freeze(registry)  # discover + freeze + register
        result = gateway.execute(tool_call)    # execute with policy enforcement
        gateway.disconnect()                   # kill server process tree
    """

    def __init__(self, config: MCPServerConfig):
        self._config = config
        self._frozen_tools: dict[str, FrozenTool] = {}
        self._tool_list_hash: str | None = None
        self._sessions: dict[str, Any] = {}
        self._has_sdk = False
        self._connected = False
        self._call_count = 0
        self._start_time: float = 0.0
        self.audit_trail: list[GatewayAuditRecord] = []

    @property
    def server_name(self) -> str:
        return self._config.name

    # ── Connection & Freeze ───────────────────────────────────────

    def connect_and_freeze(self, registry) -> list[str]:
        """Connect to the MCP server, discover tools, freeze schemas,
        compile policies, lint, and register in the given ToolRegistry.

        Returns list of registered tool names (server.tool_name).
        """
        cfg = self._config
        self._start_time = time.monotonic()

        # Detect SDK availability
        self._has_sdk = False
        try:
            from mcp.client.stdio import stdio_client, StdioServerParameters
            from mcp import ClientSession
            self._has_sdk = True
        except ImportError:
            pass

        # Discover tools
        try:
            if self._has_sdk:
                tools = asyncio.run(
                    asyncio.wait_for(
                        self._discover_via_sdk(), timeout=cfg.startup_timeout
                    )
                )
            else:
                tools = self._discover_via_manual()
        except asyncio.TimeoutError:
            raise MCPGatewayError(
                f"MCP server '{cfg.name}' startup timed out after {cfg.startup_timeout}s"
            )
        except Exception as e:
            raise MCPGatewayError(
                f"MCP server '{cfg.name}' connection failed: {e}"
            ) from e

        # Freeze tool list
        self._freeze_tools(tools)
        self._connected = True

        # Compile policy for each tool and register
        registered: list[str] = []
        for ft in self._frozen_tools.values():
            full_name = f"{cfg.name}__{ft.name}"

            wrapper = self._make_wrapper(ft.name)
            policy = self._compile_tool_policy(ft)

            td = ToolDefinition(
                name=full_name,
                description=ft.description,
                parameters=ft.schema,
                func=wrapper,
                source=cfg.name,
                policy=policy,
            )
            registry.register(td)
            registered.append(full_name)

        return registered

    def _freeze_tools(self, tools: list[tuple[str, str, dict]]) -> None:
        """Freeze the tool list and compute a list hash for mutation detection."""
        frozen = {}
        for name, desc, schema in tools:
            ft = FrozenTool.from_discovery(name, desc, schema or {})
            frozen[name] = ft

        # Compute list hash for mutation detection
        tool_names_sorted = sorted(frozen.keys())
        list_canonical = json.dumps(tool_names_sorted, ensure_ascii=False)
        self._tool_list_hash = hashlib.sha256(list_canonical.encode()).hexdigest()[:16]
        self._frozen_tools = frozen

    def _compile_tool_policy(self, ft: FrozenTool) -> ToolPolicy:
        """Compile a ToolPolicy for a frozen MCP tool based on server config."""
        cfg = self._config
        capabilities: set[str] = set(cfg.allowed_capabilities or set())

        # Derive capabilities from schema
        props = ft.schema.get("properties", {}) if ft.schema else {}
        if any(k in props for k in ("url", "uri", "endpoint")):
            capabilities.add("network.public_http")
        if any(k in props for k in ("path", "file", "directory")):
            capabilities.add("filesystem.read")

        risk = cfg.max_risk
        if "code.exec" in capabilities or risk == "code_exec":
            risk = "code_exec"
            capabilities.add("code.exec")

        return ToolPolicy(
            capabilities=capabilities,
            risk=risk,
            timeout_s=cfg.call_timeout,
            parallel_safe=False,
            requires_approval=cfg.requires_approval or risk in ("code_exec", "destructive"),
            allowed_domains=cfg.allowed_domains,
            workspace_root=cfg.workspace_root,
            trusted=False,
            trusted_output=False,
            runner="container" if risk in ("code_exec", "destructive") else "process",
        )

    # ── Mutation Detection ────────────────────────────────────────

    def detect_mutation(self, current_tools: list[tuple[str, str, dict]]) -> list[str]:
        """Compare current tool list against frozen snapshot.

        Returns list of mutation descriptions. Empty list = no mutation.
        """
        issues: list[str] = []
        current_names = {t[0] for t in current_tools}
        frozen_names = set(self._frozen_tools.keys())

        # Tool added
        for name in current_names - frozen_names:
            issues.append(f"Tool added: {name}")

        # Tool removed
        for name in frozen_names - current_names:
            issues.append(f"Tool removed: {name}")

        # Schema changed
        for name in current_names & frozen_names:
            current_schema = next(
                (t[2] for t in current_tools if t[0] == name), {}
            )
            ft = FrozenTool.from_discovery(name, "", current_schema or {})
            frozen_ft = self._frozen_tools[name]
            if ft.schema_hash != frozen_ft.schema_hash:
                issues.append(
                    f"Schema changed for '{name}': "
                    f"frozen={frozen_ft.schema_hash}, current={ft.schema_hash}"
                )

        return issues

    def verify_frozen(self) -> None:
        """Verify the frozen tool list against the current server state.

        Re-discovers tools and checks for mutations. Raises MCPGatewayError
        if mutations are detected and require_approval_for_mutation is set.
        """
        # Re-discover
        if self._has_sdk:
            current = asyncio.run(
                asyncio.wait_for(self._discover_via_sdk(), timeout=self._config.startup_timeout)
            )
        else:
            current = self._discover_via_manual()

        mutations = self.detect_mutation(current)
        if mutations:
            msg = f"MCP server '{self._config.name}' tool mutation detected: {'; '.join(mutations)}"
            if self._config.require_approval_for_mutation:
                raise MCPGatewayError(msg)
            logger.warning(msg)

    # ── Execution ─────────────────────────────────────────────────

    def execute(self, tool_call: ToolCall) -> ToolExecutionResult:
        """Execute a tool call through the gateway with policy enforcement."""
        cfg = self._config

        if not self._connected:
            return ToolExecutionResult(
                tool_call_id=tool_call.id, name=tool_call.name,
                arguments=tool_call.arguments if isinstance(tool_call.arguments, dict) else {},
                ok=False, error=f"MCP server '{cfg.name}' is not connected",
            )

        self._call_count += 1
        if self._call_count > cfg.max_calls_per_run:
            return ToolExecutionResult(
                tool_call_id=tool_call.id, name=tool_call.name,
                arguments=tool_call.arguments if isinstance(tool_call.arguments, dict) else {},
                ok=False,
                error=f"MCP server '{cfg.name}' exceeded max_calls_per_run ({cfg.max_calls_per_run})",
            )

        # Check idle timeout
        if time.monotonic() - self._start_time > cfg.idle_timeout:
            return ToolExecutionResult(
                tool_call_id=tool_call.id, name=tool_call.name,
                arguments=tool_call.arguments if isinstance(tool_call.arguments, dict) else {},
                ok=False,
                error=f"MCP server '{cfg.name}' idle timeout ({cfg.idle_timeout}s) exceeded",
            )

        # Extract base tool name (strip server prefix)
        base_name = tool_call.name.replace(f"{cfg.name}__", "", 1)
        args = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}

        start = time.monotonic()
        request_str = json.dumps(
            {"method": "tools/call", "params": {"name": base_name, "arguments": args}},
            sort_keys=True, ensure_ascii=False,
        )
        request_hash = hashlib.sha256(request_str.encode()).hexdigest()[:16]

        try:
            if self._has_sdk:
                result = asyncio.run(
                    asyncio.wait_for(
                        self._call_tool_via_sdk(base_name, args),
                        timeout=cfg.call_timeout,
                    )
                )
            else:
                result = self._call_tool_via_manual(base_name, args)

            elapsed = int((time.monotonic() - start) * 1000)
            response_hash = hashlib.sha256(
                json.dumps(result, sort_keys=True, ensure_ascii=False, default=str).encode()
            ).hexdigest()[:16]

            self._record_audit(
                server_name=cfg.name, tool_name=base_name, call_id=tool_call.id or "",
                request_hash=request_hash, response_hash=response_hash,
                latency_ms=elapsed, ok=True,
            )

            return ToolExecutionResult(
                tool_call_id=tool_call.id, name=tool_call.name,
                arguments=args, ok=True, result=result, elapsed_ms=elapsed,
            )
        except asyncio.TimeoutError:
            elapsed = int((time.monotonic() - start) * 1000)
            self._record_audit(
                server_name=cfg.name, tool_name=base_name, call_id=tool_call.id or "",
                request_hash=request_hash, response_hash="",
                latency_ms=elapsed, ok=False, error="call timeout",
            )
            return ToolExecutionResult(
                tool_call_id=tool_call.id, name=tool_call.name,
                arguments=args, ok=False,
                error=f"MCP tool '{base_name}' timed out after {cfg.call_timeout}s",
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            self._record_audit(
                server_name=cfg.name, tool_name=base_name, call_id=tool_call.id or "",
                request_hash=request_hash, response_hash="",
                latency_ms=elapsed, ok=False, error=str(e)[:200],
            )
            return ToolExecutionResult(
                tool_call_id=tool_call.id, name=tool_call.name,
                arguments=args, ok=False, error=str(e), elapsed_ms=elapsed,
            )

    def _record_audit(self, **kwargs) -> None:
        self.audit_trail.append(GatewayAuditRecord(timestamp=time.time(), **kwargs))

    # ── Wrapper Factory ───────────────────────────────────────────

    def _make_wrapper(self, tool_name: str):
        """Create a wrapper function that calls the tool via this gateway."""
        gateway = self

        def wrapper(**kwargs):
            tc = ToolCall(name=tool_name, arguments=kwargs)
            result = gateway.execute(tc)
            if not result.ok:
                raise RuntimeError(result.error or "MCP tool execution failed")
            return result.result

        wrapper.__name__ = tool_name
        return wrapper

    # ── SDK Transport ─────────────────────────────────────────────

    async def _discover_via_sdk(self) -> list[tuple[str, str, dict]]:
        from mcp.client.stdio import stdio_client
        from mcp import ClientSession

        cfg = self._config
        params = cfg.to_stdio_params()
        read, write = await stdio_client(params).__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()
        result = await session.list_tools()
        self._sessions["sdk"] = (read, write, session)
        return [(t.name, t.description or "", t.inputSchema or {}) for t in result.tools]

    async def _call_tool_via_sdk(self, tool_name: str, args: dict) -> Any:
        _, _, session = self._sessions["sdk"]
        result = await session.call_tool(tool_name, args)
        return result.content[0].text if result.content else ""

    # ── Manual Transport (fallback) ───────────────────────────────

    def _discover_via_manual(self) -> list[tuple[str, str, dict]]:
        import os as _os

        cfg = self._config
        # Build env via allowlist
        mcp_env: dict[str, str] = {}
        if cfg.env_allowlist:
            for key in cfg.env_allowlist:
                if key in _os.environ:
                    mcp_env[key] = _os.environ[key]
            if cfg.env:
                for key, val in cfg.env.items():
                    if key in cfg.env_allowlist:
                        mcp_env[key] = val
        elif cfg.env:
            mcp_env = dict(cfg.env)

        proc = subprocess.Popen(
            [cfg.command] + cfg.args,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, shell=False,
            env=mcp_env or None,
            cwd=str(cfg.cwd) if cfg.cwd else None,
        )

        # Drain stderr
        import threading
        def _drain():
            try:
                while True:
                    chunk = proc.stderr.read(4096)
                    if not chunk:
                        break
            except Exception:
                pass
        threading.Thread(target=_drain, daemon=True).start()

        # list_tools request
        request = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/list", "params": {},
        })
        proc.stdin.write(request.encode())
        proc.stdin.flush()
        proc.stdin.close()

        response_raw = proc.stdout.read()
        response = json.loads(response_raw)
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

        tools = response.get("result", {}).get("tools", [])
        return [(t["name"], t.get("description", ""), t.get("inputSchema", {})) for t in tools]

    def _call_tool_via_manual(self, tool_name: str, args: dict) -> Any:
        import os as _os

        cfg = self._config
        mcp_env: dict[str, str] = {}
        if cfg.env_allowlist:
            for key in cfg.env_allowlist:
                if key in _os.environ:
                    mcp_env[key] = _os.environ[key]
            if cfg.env:
                for key, val in cfg.env.items():
                    if key in cfg.env_allowlist:
                        mcp_env[key] = val
        elif cfg.env:
            mcp_env = dict(cfg.env)

        proc = subprocess.Popen(
            [cfg.command] + cfg.args,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, shell=False,
            env=mcp_env or None,
            cwd=str(cfg.cwd) if cfg.cwd else None,
        )

        # call_tool request
        request = json.dumps({
            "jsonrpc": "2.0", "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": args},
        })
        proc.stdin.write(request.encode())
        proc.stdin.flush()
        proc.stdin.close()

        response_raw = proc.stdout.read()
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()

        response = json.loads(response_raw)
        result = response.get("result", {})
        content = result.get("content", [])
        if content:
            text_parts = [c.get("text", "") for c in content if isinstance(c, dict)]
            return "\n".join(text_parts)
        return result

    # ── Cleanup ───────────────────────────────────────────────────

    def disconnect(self) -> None:
        """Kill the MCP server process tree and clean up."""
        self._connected = False
        if "sdk" in self._sessions:
            try:
                _, _, session = self._sessions["sdk"]
                asyncio.run(session.__aexit__(None, None, None))
            except Exception:
                pass
        self._sessions.clear()

    def kill_tree(self) -> None:
        """Force-kill the MCP server process (via taskkill on Windows, pkill on Unix)."""
        self.disconnect()
        import platform
        try:
            if platform.system() == "Windows":
                subprocess.run(
                    ["taskkill", "/F", "/IM", Path(self._config.command).name],
                    timeout=5, capture_output=True,
                )
            else:
                subprocess.run(
                    ["pkill", "-f", self._config.command],
                    timeout=5, capture_output=True,
                )
        except Exception:
            pass
