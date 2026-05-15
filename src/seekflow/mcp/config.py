"""Configuration for MCP server connections with security profiles."""
from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class MCPTrustLevel(str, Enum):
    TRUSTED = "trusted"
    SANDBOXED = "sandboxed"
    UNTRUSTED = "untrusted"


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server via stdio transport.

    Lv3 hardening: trust_level defaults to UNTRUSTED, env must pass
    env_allowlist filtering, command_digest enables pinning.
    """

    name: str
    transport: str = "stdio"
    command: str
    args: list[str] = Field(default_factory=list)
    command_digest: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    trust_level: MCPTrustLevel = MCPTrustLevel.UNTRUSTED

    # Security profile
    allowed_capabilities: set[str] | None = None
    max_risk: str = "read"
    allowed_domains: set[str] = Field(default_factory=set)
    workspace_root: Path | None = None
    requires_approval: bool = False

    # Sandbox / isolation
    sandbox: Any | None = None
    env_allowlist: set[str] = Field(default_factory=set)
    cwd: Path | None = None

    # Tool management
    freeze_tools: bool = True
    require_approval_for_mutation: bool = True

    # Connection
    startup_timeout: float = 10.0
    call_timeout: float = 30.0
    idle_timeout: float = 300.0
    max_calls_per_run: int = 100
    fail_fast: bool = False

    @classmethod
    def stdio(
        cls,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        trust_level: MCPTrustLevel = MCPTrustLevel.UNTRUSTED,
        startup_timeout: float = 10.0,
        capabilities: set[str] | None = None,
        env_allowlist: set[str] | None = None,
    ) -> "MCPServerConfig":
        """Create a stdio MCP server configuration (Lv3 defaults)."""
        return cls(
            name=name,
            transport="stdio",
            command=command,
            args=args or [],
            env=env or {},
            trust_level=trust_level,
            startup_timeout=startup_timeout,
            allowed_capabilities=capabilities,
            env_allowlist=env_allowlist or set(),
        )

    def to_stdio_params(self):
        """Convert to mcp StdioServerParameters with env_allowlist filtering.

        Lv3: env is filtered through env_allowlist. Only explicitly allowed
        keys from os.environ are passed through, plus any explicit overrides
        in cfg.env that are also in the allowlist.
        """
        from mcp.client.stdio import StdioServerParameters

        filtered_env: dict[str, str] = {}
        if self.env_allowlist:
            import os as _os
            for key in self.env_allowlist:
                if key in _os.environ:
                    filtered_env[key] = _os.environ[key]
            # Apply explicit overrides that are in the allowlist
            if self.env:
                for key, val in self.env.items():
                    if key in self.env_allowlist:
                        filtered_env[key] = val
        elif self.env:
            # No allowlist set — pass only explicit env, warn
            import warnings
            warnings.warn(
                f"MCP server '{self.name}' has env set but no env_allowlist. "
                "In Lv3, env without allowlist is not recommended.",
                RuntimeWarning,
                stacklevel=2,
            )
            filtered_env = dict(self.env)

        return StdioServerParameters(
            command=self.command,
            args=self.args,
            env=filtered_env if filtered_env else None,
        )
