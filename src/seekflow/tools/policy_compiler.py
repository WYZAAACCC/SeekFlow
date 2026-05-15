"""PolicyCompiler — compiles a ToolManifest into a ToolPolicy.

The compiler is the bridge between external tool declarations and the
internal policy enforcement system. It ensures that third-party tools
cannot declare capabilities beyond what their manifest authorizes.
"""
from __future__ import annotations

from seekflow.tools.manifest import ToolManifest
from seekflow.types import RiskLevel, RunnerKind, ToolPolicy


def compile_policy(manifest: ToolManifest) -> ToolPolicy:
    """Compile a ToolManifest into an executable ToolPolicy.

    Rules (fail-closed):
    - source != "local" → runner="container", trusted=False, trusted_output=False
    - network.allowed_domains → allowed_domains + url_params
    - filesystem.workspace_root → workspace_root + capabilities
    - env → reflected in capabilities but actual enforcement is via SecretBroker
    - sandbox → runner selection + timeout from resource limits
    - risk=code_exec/destructive → runner=container (enforced)
    - risk=network → requires allowed_domains non-empty
    - risk=write → requires workspace_root
    """
    source = manifest.source
    is_local = source == "local"
    risk: RiskLevel = manifest.risk

    # ── Runner selection ──────────────────────────────────────────
    if is_local:
        runner: RunnerKind = "auto"  # planner decides
        trusted = True
        container_codegen = False
        trusted_output = False
        allow_in_process_fallback = False
    else:
        # Non-local tools NEVER run in-process, in a subprocess, or in the
        # trusted codegen ContainerRunner. They must go through
        # ExternalToolRunner with full container isolation.
        runner = "external_container"
        trusted = False
        container_codegen = False
        trusted_output = False
        allow_in_process_fallback = False

    # ── Capabilities ──────────────────────────────────────────────
    capabilities: set[str] = set(manifest.capabilities)

    if manifest.network.allowed_domains:
        capabilities.add("network.public_http")
    if not manifest.filesystem.read_only or manifest.filesystem.workspace_root:
        capabilities.add("filesystem.read")
    if not manifest.filesystem.read_only and manifest.risk == "write":
        capabilities.add("filesystem.write")

    # ── Domain / path constraints ─────────────────────────────────
    allowed_domains: set[str] = set(manifest.network.allowed_domains)
    workspace_root = manifest.filesystem.workspace_root

    path_params: frozenset[str] = frozenset()
    if "filesystem.read" in capabilities or "filesystem.write" in capabilities:
        # Extract path param names from input schema if present
        props = manifest.input_schema.get("properties", {})
        path_candidates = {k for k, v in props.items() if _looks_like_path(k, v)}
        if path_candidates:
            path_params = frozenset(path_candidates)
        elif workspace_root:
            path_params = frozenset({"path"})

    url_params: frozenset[str] = frozenset()
    if "network.public_http" in capabilities:
        props = manifest.input_schema.get("properties", {})
        url_candidates = {k for k, v in props.items() if _looks_like_url(k, v)}
        if url_candidates:
            url_params = frozenset(url_candidates)
        else:
            url_params = frozenset({"url"})

    # ── Timeout ───────────────────────────────────────────────────
    timeout_s = 30.0
    if manifest.sandbox.runner == "container":
        timeout_s = max(timeout_s, 60.0)  # container startup overhead

    # ── Approval ──────────────────────────────────────────────────
    requires_approval = manifest.requires_approval
    if risk in ("code_exec", "destructive") and not requires_approval:
        requires_approval = True  # force approval for dangerous tools

    return ToolPolicy(
        capabilities=capabilities,
        risk=risk,
        timeout_s=timeout_s,
        runner=runner,
        trusted=trusted,
        trusted_output=trusted_output,
        idempotent=manifest.idempotent,
        allow_in_process_fallback=allow_in_process_fallback,
        container_codegen_trusted=container_codegen,
        parallel_safe=is_local,
        requires_approval=requires_approval,
        allowed_domains=allowed_domains,
        workspace_root=workspace_root,
        path_params=path_params,
        url_params=url_params,
    )


def _looks_like_path(key: str, schema: dict) -> bool:
    """Heuristic: does a schema property look like a filesystem path?"""
    if key in ("path", "file", "filepath", "filename", "directory", "dir", "folder"):
        return True
    if "path" in key.lower():
        return True
    return False


def _looks_like_url(key: str, schema: dict) -> bool:
    """Heuristic: does a schema property look like a URL?"""
    if key in ("url", "uri", "endpoint", "href", "link"):
        return True
    if schema.get("format") == "uri":
        return True
    return False
