"""Manifest verifier — digest and signature verification for ToolManifest.

Phase B: digest verification is enforced; signature verification is a
placeholder that accepts all signatures in non-strict mode and rejects
unsigned external manifests in strict mode.

Phase F: full Ed25519/ECDSA signature verification with key registry.
"""
from __future__ import annotations

import hashlib
import json

from seekflow.tools.manifest import ToolManifest


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
) -> None:
    """Verify the manifest's signature.

    Phase B placeholder:
    - If no signature and source is 'local': OK (trusted local tool)
    - If no signature and source is external + strict=True: REJECT
    - If signature present: accept (verification placeholder)

    Phase F: full cryptographic verification.
    """
    if manifest.signature is None:
        if strict and manifest.source != "local":
            raise ManifestVerificationError(
                f"Tool '{manifest.name}': strict mode requires a signature "
                f"for source={manifest.source}"
            )
        return

    # Placeholder: in Phase F, verify Ed25519/ECDSA signature against
    # the manifest's canonical JSON bytes using the key identified by
    # manifest.signing_key_id.
    if not manifest.signing_key_id and strict:
        raise ManifestVerificationError(
            f"Tool '{manifest.name}': signature present but signing_key_id is missing"
        )


def verify_manifest(
    manifest: ToolManifest,
    *,
    package_bytes: bytes | None = None,
    strict: bool = False,
) -> None:
    """Run all verification checks on a manifest.

    Raises ManifestVerificationError on the first failure.
    """
    verify_digest(manifest, package_bytes)
    verify_signature(manifest, strict=strict)


def compute_manifest_digest(manifest: ToolManifest) -> str:
    """Compute a canonical sha256 digest of the manifest for audit purposes.

    This is NOT the package digest — it's the digest of the manifest itself,
    used for policy pinning and audit trail.
    """
    # Use json dump with sorted keys for deterministic output
    canonical = manifest.model_dump(mode="json", exclude={"signature"})
    raw = json.dumps(canonical, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
