"""Lightweight Agent Memory — short-term + long-term, zero external deps.

Unlike CrewAI's LanceDB-based memory (heavy), this uses pure Python
with cosine similarity over simple character-n-gram vectors.
Fast enough for < 10K stored memories, no database required.
"""
from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryItem:
    """A single stored memory."""
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)
    access_count: int = 0
    importance: float = 0.5  # 0.0-1.0


class AgentMemory:
    """Short-term + long-term memory for Agents.

    Short-term: sliding window of last N interactions.
    Long-term: vector-indexed persistent memories with retrieval.

    Usage:
        memory = AgentMemory(short_term_size=10)
        memory.remember("User prefers short answers")
        relevant = memory.recall("user preferences", top_k=3)
    """

    def __init__(self, short_term_size: int = 10, long_term_max: int = 1000):
        self._short_term: list[dict] = []
        self._short_term_size = short_term_size
        self._long_term: list[MemoryItem] = []
        self._long_term_max = long_term_max

    # ── Short-term ──────────────────────────────────────────────

    def add_interaction(self, role: str, content: str) -> None:
        """Add a conversation turn to short-term memory."""
        self._short_term.append({
            "role": role,
            "content": content[:2000],
            "timestamp": time.time(),
        })
        if len(self._short_term) > self._short_term_size:
            # Evict oldest to long-term
            evicted = self._short_term.pop(0)
            self.remember(
                f"[{evicted['role']}]: {evicted['content'][:500]}",
                importance=0.3,
            )

    def recent(self, n: int | None = None) -> list[dict]:
        """Return recent interactions."""
        n = n or self._short_term_size
        return self._short_term[-n:]

    # ── Long-term ───────────────────────────────────────────────

    def remember(self, content: str, metadata: dict | None = None,
                 importance: float = 0.5) -> None:
        """Store a fact in long-term memory, consolidating duplicates."""
        # Consolidation only for near-exact matches (cosine > 0.99)
        for item in self._long_term:
            if self._cosine(self._text_vector(content), self._text_vector(item.content)) > 0.99:
                item.access_count += 1
                item.importance = max(item.importance, importance)
                return  # Consolidated, don't add duplicate

        item = MemoryItem(
            content=content,
            metadata=metadata or {},
            importance=importance,
        )
        self._long_term.append(item)
        if len(self._long_term) > self._long_term_max:
            # Evict least important
            self._long_term.sort(key=lambda m: m.importance * (1 + m.access_count * 0.1))
            self._long_term.pop(0)

    def recall(self, query: str, top_k: int = 5,
               min_importance: float = 0.0) -> list[str]:
        """Retrieve relevant memories by semantic similarity."""
        if not self._long_term:
            return []

        query_vec = self._text_vector(query)
        scored = []
        for item in self._long_term:
            if item.importance < min_importance:
                continue
            item_vec = self._text_vector(item.content)
            sim = self._cosine(query_vec, item_vec)
            scored.append((sim * (0.5 + 0.5 * item.importance), item))
        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, item in scored[:top_k]:
            item.access_count += 1
            results.append(item.content)
        return results

    def forget(self, content: str) -> bool:
        """Remove a specific memory by exact content match."""
        for i, item in enumerate(self._long_term):
            if item.content == content:
                self._long_term.pop(i)
                return True
        return False

    def flush_to_long_term(self) -> int:
        """Transfer all short-term memories to long-term. Returns count transferred."""
        count = 0
        for item in self._short_term:
            self.remember(
                f"[{item['role']}]: {item['content'][:500]}",
                importance=0.5,
            )
            count += 1
        self._short_term.clear()
        return count

    def clear(self) -> None:
        """Clear all memories."""
        self._short_term.clear()
        self._long_term.clear()

    def stats(self) -> dict:
        """Return memory statistics."""
        return {
            "short_term_items": len(self._short_term),
            "long_term_items": len(self._long_term),
            "total_stored": len(self._long_term),
        }

    # ── Vector utils (zero-dependency, char-n-gram based) ──────

    @staticmethod
    def _text_vector(text: str, dim: int = 128) -> list[float]:
        """Convert text to a fixed-dimension vector using character trigrams."""
        vec = [0.0] * dim
        text = text.lower()
        for i in range(len(text) - 2):
            trigram = text[i:i + 3]
            idx = int(hashlib.md5(trigram.encode()).hexdigest(), 16) % dim
            vec[idx] += 1.0
        # Normalize
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        return max(0.0, min(1.0, dot))  # vectors are normalized
