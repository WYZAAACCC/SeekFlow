"""Durable audit store — append-only JSONL and SQLite backends.

Lv3 requirement: all tool executions must leave an append-only,
hash-chained, tamper-evident audit trail.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from seekflow.audit.model import AuditEvent


class AuditStoreError(RuntimeError):
    """Raised when audit operations fail."""


class JSONLAuditStore:
    """Append-only JSONL audit backend.

    Each line is a complete AuditEvent JSON object. The file is opened
    in append mode and each write is flushed immediately.
    """

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._last_hash: str | None = None

        # Load last hash from existing file
        if self._path.exists():
            self._last_hash = self._read_last_hash()

    def append(self, event: AuditEvent) -> AuditEvent:
        """Append an event to the audit log, updating the hash chain.

        Returns the event with prev_hash and event_hash populated.
        """
        # Compute hash chain
        event.prev_hash = self._last_hash
        event.event_hash = _compute_event_hash(event)

        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(event.model_dump_json(exclude_none=True))
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:
            raise AuditStoreError(f"Failed to write audit event: {e}") from e

        self._last_hash = event.event_hash
        return event

    def read_all(self) -> list[dict]:
        """Read all audit events from the log."""
        if not self._path.exists():
            return []
        events = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    def _read_last_hash(self) -> str | None:
        """Read the last event_hash from the existing log."""
        try:
            with open(self._path, "rb") as f:
                f.seek(0, os.SEEK_END)
                if f.tell() == 0:
                    return None
                # Seek backwards to find last line
                f.seek(max(0, f.tell() - 4096))
                lines = f.read().decode("utf-8", errors="replace").strip().splitlines()
                if lines:
                    last = json.loads(lines[-1])
                    return last.get("event_hash")
        except Exception:
            pass
        return None


class SQLiteAuditStore:
    """SQLite WAL-mode audit backend.

    Provides indexed queries while maintaining append-only semantics.
    """

    def __init__(self, path: str | Path):
        self._path = str(path)
        self._conn: sqlite3.Connection | None = None
        self._last_hash: str | None = None

    def _ensure_table(self) -> None:
        if self._conn is None:
            self._conn = sqlite3.connect(self._path)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL,
                    ts TEXT NOT NULL,
                    run_id TEXT,
                    step INTEGER,
                    event_type TEXT,
                    tool_name TEXT,
                    tool_version TEXT,
                    tool_digest TEXT,
                    manifest_digest TEXT,
                    policy_digest TEXT,
                    input_hash TEXT,
                    output_hash TEXT,
                    runner TEXT,
                    sandbox_image_digest TEXT,
                    prev_hash TEXT,
                    event_hash TEXT NOT NULL,
                    ok INTEGER,
                    error TEXT,
                    elapsed_ms INTEGER,
                    payload_json TEXT
                )
            """)
            self._conn.commit()

            # Load last hash
            row = self._conn.execute(
                "SELECT event_hash FROM audit_events ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row:
                self._last_hash = row[0]

    def append(self, event: AuditEvent) -> AuditEvent:
        """Append an event, updating the hash chain."""
        self._ensure_table()

        event.prev_hash = self._last_hash
        event.event_hash = _compute_event_hash(event)

        payload = event.model_dump_json(exclude_none=True)
        self._conn.execute(
            """INSERT INTO audit_events
               (event_id, ts, run_id, step, event_type, tool_name, tool_version,
                tool_digest, manifest_digest, policy_digest, input_hash, output_hash,
                runner, sandbox_image_digest, prev_hash, event_hash, ok, error,
                elapsed_ms, payload_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event.event_id, event.ts.isoformat(), event.run_id, event.step,
                event.event_type, event.tool_name, event.tool_version,
                event.tool_digest, event.manifest_digest, event.policy_digest,
                event.input_hash, event.output_hash, event.runner,
                event.sandbox_image_digest, event.prev_hash, event.event_hash,
                int(event.ok), event.error, event.elapsed_ms, payload,
            ),
        )
        self._conn.commit()

        self._last_hash = event.event_hash
        return event

    def query_by_run(self, run_id: str) -> list[dict]:
        """Query all audit events for a run_id."""
        self._ensure_table()
        rows = self._conn.execute(
            "SELECT payload_json FROM audit_events WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


def verify_audit_chain(events: list[dict]) -> tuple[bool, str]:
    """Verify the hash chain of a list of audit event dicts.

    Returns (valid, message). Each event's event_hash must match the
    computed hash, and each event's prev_hash must match the previous
    event's event_hash.
    """
    prev_hash: str | None = None
    for i, event in enumerate(events):
        # Check prev_hash consistency
        expected_prev = prev_hash
        actual_prev = event.get("prev_hash")
        if expected_prev != actual_prev:
            return False, (
                f"Chain break at event {i}: expected prev_hash={expected_prev}, "
                f"got prev_hash={actual_prev}"
            )

        # Check event_hash integrity
        computed = _compute_event_hash_from_dict(event)
        actual = event.get("event_hash", "")
        if computed != actual:
            return False, (
                f"Tamper detected at event {i}: "
                f"expected event_hash={computed}, got event_hash={actual}"
            )

        prev_hash = event.get("event_hash")

    return True, "Chain valid"


def _compute_event_hash(event: AuditEvent) -> str:
    """Compute the SHA-256 hash of an audit event's content.

    Uses model_dump(mode="json", exclude_none=True) to match the
    serialization in JSONLAuditStore.append() — this ensures that
    re-reading a stored event produces the same hash.
    """
    return _compute_event_hash_from_dict(
        event.model_dump(mode="json", exclude={"event_hash"}, exclude_none=True)
    )


def _compute_event_hash_from_dict(data: dict) -> str:
    """Compute SHA-256 from a dict, excluding event_hash and signature."""
    data_copy = {k: v for k, v in data.items() if k not in ("event_hash", "signature")}
    canonical = json.dumps(data_copy, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
