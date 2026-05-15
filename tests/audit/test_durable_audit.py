"""Phase F: DurableAuditStore — append-only, hash-chained audit tests."""
import json
import os
import tempfile
import uuid
from pathlib import Path

import pytest

from seekflow.audit.model import AuditEvent, EgressAudit
from seekflow.audit.store import (
    JSONLAuditStore, SQLiteAuditStore,
    verify_audit_chain, _compute_event_hash_from_dict,
)


def _make_event(run_id: str = "run-1", step: int = 0, **overrides) -> AuditEvent:
    data = {
        "event_id": uuid.uuid4().hex,
        "run_id": run_id,
        "step": step,
        "event_type": "tool_execution",
        "tool_name": "echo",
        "tool_version": "1.0.0",
        "tool_digest": "sha256:abc",
        "input_hash": "abc123",
        "output_hash": "def456",
        "runner": "external_container",
        "sandbox_image_digest": "sha256:xyz",
        "ok": True,
        "elapsed_ms": 100,
        **overrides,
    }
    return AuditEvent(**data)


class TestAuditEvent:
    """AuditEvent model."""

    def test_event_has_required_fields(self):
        event = _make_event()
        assert event.event_id
        assert event.ts is not None
        assert event.event_hash == ""  # computed by store

    def test_event_includes_tool_identity(self):
        event = _make_event()
        assert event.tool_name == "echo"
        assert event.tool_version == "1.0.0"
        assert event.tool_digest == "sha256:abc"
        assert event.manifest_digest is None

    def test_event_includes_egress_audit(self):
        egress = EgressAudit(url="https://api.example.com", domain="api.example.com")
        event = _make_event(egress=[egress])
        assert len(event.egress) == 1
        assert event.egress[0].domain == "api.example.com"

    def test_event_includes_secret_refs(self):
        event = _make_event(secret_refs=["DB_PASSWORD"])
        assert "DB_PASSWORD" in event.secret_refs


class TestJSONLAuditStore:
    """JSONL append-only audit store."""

    def test_append_writes_event(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            store = JSONLAuditStore(path)
            event = _make_event()
            result = store.append(event)

            assert result.event_hash
            assert result.prev_hash is None  # first event

            events = store.read_all()
            assert len(events) == 1
            assert events[0]["tool_name"] == "echo"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_hash_chain_is_continuous(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            store = JSONLAuditStore(path)
            e1 = store.append(_make_event(run_id="run-1", step=0))
            e2 = store.append(_make_event(run_id="run-1", step=1))

            assert e2.prev_hash == e1.event_hash
            assert e1.event_hash != e2.event_hash

            events = store.read_all()
            assert events[0]["event_hash"] == e1.event_hash
            assert events[1]["prev_hash"] == e1.event_hash
        finally:
            Path(path).unlink(missing_ok=True)

    def test_tamper_detection(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            store = JSONLAuditStore(path)
            store.append(_make_event(run_id="run-1", step=0))
            store.append(_make_event(run_id="run-1", step=1))

            events = store.read_all()
            valid, msg = verify_audit_chain(events)
            assert valid, msg

            # Tamper with event 1's output_hash
            events[1]["output_hash"] = "tampered"
            valid, msg = verify_audit_chain(events)
            assert not valid
            assert "Tamper detected" in msg
        finally:
            Path(path).unlink(missing_ok=True)

    def test_chain_break_detected(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name

        try:
            store = JSONLAuditStore(path)
            store.append(_make_event(run_id="run-1", step=0))
            store.append(_make_event(run_id="run-1", step=1))

            events = store.read_all()
            # Break the chain
            events[1]["prev_hash"] = "broken"
            valid, msg = verify_audit_chain(events)
            assert not valid
            assert "Chain break" in msg
        finally:
            Path(path).unlink(missing_ok=True)

    def test_event_hash_excludes_signature(self):
        """event_hash is computed without the signature field."""
        data = _make_event().model_dump(mode="json")
        data["signature"] = "base64sig"
        h1 = _compute_event_hash_from_dict(data)
        del data["signature"]
        h2 = _compute_event_hash_from_dict(data)
        assert h1 == h2  # signature shouldn't affect hash

    def test_empty_store_reads_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            store = JSONLAuditStore(path)
            assert store.read_all() == []
        finally:
            Path(path).unlink(missing_ok=True)


class TestSQLiteAuditStore:
    """SQLite WAL-mode audit store."""

    def test_append_and_query(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name

        try:
            store = SQLiteAuditStore(path)
            event = _make_event(run_id="run-sqlite-1", step=0)
            result = store.append(event)

            assert result.event_hash
            events = store.query_by_run("run-sqlite-1")
            assert len(events) == 1
            assert events[0]["tool_name"] == "echo"
            store.close()
        finally:
            Path(path).unlink(missing_ok=True)

    def test_query_by_run_filters_correctly(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name

        try:
            store = SQLiteAuditStore(path)
            store.append(_make_event(run_id="run-a", step=0))
            store.append(_make_event(run_id="run-b", step=0))
            store.append(_make_event(run_id="run-a", step=1))

            events_a = store.query_by_run("run-a")
            assert len(events_a) == 2
            events_b = store.query_by_run("run-b")
            assert len(events_b) == 1
            store.close()
        finally:
            Path(path).unlink(missing_ok=True)

    def test_hash_chain_across_events(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = f.name

        try:
            store = SQLiteAuditStore(path)
            e1 = store.append(_make_event(run_id="run-1", step=0))
            e2 = store.append(_make_event(run_id="run-1", step=1))

            assert e2.prev_hash == e1.event_hash
            store.close()
        finally:
            Path(path).unlink(missing_ok=True)
