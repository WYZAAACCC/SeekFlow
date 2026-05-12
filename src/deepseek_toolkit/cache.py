"""Prompt cache observation and prefix-change detection.

DeepSeek automatically caches the longest matching prefix of sequential
requests. This module helps users understand and not break that cache.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CacheAdvice:
    status: str  # "first_request", "stable", "changed"
    message: str = ""


class CacheSentinel:
    """Detects prefix changes that would invalidate the prompt cache."""

    def __init__(self):
        self._prefix_hash: int | None = None

    def check(self, messages: list[dict]) -> CacheAdvice:
        prefix = self._extract_prefix(messages)
        h = hash(prefix)
        if self._prefix_hash is None:
            self._prefix_hash = h
            return CacheAdvice("first_request", "Cache baseline established.")
        if h != self._prefix_hash:
            self._prefix_hash = h
            return CacheAdvice(
                "changed",
                "Cache prefix changed — cache invalidated. "
                "Keep system message stable for best cache performance.",
            )
        return CacheAdvice("stable", "Cache prefix matches previous request.")

    @staticmethod
    def _extract_prefix(messages: list[dict]) -> tuple:
        """Extract cacheable prefix: system messages only.

        DeepSeek caches the longest matching prefix starting from the first
        message. Only system messages form the stable cacheable prefix —
        user messages change every call.
        """
        return tuple(
            (m.get("role"), m.get("content"))
            for m in messages
            if m.get("role") == "system"
        )


def extract_cached_tokens(usage: dict) -> int:
    """Extract cached token count from usage dict."""
    details = usage.get("prompt_tokens_details", {}) or {}
    return details.get("cached_tokens", 0)
