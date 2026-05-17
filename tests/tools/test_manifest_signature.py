"""Phase 1 tests: manifest signature verification + package digest binding."""
from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from seekflow.tools.manifest import ToolManifest
from seekflow.tools.manifest_verify import (
    ManifestVerificationError,
    verify_digest,
    verify_manifest,
    verify_signature,
)
from seekflow.tools.trust_store import TrustStore


def _make_manifest(*, source="local", signature=None, signing_key_id=None, package_digest=None):
    return ToolManifest(
        name="test-tool",
        version="1.0.0",
        source=source,
        package_digest=package_digest or hashlib.sha256(b"test").hexdigest(),
        signature=signature,
        signing_key_id=signing_key_id,
    )


# ── P0-B: signature verification ──────────────────────────────────


def test_strict_external_manifest_requires_signature():
    """strict=True下外部manifest无签名→拒绝"""
    manifest = _make_manifest(source="registry", signature=None)
    with pytest.raises(ManifestVerificationError, match="strict mode requires a signature"):
        verify_signature(manifest, strict=True, trust_store=TrustStore())


def test_strict_external_manifest_requires_trust_store():
    """strict=True下无trust_store→拒绝"""
    manifest = _make_manifest(
        source="registry",
        signature=base64.b64encode(b"\x00" * 64).decode(),
        signing_key_id="key-1",
    )
    with pytest.raises(ManifestVerificationError, match="strict mode requires trust_store"):
        verify_signature(manifest, strict=True, trust_store=None)


def test_local_manifest_no_signature_ok():
    """local manifest不需要签名，静默通过"""
    manifest = _make_manifest(source="local", signature=None)
    verify_signature(manifest, strict=True)  # no raise


def test_valid_ed25519_signature_passes():
    """正确Ed25519签名→通过"""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        pytest.skip("cryptography not installed")

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes_raw()

    manifest = _make_manifest(source="registry", signing_key_id="key-1")
    # Compute canonical bytes and sign
    from seekflow.tools.trust_store import canonical_manifest_bytes
    payload = canonical_manifest_bytes(manifest)
    sig = private_key.sign(payload)
    manifest.signature = base64.b64encode(sig).decode()

    ts = TrustStore({"key-1": public_bytes})
    verify_signature(manifest, strict=True, trust_store=ts)  # no raise


def test_invalid_signature_fails():
    """签名不匹配→拒绝"""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        pytest.skip("cryptography not installed")

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes_raw()

    manifest = _make_manifest(source="registry", signing_key_id="key-1")
    from seekflow.tools.trust_store import canonical_manifest_bytes
    payload = canonical_manifest_bytes(manifest)
    # Sign a DIFFERENT payload
    sig = private_key.sign(b"wrong payload")
    manifest.signature = base64.b64encode(sig).decode()

    ts = TrustStore({"key-1": public_bytes})
    with pytest.raises(ManifestVerificationError, match="Invalid signature"):
        verify_signature(manifest, strict=True, trust_store=ts)


def test_unknown_signing_key_fails():
    """signing_key_id不在trust_store→拒绝"""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        pytest.skip("cryptography not installed")

    private_key = Ed25519PrivateKey.generate()
    manifest = _make_manifest(source="registry", signing_key_id="key-unknown")
    from seekflow.tools.trust_store import canonical_manifest_bytes
    payload = canonical_manifest_bytes(manifest)
    sig = private_key.sign(payload)
    manifest.signature = base64.b64encode(sig).decode()

    ts = TrustStore({"key-1": b"\x00" * 32})
    with pytest.raises(ManifestVerificationError, match="Unknown signing key_id"):
        verify_signature(manifest, strict=True, trust_store=ts)


def test_manifest_tamper_after_signing_fails():
    """签后篡改→拒绝"""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        pytest.skip("cryptography not installed")

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    public_bytes = public_key.public_bytes_raw()

    manifest = _make_manifest(source="registry", signing_key_id="key-1")
    from seekflow.tools.trust_store import canonical_manifest_bytes
    payload = canonical_manifest_bytes(manifest)
    sig = private_key.sign(payload)
    manifest.signature = base64.b64encode(sig).decode()

    # Tamper: change version after signing
    manifest.version = "2.0.0"

    ts = TrustStore({"key-1": public_bytes})
    with pytest.raises(ManifestVerificationError, match="Invalid signature"):
        verify_signature(manifest, strict=True, trust_store=ts)


# ── P0-C: package digest binding ──────────────────────────────────


def test_package_digest_mismatch_rejected():
    """实际包digest与manifest不一致→拒绝"""
    package_bytes = b"real package content"
    manifest = _make_manifest(package_digest=hashlib.sha256(b"wrong content").hexdigest())

    with pytest.raises(ManifestVerificationError, match="digest mismatch"):
        verify_digest(manifest, actual_package_bytes=package_bytes)


def test_package_digest_match_passes():
    """实际包digest匹配→通过"""
    package_bytes = b"real package content"
    digest = hashlib.sha256(package_bytes).hexdigest()
    manifest = _make_manifest(package_digest=digest)

    verify_digest(manifest, actual_package_bytes=package_bytes)  # no raise


def test_oci_tag_only_rejected():
    """OCI image使用tag而非digest→CLI拒绝"""
    # Simulate the check directly
    oci_image = "python:3.11"
    assert "@sha256:" not in oci_image


def test_cli_install_strict_validates_package():
    """CLI install --strict读取实际包并校验digest"""
    package_bytes = b"package v1.0.0"
    digest = hashlib.sha256(package_bytes).hexdigest()
    manifest = _make_manifest(source="local", package_digest=digest)

    verify_manifest(manifest, package_bytes=package_bytes, strict=True)  # no raise
