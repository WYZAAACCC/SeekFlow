"""Phase B: ToolManifest v1 — validation, compilation, and verification tests."""
import json
import tempfile
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from seekflow.tools.manifest import (
    ToolManifest, NetworkManifest, FilesystemManifest,
    EnvManifest, SandboxManifest,
)
from seekflow.tools.manifest_loader import (
    load_manifest_from_dict, load_manifest_from_yaml,
    load_manifest_from_json, load_manifest, ManifestLoadError,
)
from seekflow.tools.manifest_verify import (
    verify_manifest, verify_digest, verify_signature,
    compute_manifest_digest, ManifestVerificationError,
)
from seekflow.tools.policy_compiler import compile_policy
from seekflow.tools.policy_linter import lint_policy, has_errors
from seekflow.tools.registry import ToolRegistry


VALID_MANIFEST_DICT = {
    "name": "example-tool",
    "version": "1.0.0",
    "description": "An example tool for testing",
    "publisher": "test-org",
    "source": "registry",
    "entrypoint": {"command": "python", "args": ["/tool/main.py"]},
    "package_digest": "a" * 64,
    "capabilities": ["filesystem.read"],
    "risk": "read",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path"},
        },
        "required": ["path"],
    },
    "filesystem": {
        "workspace_root": "/workspace",
        "read_only": True,
    },
}


class TestToolManifestValidation:
    """ToolManifest Pydantic validation."""

    def test_valid_manifest_loads(self):
        m = load_manifest_from_dict(VALID_MANIFEST_DICT)
        assert m.name == "example-tool"
        assert m.version == "1.0.0"
        assert m.source == "registry"
        assert m.package_digest == "a" * 64

    def test_manifest_requires_package_digest(self):
        data = {**VALID_MANIFEST_DICT}
        del data["package_digest"]
        with pytest.raises(ManifestLoadError, match="package_digest"):
            load_manifest_from_dict(data)

    def test_manifest_source_defaults_to_local(self):
        data = {
            "name": "local-tool",
            "version": "1.0.0",
            "package_digest": "b" * 64,
            "input_schema": {"type": "object", "properties": {}},
        }
        m = load_manifest_from_dict(data)
        assert m.source == "local"

    def test_schema_version_default(self):
        m = load_manifest_from_dict(VALID_MANIFEST_DICT)
        assert m.schema_version == "seekflow.tool.v1"

    def test_network_manifest_defaults(self):
        nm = NetworkManifest()
        assert nm.allowed_domains == set()
        assert nm.allowed_schemes == {"https"}
        assert nm.require_tls is True

    def test_filesystem_manifest_defaults(self):
        fm = FilesystemManifest()
        assert fm.read_only is True
        assert fm.workspace_root is None

    def test_env_manifest_defaults(self):
        em = EnvManifest()
        assert em.inherit_host is False
        assert em.allowlist == set()

    def test_sandbox_manifest_defaults(self):
        sm = SandboxManifest()
        assert sm.runner == "container"
        assert sm.network == "none"


class TestManifestLoader:
    """Loading manifests from files."""

    def test_load_from_yaml_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(VALID_MANIFEST_DICT, f)
            f.flush()
            m = load_manifest_from_yaml(f.name)
        Path(f.name).unlink(missing_ok=True)
        assert m.name == "example-tool"

    def test_load_from_json_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(VALID_MANIFEST_DICT, f)
            f.flush()
            m = load_manifest_from_json(f.name)
        Path(f.name).unlink(missing_ok=True)
        assert m.name == "example-tool"

    def test_load_auto_detect_yaml(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(VALID_MANIFEST_DICT, f)
            f.flush()
            m = load_manifest(f.name)
        Path(f.name).unlink(missing_ok=True)
        assert m.name == "example-tool"

    def test_load_auto_detect_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(VALID_MANIFEST_DICT, f)
            f.flush()
            m = load_manifest(f.name)
        Path(f.name).unlink(missing_ok=True)
        assert m.name == "example-tool"

    def test_missing_file_raises(self):
        with pytest.raises(ManifestLoadError, match="not found"):
            load_manifest("/nonexistent/path.yaml")

    def test_unknown_extension_raises(self):
        with pytest.raises(ManifestLoadError, match="Unknown manifest format"):
            load_manifest("/path/to/manifest.txt")


class TestManifestVerification:
    """Digest and signature verification."""

    def test_valid_digest_passes(self):
        m = load_manifest_from_dict(VALID_MANIFEST_DICT)
        verify_digest(m)

    def test_missing_digest_rejected(self):
        data = {**VALID_MANIFEST_DICT, "package_digest": ""}
        m = load_manifest_from_dict(data)
        with pytest.raises(ManifestVerificationError, match="package_digest is required"):
            verify_digest(m)

    def test_invalid_hex_digest_rejected(self):
        data = {**VALID_MANIFEST_DICT, "package_digest": "zzz" * 21 + "aa"}
        m = load_manifest_from_dict(data)
        with pytest.raises(ManifestVerificationError, match="not valid hex"):
            verify_digest(m)

    def test_wrong_length_digest_rejected(self):
        data = {**VALID_MANIFEST_DICT, "package_digest": "abcdef" * 10}  # 60 chars, not 64
        m = load_manifest_from_dict(data)
        with pytest.raises(ManifestVerificationError, match="64 hex chars"):
            verify_digest(m)

    def test_content_digest_mismatch_rejected(self):
        m = load_manifest_from_dict(VALID_MANIFEST_DICT)
        fake_bytes = b"not the real package"
        with pytest.raises(ManifestVerificationError, match="digest mismatch"):
            verify_digest(m, actual_package_bytes=fake_bytes)

    def test_content_digest_match_passes(self):
        import hashlib
        content = b"real package content"
        digest = hashlib.sha256(content).hexdigest()
        data = {**VALID_MANIFEST_DICT, "package_digest": digest}
        m = load_manifest_from_dict(data)
        verify_digest(m, actual_package_bytes=content)

    def test_unsigned_external_rejected_in_strict(self):
        m = load_manifest_from_dict(VALID_MANIFEST_DICT)
        with pytest.raises(ManifestVerificationError, match="strict mode requires a signature"):
            verify_signature(m, strict=True)

    def test_unsigned_external_allowed_in_non_strict(self):
        m = load_manifest_from_dict(VALID_MANIFEST_DICT)
        verify_signature(m, strict=False)  # should not raise

    def test_signature_without_key_id_rejected_in_strict(self):
        data = {**VALID_MANIFEST_DICT, "signature": "base64signature=="}
        m = load_manifest_from_dict(data)
        with pytest.raises(ManifestVerificationError, match="signing_key_id is missing"):
            verify_signature(m, strict=True)

    def test_manifest_digest_is_deterministic(self):
        m1 = load_manifest_from_dict(VALID_MANIFEST_DICT)
        m2 = load_manifest_from_dict(VALID_MANIFEST_DICT)
        assert compute_manifest_digest(m1) == compute_manifest_digest(m2)

    def test_manifest_digest_changes_with_content(self):
        m1 = load_manifest_from_dict(VALID_MANIFEST_DICT)
        data = {**VALID_MANIFEST_DICT, "version": "2.0.0"}
        m2 = load_manifest_from_dict(data)
        assert compute_manifest_digest(m1) != compute_manifest_digest(m2)


class TestPolicyCompiler:
    """Compiling manifest into ToolPolicy."""

    def test_local_source_gets_trusted(self):
        data = {**VALID_MANIFEST_DICT, "source": "local"}
        m = load_manifest_from_dict(data)
        policy = compile_policy(m)
        assert policy.trusted is True
        assert policy.runner == "auto"

    def test_registry_source_gets_container(self):
        m = load_manifest_from_dict(VALID_MANIFEST_DICT)
        policy = compile_policy(m)
        assert policy.runner == "container"
        assert policy.trusted is False
        assert policy.trusted_output is False

    def test_network_manifest_compiles_to_allowed_domains(self):
        data = {**VALID_MANIFEST_DICT, "risk": "network",
                "network": {"allowed_domains": ["api.example.com", "cdn.example.com"]}}
        m = load_manifest_from_dict(data)
        policy = compile_policy(m)
        assert "api.example.com" in policy.allowed_domains
        assert "network.public_http" in policy.capabilities

    def test_filesystem_manifest_compiles_to_workspace_root(self):
        m = load_manifest_from_dict(VALID_MANIFEST_DICT)
        policy = compile_policy(m)
        assert policy.workspace_root == Path("/workspace")
        assert "filesystem.read" in policy.capabilities
        assert policy.path_params

    def test_code_exec_requires_approval(self):
        data = {**VALID_MANIFEST_DICT, "risk": "code_exec",
                "capabilities": ["code.exec"]}
        m = load_manifest_from_dict(data)
        policy = compile_policy(m)
        assert policy.requires_approval is True

    def test_idempotent_propagates(self):
        data = {**VALID_MANIFEST_DICT, "idempotent": True}
        m = load_manifest_from_dict(data)
        policy = compile_policy(m)
        assert policy.idempotent is True


class TestPolicyLinter:
    """Lint rules enforcement."""

    def test_local_runner_for_external_denied(self):
        from seekflow.types import ToolPolicy
        policy = ToolPolicy(risk="read", runner="in_process")
        issues = lint_policy(policy, source="registry")
        assert has_errors(issues)
        assert any(i.code == "L001" for i in issues)

    def test_network_without_domains_denied(self):
        from seekflow.types import ToolPolicy
        policy = ToolPolicy(risk="network", capabilities={"network.public_http"})
        issues = lint_policy(policy, source="local")
        assert has_errors(issues)
        assert any(i.code == "L002" for i in issues)

    def test_filesystem_without_workspace_denied(self):
        from seekflow.types import ToolPolicy
        policy = ToolPolicy(risk="write", capabilities={"filesystem.write"})
        issues = lint_policy(policy, source="local")
        assert has_errors(issues)
        assert any(i.code == "L004" for i in issues)

    def test_wildcard_domain_denied(self):
        from seekflow.types import ToolPolicy
        policy = ToolPolicy(risk="network", allowed_domains={"*"},
                            capabilities={"network.public_http"})
        issues = lint_policy(policy, source="local")
        assert has_errors(issues)
        assert any(i.code == "L009" for i in issues)

    def test_non_fqdn_domain_denied(self):
        from seekflow.types import ToolPolicy
        policy = ToolPolicy(risk="network", allowed_domains={"com"},
                            capabilities={"network.public_http"})
        issues = lint_policy(policy, source="local")
        assert has_errors(issues)
        assert any(i.code == "L010" for i in issues)

    def test_trusted_output_for_external_denied(self):
        from seekflow.types import ToolPolicy
        policy = ToolPolicy(risk="read", trusted=True, trusted_output=True)
        issues = lint_policy(policy, source="registry")
        assert has_errors(issues)
        assert any(i.code == "L007" for i in issues)

    def test_code_exec_without_container_denied(self):
        from seekflow.types import ToolPolicy
        policy = ToolPolicy(risk="code_exec", capabilities={"code.exec"},
                            runner="process")
        issues = lint_policy(policy, source="local")
        assert has_errors(issues)
        assert any(i.code == "L006" for i in issues)

    def test_clean_policy_passes(self):
        from seekflow.types import ToolPolicy
        policy = ToolPolicy(
            risk="read",
            runner="container",
            capabilities={"filesystem.read"},
            workspace_root=Path("/tmp"),
            path_params=frozenset({"path"}),
        )
        issues = lint_policy(policy, source="registry")
        assert not has_errors(issues)


class TestRegistryIntegration:
    """End-to-end manifest → register pipeline."""

    def test_register_from_manifest_succeeds(self):
        m = load_manifest_from_dict(VALID_MANIFEST_DICT)
        reg = ToolRegistry()
        td = reg.register_from_manifest(m, strict=False)
        assert td.name == "example-tool"
        assert td.source == "registry"
        assert td.policy is not None
        assert td.policy.runner == "container"
        assert td.func is None  # external tools have no Python callable

    def test_register_from_manifest_rejects_bad_policy(self):
        from seekflow.errors import ToolSchemaError
        data = {
            **VALID_MANIFEST_DICT,
            "risk": "network",
            "capabilities": ["network.public_http"],
            # no allowed_domains
        }
        m = load_manifest_from_dict(data)
        reg = ToolRegistry()
        with pytest.raises(ToolSchemaError, match="failed policy lint"):
            reg.register_from_manifest(m, strict=False)

    def test_register_from_manifest_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(VALID_MANIFEST_DICT, f)
            f.flush()
            reg = ToolRegistry()
            td = reg.register_from_manifest_file(f.name, strict=False)
        Path(f.name).unlink(missing_ok=True)
        assert td.name == "example-tool"
        assert td.policy is not None
