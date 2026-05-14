"""Normalized usage — single source of truth for DeepSeek token consumption."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedUsage:
    """Token usage normalized across old and new DeepSeek API fields."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cache_hit_tokens: int = 0
    cache_miss_tokens: int = 0
    reasoning_tokens: int = 0

    def add(self, other: NormalizedUsage) -> NormalizedUsage:
        return NormalizedUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            cache_hit_tokens=self.cache_hit_tokens + other.cache_hit_tokens,
            cache_miss_tokens=self.cache_miss_tokens + other.cache_miss_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
        )

    def to_dict(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "prompt_tokens_details": {
                "prompt_cache_hit_tokens": self.cache_hit_tokens,
                "prompt_cache_miss_tokens": self.cache_miss_tokens,
                "cached_tokens": self.cache_hit_tokens,
                "reasoning_tokens": self.reasoning_tokens,
            },
        }


def normalize_usage(usage: dict | None) -> NormalizedUsage:
    """Convert a raw DeepSeek usage dict to NormalizedUsage.

    Handles both current API (prompt_cache_hit_tokens / prompt_cache_miss_tokens)
    and legacy API (cached_tokens).
    """
    if not usage:
        return NormalizedUsage()

    prompt = int(usage.get("prompt_tokens", 0) or 0)
    completion = int(usage.get("completion_tokens", 0) or 0)
    total = int(usage.get("total_tokens", prompt + completion) or 0)

    details = usage.get("prompt_tokens_details", {}) or {}

    hit = int(
        details.get("prompt_cache_hit_tokens")
        or details.get("cached_tokens")
        or 0
    )
    miss = int(
        details.get("prompt_cache_miss_tokens")
        if details.get("prompt_cache_miss_tokens") is not None
        else max(prompt - hit, 0)
    )
    reasoning = int(details.get("reasoning_tokens", 0) or 0)

    return NormalizedUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cache_hit_tokens=hit,
        cache_miss_tokens=miss,
        reasoning_tokens=reasoning,
    )
