"""Secret reference and identity types for Lv3 SecretBroker."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SecretRef(BaseModel):
    """A reference to a secret that a tool requires.

    Secrets are resolved at runtime by SecretBroker, never embedded
    in manifests or passed via environment variables directly.
    """

    name: str
    scope: str = "tool"  # "tool", "run", "server"
    required: bool = True
    ttl_seconds: int | None = None
