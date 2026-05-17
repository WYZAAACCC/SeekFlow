"""Manifest verifier — digest and signature verification for ToolManifest.

Phase B: digest verification is enforced; signature verification is a
placeholder that accepts all signatures in non-strict mode and rejects
unsigned external manifests in strict mode.

Phase F: full Ed25519/ECDSA signature verification with key registry.
"""
from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from seekflow.tools.manifest import ToolManifest

if TYPE_CHECKING:
    from seekflow.tools.trust_store import TrustStore


class ManifestVerificationError(ValueError):
    """Raised when manifest verification fails."""


def verify_digest(manifest: ToolManifest, actual_package_bytes: bytes | None = None) -> None:
    """Verify that the manifest's package_digest matches the actual package.

    In Phase B, this is a structural check — we verify the digest field is
    present and well-formed. Full content verification requires the actual
    package bytes, which is done at install time (Phase F CLI).

    Raises ManifestVerificationError if the digest is missing or malformed.
    """
    if not manifest.package_digest:
        raise ManifestVerificationError(
            f"Tool '{manifest.name}': package_digest is required"
        )

    # Validate hex format
    try:
        bytes.fromhex(manifest.package_digest)
    except ValueError:
        raise ManifestVerificationError(
            f"Tool '{manifest.name}': package_digest is not valid hex"
        )

    if len(manifest.package_digest) != 64:
        raise ManifestVerificationError(
            f"Tool '{manifest.name}': package_digest must be 64 hex chars (sha256)"
        )

    # If actual bytes provided, verify content
    if actual_package_bytes is not None:
        actual_digest = hashlib.sha256(actual_package_bytes).hexdigest()
        if actual_digest != manifest.package_digest:
            raise ManifestVerificationError(
                f"Tool '{manifest.name}': digest mismatch — "
                f"expected {manifest.package_digest[:16]}..., "
                f"got {actual_digest[:16]}..."
            )

    # Verify schema digest if provided
    if manifest.schema_digest is not None:
        try:
            bytes.fromhex(manifest.schema_digest)
        except ValueError:
            raise ManifestVerificationError(
                f"Tool '{manifest.name}': schema_digest is not valid hex"
            )


def verify_signature(
    manifest: ToolManifest,
    *,
    strict: bool = False,
    trust_store: "TrustStore | None" = None,
) -> None:
    """Verify the manifest's Ed25519 signature.

    In strict mode, external-source manifests MUST have a valid signature.
    Local-source manifests are exempt. When a signature is present and a
    trust_store is provided, real Ed25519 cryptographic verification is
    performed.

    Raises ManifestVerificationError on any failure.
    """
    if manifest.source != "local" and strict:
        if not manifest.signature:
            raise ManifestVerificationError(
                f"Tool '{manifest.name}': strict mode requires a signature "
                f"for source={manifest.source}"
            )
        if not manifest.signing_key_id:
            raise ManifestVerificationError(
                f"Tool '{manifest.name}': signature present but signing_key_id is missing"
            )
        if trust_store is None:
            raise ManifestVerificationError(
                f"Tool '{manifest.name}': strict mode requires trust_store "
                f"for source={manifest.source}"
            )

    if not manifest.signature:
        return

    # Real verification when signature is present
    if trust_store is not None and manifest.signing_key_id:
        from seekflow.tools.trust_store import verify_ed25519_signature, TrustStoreError
        try:
            verify_ed25519_signature(manifest, trust_store)
        except ImportError:
            raise ManifestVerificationError(
                "cryptography>=42 required for signature verification"
            )
        except TrustStoreError as e:
            raise ManifestVerificationError(str(e)) from e


def verify_manifest(
    manifest: ToolManifest,
    *,
    package_bytes: bytes | None = None,
    strict: bool = False,
    trust_store: "TrustStore | None" = None,
) -> None:
    """Run all verification checks on a manifest.

    Raises ManifestVerificationError on the first failure.
    """
    verify_digest(manifest, package_bytes)
    verify_signature(manifest, strict=strict, trust_store=trust_store)


def compute_manifest_digest(manifest: ToolManifest) -> str:
    """Compute a canonical sha256 digest of the manifest for audit purposes.

    This is NOT the package digest — it's the digest of the manifest itself,
    used for policy pinning and audit trail.
    """
    # Use json dump with sorted keys for deterministic output
    canonical = manifest.model_dump(mode="json", exclude={"signature"})
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
