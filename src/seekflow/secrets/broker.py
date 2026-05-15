"""SecretBroker — Lv3 secret injection for external tool execution.

Replaces ambient os.environ inheritance with explicit, audited secret
injection. Each secret is resolved by reference, not by value, and
never appears in traces or model output.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from seekflow.secrets.types import SecretRef


@dataclass
class SecretResolution:
    """Result of resolving a secret reference."""
    ref: SecretRef
    resolved: bool
    value: str | None = None
    error: str | None = None


@dataclass
class SecretAuditEntry:
    """Audit record for a secret resolution — value NEVER included."""
    timestamp: float = 0.0
    secret_name: str = ""
    scope: str = ""
    tool_name: str = ""
    run_id: str = ""
    resolved: bool = False
    ref_hash: str = ""


class SecretBroker:
    """Lv3 secret broker — resolves SecretRefs without exposing values.

    Rules:
    - Default gives no env at all.
    - No os.environ inheritance.
    - Secrets resolved by reference via registered providers.
    - Secret values never enter trace or model output.
    - Every resolution is audited (name + hash only, no value).
    - EnvProvider requires explicit allowlist — no ambient env access.
    """

    def __init__(self):
        self._providers: dict[str, Any] = {
            "memory": _MemoryProvider(),
        }
        self.audit_entries: list[SecretAuditEntry] = []

    def register_provider(self, name: str, provider: Any) -> None:
        """Register a secret provider backend."""
        self._providers[name] = provider

    def resolve_for_tool(
        self,
        tool_name: str,
        refs: list[SecretRef],
        run_id: str = "",
    ) -> dict[str, str]:
        """Resolve a list of SecretRefs into a dict of name→value.

        Unresolved required refs raise ValueError.
        Values are injected into the tool's environment — never logged.
        """
        resolved: dict[str, str] = {}
        for ref in refs:
            value = self._resolve_ref(ref)
            if value is None and ref.required:
                raise ValueError(
                    f"Secret '{ref.name}' (scope={ref.scope}) required "
                    f"by tool '{tool_name}' could not be resolved"
                )

            ref_hash = _hash_ref(ref)
            self.audit_entries.append(SecretAuditEntry(
                timestamp=time.time(),
                secret_name=ref.name,
                scope=ref.scope,
                tool_name=tool_name,
                run_id=run_id,
                resolved=value is not None,
                ref_hash=ref_hash,
            ))

            if value is not None:
                resolved[ref.name] = value

        return resolved

    def _resolve_ref(self, ref: SecretRef) -> str | None:
        for provider in self._providers.values():
            try:
                value = provider.resolve(ref)
                if value is not None:
                    return value
            except Exception:
                continue
        return None


class _EnvProvider:
    """Resolves secrets from environment variables (explicit allowlist only).

    Lv3 fail-closed: no ambient env access. Each allowed env var must be
    explicitly listed at construction time.
    """
    def __init__(self, allowed_names: set[str] | None = None):
        self.allowed_names = allowed_names or set()

    def resolve(self, ref: SecretRef) -> str | None:
        import os as _os
        if ref.name not in self.allowed_names:
            return None
        return _os.environ.get(ref.name)


class _MemoryProvider:
    """Resolves secrets from an in-memory store (for testing/config)."""
    def __init__(self):
        self._store: dict[str, str] = {}

    def set(self, name: str, value: str) -> None:
        self._store[name] = value

    def resolve(self, ref: SecretRef) -> str | None:
        return self._store.get(ref.name)


def _hash_ref(ref: SecretRef) -> str:
    raw = f"{ref.name}:{ref.scope}:{ref.required}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
