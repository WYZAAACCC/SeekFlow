"""TrustStore — public key registry for manifest signature verification.

Lv3 supply-chain security: ToolManifest signatures are verified against
registered public keys. Keys are identified by key_id and can be loaded
from files, environment, or a key server.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any


class TrustStoreError(ValueError):
    """Raised when a trust store operation fails."""


class TrustStore:
    """Registry of trusted public keys for manifest signature verification.

    Usage:
        store = TrustStore()
        store.add_key("publisher-1", public_key_bytes)
        store.verify(manifest)  # raises on failure
    """

    def __init__(self, keys: dict[str, bytes] | None = None):
        self._keys: dict[str, bytes] = dict(keys) if keys else {}

    def add_key(self, key_id: str, public_key_bytes: bytes) -> None:
        """Register a public key for a given key_id."""
        if len(public_key_bytes) != 32:
            raise TrustStoreError(
                f"Ed25519 public key must be 32 bytes, got {len(public_key_bytes)}"
            )
        self._keys[key_id] = public_key_bytes

    def add_key_from_file(self, key_id: str, path: str | Path) -> None:
        """Load a public key from a file (raw bytes or base64)."""
        data = Path(path).read_bytes()
        if data.startswith(b"-----"):
            # PEM format: extract base64 content
            lines = data.decode().strip().split("\n")
            b64 = "".join(l for l in lines if not l.startswith("-----"))
            data = base64.b64decode(b64)
        elif len(data) > 32:
            # Assume base64-encoded
            try:
                data = base64.b64decode(data.decode().strip())
            except Exception:
                pass
        self.add_key(key_id, data)

    def get_public_key(self, key_id: str) -> bytes:
        """Get a registered public key. Raises TrustStoreError if not found."""
        if key_id not in self._keys:
            raise TrustStoreError(
                f"Unknown signing key_id: {key_id}. "
                "Register the key via TrustStore.add_key() or add_key_from_file()."
            )
        return self._keys[key_id]


def canonical_manifest_bytes(manifest: Any) -> bytes:
    """Compute canonical JSON bytes of a manifest for signing/verification.

    Excludes the signature field itself and uses sorted keys for determinism.
    """
    import json
    data = manifest.model_dump(mode="json", exclude={"signature", "event_hash"})
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def verify_ed25519_signature(
    manifest: Any,
    trust_store: TrustStore,
) -> None:
    """Verify an Ed25519 signature on a manifest.

    Requires: cryptography >= 42.0

    Raises:
        TrustStoreError: if verification fails or key not found.
        ImportError: if cryptography is not installed.
    """
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        raise ImportError(
            "cryptography>=42 is required for signature verification. "
            "Install with: pip install cryptography>=42"
        )

    if not manifest.signature:
        raise TrustStoreError("Manifest has no signature")

    if not manifest.signing_key_id:
        raise TrustStoreError("Manifest has signature but no signing_key_id")

    public_key_bytes = trust_store.get_public_key(manifest.signing_key_id)
    public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
    payload = canonical_manifest_bytes(manifest)

    try:
        signature_bytes = base64.b64decode(manifest.signature)
        public_key.verify(signature_bytes, payload)
    except InvalidSignature:
        raise TrustStoreError(
            f"Invalid signature for manifest '{manifest.name}' "
            f"(key_id={manifest.signing_key_id})"
        )
    except Exception as e:
        raise TrustStoreError(f"Signature verification failed: {e}")
