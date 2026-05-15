"""PR-9: CLI — seekflow tool inspect/verify/install/list/audit tests."""
import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest
import yaml
from typer.testing import CliRunner

from seekflow.cli import app


VALID_MANIFEST = {
    "name": "cli-test-tool",
    "version": "1.0.0",
    "source": "registry",
    "package_digest": "a" * 64,
    "entrypoint": {"command": "python", "args": ["/tool/main.py"]},
    "input_schema": {"type": "object", "properties": {}},
}

runner = CliRunner()


class TestToolInspect:
    """seekflow tool inspect."""

    def test_inspect_valid_manifest(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(VALID_MANIFEST, f)
            f.flush()
            result = runner.invoke(app, ["tool", "inspect", f.name])
        Path(f.name).unlink(missing_ok=True)
        assert result.exit_code == 0
        assert "cli-test-tool" in result.stdout
        assert "1.0.0" in result.stdout

    def test_inspect_missing_file(self):
        result = runner.invoke(app, ["tool", "inspect", "/nonexistent.yaml"])
        assert result.exit_code == 1

    def test_inspect_shows_sandbox(self):
        data = {**VALID_MANIFEST, "sandbox": {"runner": "container", "image": "python:3.11-slim"}}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(data, f)
            f.flush()
            result = runner.invoke(app, ["tool", "inspect", f.name])
        Path(f.name).unlink(missing_ok=True)
        assert result.exit_code == 0
        assert "container" in result.stdout


class TestToolVerify:
    """seekflow tool verify."""

    def test_verify_valid_manifest(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(VALID_MANIFEST, f)
            f.flush()
            result = runner.invoke(app, ["tool", "verify", f.name])
        Path(f.name).unlink(missing_ok=True)
        assert result.exit_code == 0
        assert "verified" in result.stdout.lower()

    def test_verify_strict_unsigned_external_rejected(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(VALID_MANIFEST, f)
            f.flush()
            result = runner.invoke(app, ["tool", "verify", f.name, "--strict"])
        Path(f.name).unlink(missing_ok=True)
        assert result.exit_code == 1
        assert "signature" in result.stdout.lower() or "FAIL" in result.stdout

    def test_verify_malformed_manifest(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("{invalid yaml!!!")
            f.flush()
            result = runner.invoke(app, ["tool", "verify", f.name])
        Path(f.name).unlink(missing_ok=True)
        assert result.exit_code == 1


class TestToolInstall:
    """seekflow tool install."""

    def test_install_dry_run_passes(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(VALID_MANIFEST, f)
            f.flush()
            result = runner.invoke(app, ["tool", "install", f.name, "--dry-run"])
        Path(f.name).unlink(missing_ok=True)
        assert result.exit_code == 0
        assert "Dry-run" in result.stdout or "verified" in result.stdout.lower()

    def test_install_rejects_bad_policy(self):
        data = {**VALID_MANIFEST, "risk": "network", "capabilities": ["network.public_http"]}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(data, f)
            f.flush()
            # network without allowed_domains should be rejected by linter
            result = runner.invoke(app, ["tool", "install", f.name, "--dry-run"])
        Path(f.name).unlink(missing_ok=True)
        assert result.exit_code == 1
        assert "L002" in result.stdout or "FAIL" in result.stdout

    def test_install_missing_digest_rejected(self):
        data = {**VALID_MANIFEST, "package_digest": ""}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(data, f)
            f.flush()
            result = runner.invoke(app, ["tool", "install", f.name, "--dry-run"])
        Path(f.name).unlink(missing_ok=True)
        assert result.exit_code == 1


class TestToolList:
    """seekflow tool list."""

    def test_list_empty(self):
        # Ensure clean state
        result = runner.invoke(app, ["tool", "list"])
        # Should not crash
        assert result.exit_code == 0

    def test_list_after_install(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(VALID_MANIFEST, f)
            f.flush()
            install_result = runner.invoke(app, ["tool", "install", f.name])
            list_result = runner.invoke(app, ["tool", "list"])
        Path(f.name).unlink(missing_ok=True)
        # Install may succeed or fail (depends on env), but list should not crash
        assert list_result.exit_code == 0


class TestAuditCLI:
    """seekflow audit verify/export."""

    def test_audit_verify_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            pass  # empty file
        try:
            result = runner.invoke(app, ["audit", "verify", f.name])
            assert result.exit_code == 0  # empty = no tampering
        finally:
            Path(f.name).unlink(missing_ok=True)

    def test_audit_verify_missing_file(self):
        result = runner.invoke(app, ["audit", "verify", "/nonexistent.jsonl"])
        assert result.exit_code == 1

    def test_audit_verify_valid_chain(self):
        from seekflow.audit.store import JSONLAuditStore
        from seekflow.audit.model import AuditEvent
        import uuid

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            store = JSONLAuditStore(path)
            for i in range(3):
                store.append(AuditEvent(
                    event_id=uuid.uuid4().hex,
                    run_id="test-run",
                    step=i,
                    event_type="tool_execution",
                    tool_name="echo",
                    ok=True,
                ))

            result = runner.invoke(app, ["audit", "verify", path])
            assert result.exit_code == 0
            assert "valid" in result.stdout.lower()
        finally:
            Path(path).unlink(missing_ok=True)

    def test_audit_verify_tampered_chain(self):
        from seekflow.audit.store import JSONLAuditStore
        from seekflow.audit.model import AuditEvent
        import uuid

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            store = JSONLAuditStore(path)
            for i in range(3):
                store.append(AuditEvent(
                    event_id=uuid.uuid4().hex,
                    run_id="test-run",
                    step=i,
                    event_type="tool_execution",
                    tool_name="echo",
                    ok=True,
                ))

            # Tamper: overwrite second event
            lines = Path(path).read_text(encoding="utf-8").strip().split("\n")
            event = json.loads(lines[1])
            event["tool_name"] = "tampered-tool"
            lines[1] = json.dumps(event)
            Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")

            result = runner.invoke(app, ["audit", "verify", path])
            assert result.exit_code == 1
            assert "Tamper" in result.stdout or "FAIL" in result.stdout
        finally:
            Path(path).unlink(missing_ok=True)

    def test_audit_export_jsonl(self):
        from seekflow.audit.store import JSONLAuditStore
        from seekflow.audit.model import AuditEvent
        import uuid

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            store = JSONLAuditStore(path)
            store.append(AuditEvent(
                event_id=uuid.uuid4().hex,
                run_id="export-test",
                step=0,
                event_type="tool_execution",
                tool_name="echo",
                ok=True,
            ))

            result = runner.invoke(app, ["audit", "export", path, "--run-id", "export-test"])
            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert len(data) == 1
            assert data[0]["run_id"] == "export-test"
        finally:
            Path(path).unlink(missing_ok=True)
