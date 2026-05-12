"""LRU+TTL cache for tool call results."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict

from deepseek_toolkit.types import ToolExecutionResult


def make_cache_key(tool_name: str, arguments: dict) -> str:
    """Create a deterministic cache key from tool name and arguments.

    Arguments are sorted by key for order-independent matching.
    """
    canonical = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
    raw = f"{tool_name}:{canonical}"
    return hashlib.sha256(raw.encode()).hexdigest()


class ToolCallCache:
    """LRU cache with optional TTL for ToolExecutionResult values."""

    def __init__(self, max_size: int = 128, ttl: float | None = None):
        self._max_size = max_size
        self._ttl = ttl
        self._store: OrderedDict[str, tuple[float, ToolExecutionResult]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> ToolExecutionResult | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            ts, value = entry
            if self._ttl is not None and time.monotonic() - ts > self._ttl:
                del self._store[key]
                self._misses += 1
                return None
            self._store.move_to_end(key)
            self._hits += 1
            return value

    def put(self, key: str, value: ToolExecutionResult) -> None:
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            elif len(self._store) >= self._max_size:
                self._store.popitem(last=False)  # LRU eviction
            self._store[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    @property
    def hit_rate(self) -> float:
        with self._lock:
            total = self._hits + self._misses
            return self._hits / total if total > 0 else 0.0

    @property
    def stats(self) -> dict:
        with self._lock:
            total = self._hits + self._misses
            return {
                "hits": self._hits,
                "misses": self._misses,
                "ratio": self._hits / total if total > 0 else 0.0,
            }
