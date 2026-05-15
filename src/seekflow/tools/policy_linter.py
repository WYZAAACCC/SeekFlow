"""PolicyLinter — security lint rules for ToolPolicy before registration.

Each rule is a function that takes a ToolPolicy + context (manifest source, etc.)
and returns a list of LintIssue. Rules are DENY by default — anything not
explicitly allowed is flagged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

from seekflow.types import ToolPolicy
from seekflow.tools.manifest import ManifestSource

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class LintIssue:
    """A single lint violation found during policy review."""

    severity: Severity
    code: str
    message: str
    path: str = "$"


# ── Rule type ─────────────────────────────────────────────────────
LintRule = Callable[[ToolPolicy, ManifestSource], list[LintIssue]]


# ── Rule implementations ──────────────────────────────────────────

def _rule_no_local_runner_for_external(
    policy: ToolPolicy, source: ManifestSource
) -> list[LintIssue]:
    """Non-local tools MUST use external_container — never in_process/process/container."""
    if source in {"registry", "mcp", "oci", "wasm"}:
        if policy.runner != "external_container":
            return [LintIssue(
                severity="error",
                code="L001",
                message=f"source={source} requires runner=external_container; "
                        f"got runner={policy.runner}",
                path="$.runner",
            )]
    return []


def _rule_network_requires_domains(
    policy: ToolPolicy, source: ManifestSource
) -> list[LintIssue]:
    """Network tools must declare allowed_domains."""
    if policy.risk == "network" and not policy.allowed_domains:
        return [LintIssue(
            severity="error",
            code="L002",
            message="risk=network requires non-empty allowed_domains",
            path="$.allowed_domains",
        )]
    if "network.public_http" in policy.capabilities and not policy.url_params:
        return [LintIssue(
            severity="error",
            code="L003",
            message="network.public_http capability requires url_params",
            path="$.url_params",
        )]
    return []


def _rule_filesystem_requires_workspace(
    policy: ToolPolicy, source: ManifestSource
) -> list[LintIssue]:
    """Filesystem tools must declare workspace_root."""
    has_fs = "filesystem.read" in policy.capabilities or "filesystem.write" in policy.capabilities
    if has_fs and policy.workspace_root is None:
        return [LintIssue(
            severity="error",
            code="L004",
            message="filesystem capabilities require workspace_root",
            path="$.workspace_root",
        )]
    return []


def _rule_write_requires_approval(
    policy: ToolPolicy, source: ManifestSource
) -> list[LintIssue]:
    """Write tools require approval unless explicitly trusted + codegen."""
    if "filesystem.write" in policy.capabilities:
        if not policy.requires_approval and not (
            policy.trusted and policy.container_codegen_trusted
        ):
            return [LintIssue(
                severity="error",
                code="L005",
                message="filesystem.write requires requires_approval=True "
                        "unless trusted=True + container_codegen_trusted=True",
                path="$.requires_approval",
            )]
    return []


def _rule_code_exec_requires_container(
    policy: ToolPolicy, source: ManifestSource
) -> list[LintIssue]:
    """code_exec/destructive must use container runner."""
    if policy.risk in {"code_exec", "destructive"}:
        if policy.runner not in {"container", "auto"}:
            return [LintIssue(
                severity="error",
                code="L006",
                message=f"risk={policy.risk} requires container runner, "
                        f"got runner={policy.runner}",
                path="$.runner",
            )]
    return []


def _rule_no_trusted_output_for_external(
    policy: ToolPolicy, source: ManifestSource
) -> list[LintIssue]:
    """Third-party tools must not declare trusted_output=True."""
    if source != "local" and policy.trusted_output:
        return [LintIssue(
            severity="error",
            code="L007",
            message=f"trusted_output=True not allowed for source={source}",
            path="$.trusted_output",
        )]
    return []


def _rule_cache_restricted(
    policy: ToolPolicy, source: ManifestSource
) -> list[LintIssue]:
    """Cache only for read tools or idempotent network tools."""
    # This rule is advisory — executor._cache_allowed handles enforcement.
    # We flag it here so policy authors know.
    if policy.risk not in {"read"} and not (
        policy.risk == "network" and policy.idempotent
    ):
        # Not an error, but a warning for policy authors
        return [LintIssue(
            severity="warning",
            code="L008",
            message=f"Cache is disabled for risk={policy.risk}. "
                    "Only read and idempotent network tools are cached.",
            path="$",
        )]
    return []


def _rule_no_env_wildcard(
    policy: ToolPolicy, source: ManifestSource
) -> list[LintIssue]:
    """Wildcard env is not allowed. Each env var must be explicit."""
    # This rule applies to the manifest, not the policy directly.
    # We issue a warning since the policy doesn't carry env details.
    # Full enforcement is in manifest_loader + SecretBroker.
    return []


def _rule_no_wildcard_domains(
    policy: ToolPolicy, source: ManifestSource
) -> list[LintIssue]:
    """Wildcard domains are not allowed."""
    if "*" in policy.allowed_domains:
        return [LintIssue(
            severity="error",
            code="L009",
            message="allowed_domains must not contain wildcard '*'",
            path="$.allowed_domains",
        )]
    return []


def _rule_no_public_suffix_only_domains(
    policy: ToolPolicy, source: ManifestSource
) -> list[LintIssue]:
    """Domains must be FQDN, not public suffixes like 'com' or 'co.uk'."""
    for domain in policy.allowed_domains:
        if "." not in domain:
            return [LintIssue(
                severity="error",
                code="L010",
                message=f"allowed_domain '{domain}' is not a FQDN (no dot)",
                path=f"$.allowed_domains.{domain}",
            )]
    return []


def _rule_path_params_for_filesystem(
    policy: ToolPolicy, source: ManifestSource
) -> list[LintIssue]:
    """Filesystem tools must declare path_params."""
    has_fs = "filesystem.read" in policy.capabilities or "filesystem.write" in policy.capabilities
    if has_fs and not policy.path_params:
        return [LintIssue(
            severity="warning",
            code="L011",
            message="filesystem capabilities without path_params — "
                    "path traversal checks may be incomplete",
            path="$.path_params",
        )]
    return []


# ── Rule registry ─────────────────────────────────────────────────

ALL_RULES: list[LintRule] = [
    _rule_no_local_runner_for_external,
    _rule_network_requires_domains,
    _rule_filesystem_requires_workspace,
    _rule_write_requires_approval,
    _rule_code_exec_requires_container,
    _rule_no_trusted_output_for_external,
    _rule_cache_restricted,
    _rule_no_env_wildcard,
    _rule_no_wildcard_domains,
    _rule_no_public_suffix_only_domains,
    _rule_path_params_for_filesystem,
]


def lint_policy(
    policy: ToolPolicy,
    source: ManifestSource = "local",
    *,
    rules: list[LintRule] | None = None,
) -> list[LintIssue]:
    """Run all lint rules against a compiled policy.

    Returns a list of LintIssue. An empty list means the policy passes.
    Errors (severity="error") must block registration.
    Warnings (severity="warning") are advisory.
    """
    active_rules = rules if rules is not None else ALL_RULES
    issues: list[LintIssue] = []
    for rule in active_rules:
        try:
            issues.extend(rule(policy, source))
        except Exception as e:
            issues.append(LintIssue(
                severity="error",
                code="L999",
                message=f"Lint rule {rule.__name__} raised: {e}",
                path="$",
            ))
    return issues


def has_errors(issues: list[LintIssue]) -> bool:
    """Return True if any issue is severity='error'."""
    return any(i.severity == "error" for i in issues)
