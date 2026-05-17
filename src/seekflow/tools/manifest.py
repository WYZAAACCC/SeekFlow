"""ToolManifest v1 — external tool identity, capability, and sandbox contract.

A ToolManifest is the Lv3 replacement for direct Python callable registration.
Third-party tools MUST provide a signed manifest before they can be registered.
The manifest is compiled into a ToolPolicy by PolicyCompiler and validated by
PolicyLinter before execution.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from seekflow.types import RiskLevel

ManifestSource = Literal["local", "registry", "mcp", "oci", "wasm"]
SchemaVersion = Literal["seekflow.tool.v1"]


class NetworkManifest(BaseModel):
    """Network access contract for a tool.

    Declares what domains/schemes/ports the tool is allowed to contact.
    The actual enforcement is done by EgressGateway at runtime.
    """

    allowed_domains: set[str] = Field(default_factory=set)
    allowed_schemes: set[str] = Field(default_factory=lambda: {"https"})
    allowed_ports: set[int] = Field(default_factory=lambda: {443})
    allowed_methods: set[str] = Field(default_factory=lambda: {"GET"})
    max_request_bytes: int = 64_000
    max_response_bytes: int = 1_000_000
    max_redirects: int = 3
    block_private_ips: bool = True
    require_tls: bool = True


class FilesystemManifest(BaseModel):
    """Filesystem access contract for a tool.

    Declares what paths and access modes the tool needs.
    Write access requires explicit scoping.
    """

    read_only: bool = True
    workspace_root: Path | None = None
    allowed_paths: set[str] = Field(default_factory=set)
    deny_paths: set[str] = Field(default_factory=set)


class EnvManifest(BaseModel):
    """Environment variable contract for a tool.

    Lv3 tools do NOT inherit os.environ. Every env var must be
    explicitly declared here and resolved via SecretBroker.
    """

    allowlist: set[str] = Field(default_factory=set)
    secrets: set[str] = Field(default_factory=set)
    inherit_host: bool = False


class SandboxManifest(BaseModel):
    """Sandbox profile for external tool execution.

    Declares the isolation mechanism and resource limits.
    """

    runner: Literal["container", "wasm", "firecracker"] = "container"
    image: str | None = None
    image_digest: str | None = None
    memory_mb: int = 256
    cpu_count: float = 1.0
    pids_limit: int = 64
    tmpfs_size_mb: int = 64
    network: Literal["none", "egress_proxy"] = "none"
    read_only_rootfs: bool = True


class ToolManifest(BaseModel):
    """External tool identity and execution contract — Schema v1.

    This is the source of truth for any tool not defined locally in Python.
    The manifest is hashed, signed, compiled into a ToolPolicy, and linted
    before the tool can be registered.
    """

    schema_version: SchemaVersion = "seekflow.tool.v1"

    # Identity
    name: str
    version: str
    description: str = ""
    publisher: str | None = None
    source: ManifestSource = "local"

    # Entrypoint
    entrypoint: dict[str, Any] = Field(default_factory=dict)

    # Integrity
    package_digest: str  # sha256 of the tool package
    package_path: str | None = None
    package_url: str | None = None
    oci_image: str | None = None
    schema_digest: str | None = None
    signature: str | None = None
    signing_key_id: str | None = None

    # Capability declaration
    capabilities: set[str] = Field(default_factory=set)
    risk: RiskLevel = "read"

    # Schemas (JSON Schema)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] | None = None

    # Resource manifests
    network: NetworkManifest = Field(default_factory=NetworkManifest)
    filesystem: FilesystemManifest = Field(default_factory=FilesystemManifest)
    env: EnvManifest = Field(default_factory=EnvManifest)
    sandbox: SandboxManifest = Field(default_factory=SandboxManifest)

    # Policy hints
    requires_approval: bool = False
    idempotent: bool = False
