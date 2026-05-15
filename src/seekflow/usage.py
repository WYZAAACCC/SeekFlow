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

    @property
    def cache_hit_ratio(self) -> float:
        if self.prompt_tokens <= 0:
            return 0.0
        return self.cache_hit_tokens / self.prompt_tokens

    @property
    def cache_miss_ratio(self) -> float:
        if self.prompt_tokens <= 0:
            return 0.0
        return self.cache_miss_tokens / self.prompt_tokens

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

    Reads from three possible locations (in priority order):
    1. Top-level fields (current DeepSeek API): prompt_cache_hit_tokens, prompt_cache_miss_tokens
    2. Nested fields (SDK object): prompt_tokens_details.prompt_cache_hit/miss_tokens
    3. Legacy field: prompt_tokens_details.cached_tokens
    Also reads completion_tokens_details.reasoning_tokens (current API).
    """
    if not usage:
        return NormalizedUsage()

    prompt = int(usage.get("prompt_tokens", 0) or 0)
    completion = int(usage.get("completion_tokens", 0) or 0)
    total = int(usage.get("total_tokens", prompt + completion) or 0)

    # Try top-level fields first (current API), then nested (SDK), then legacy
    details = usage.get("prompt_tokens_details", {}) or {}
    completion_details = usage.get("completion_tokens_details", {}) or {}

    hit = (
        usage.get("prompt_cache_hit_tokens")
        or details.get("prompt_cache_hit_tokens")
        or details.get("cached_tokens")
        or 0
    )
    miss = (
        usage.get("prompt_cache_miss_tokens")
        or details.get("prompt_cache_miss_tokens")
    )
    if miss is None:
        miss = max(prompt - int(hit or 0), 0)

    reasoning = (
        completion_details.get("reasoning_tokens")
        or details.get("reasoning_tokens")
        or 0
    )

    return NormalizedUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cache_hit_tokens=int(hit or 0),
        cache_miss_tokens=int(miss or 0),
        reasoning_tokens=int(reasoning or 0),
    )
