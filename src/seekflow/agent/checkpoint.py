"""Checkpoint — Agent execution state save/resume."""
from __future__ import annotations

import json
import sqlite3
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentCheckpoint:
    """Snapshot of Agent execution state."""
    thread_id: str
    step: int = 0
    messages: list[dict] = field(default_factory=list)
    tool_calls_completed: list[str] = field(default_factory=list)
    timestamp: str = ""
    agent_state: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")


class CheckpointStore(ABC):
    """Abstract checkpoint persistence."""

    @abstractmethod
    def save(self, checkpoint: AgentCheckpoint) -> None: ...

    @abstractmethod
    def load(self, thread_id: str) -> AgentCheckpoint | None: ...

    @abstractmethod
    def delete(self, thread_id: str) -> None: ...

    @abstractmethod
    def list(self, limit: int = 10) -> list[AgentCheckpoint]: ...


class InMemoryStore(CheckpointStore):
    """Dict-based checkpoint store (default)."""

    def __init__(self):
        self._data: dict[str, AgentCheckpoint] = {}

    def save(self, checkpoint: AgentCheckpoint) -> None:
        self._data[checkpoint.thread_id] = checkpoint

    def load(self, thread_id: str) -> AgentCheckpoint | None:
        return self._data.get(thread_id)

    def delete(self, thread_id: str) -> None:
        self._data.pop(thread_id, None)

    def list(self, limit: int = 10) -> list[AgentCheckpoint]:
        items = sorted(
            self._data.values(),
            key=lambda c: c.timestamp,
            reverse=True,
        )
        return items[:limit]


class SqliteStore(CheckpointStore):
    """SQLite-based persistent checkpoint store (zero dependencies)."""

    def __init__(self, db_path: str = "checkpoints.db"):
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS checkpoints "
            "(thread_id TEXT PRIMARY KEY, step INTEGER, "
            "messages_json TEXT, tool_calls_json TEXT, "
            "agent_state_json TEXT, timestamp TEXT)"
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def __del__(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def save(self, checkpoint: AgentCheckpoint) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO checkpoints VALUES (?, ?, ?, ?, ?, ?)",
            (
                checkpoint.thread_id, checkpoint.step,
                json.dumps(checkpoint.messages, ensure_ascii=False),
                json.dumps(checkpoint.tool_calls_completed),
                json.dumps(checkpoint.agent_state, ensure_ascii=False),
                checkpoint.timestamp,
            ),
        )
        self._conn.commit()

    def load(self, thread_id: str) -> AgentCheckpoint | None:
        row = self._conn.execute(
            "SELECT * FROM checkpoints WHERE thread_id = ?", (thread_id,)
        ).fetchone()
        if row is None:
            return None
        return AgentCheckpoint(
            thread_id=row[0], step=row[1],
            messages=json.loads(row[2]),
            tool_calls_completed=json.loads(row[3]),
            agent_state=json.loads(row[4]),
            timestamp=row[5],
        )

    def delete(self, thread_id: str) -> None:
        self._conn.execute(
            "DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,)
        )
        self._conn.commit()

    def list(self, limit: int = 10) -> list[AgentCheckpoint]:
        rows = self._conn.execute(
            "SELECT * FROM checkpoints ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            AgentCheckpoint(
                thread_id=r[0], step=r[1],
                messages=json.loads(r[2]),
                tool_calls_completed=json.loads(r[3]),
                agent_state=json.loads(r[4]),
                timestamp=r[5],
            )
            for r in rows
        ]
