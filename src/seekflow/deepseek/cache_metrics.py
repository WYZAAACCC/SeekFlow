"""DeepSeek Context Cache metrics — hit/miss token tracking.

DeepSeek context cache is prefix-unit based, best-effort, and enabled by default.
Cache status is reported via prompt_cache_hit_tokens / prompt_cache_miss_tokens.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class CacheMetrics:
    """Cache hit/miss token counts from a DeepSeek API response."""

    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0

    @property
    def total_prompt_cache_tokens(self) -> int:
        return self.prompt_cache_hit_tokens + self.prompt_cache_miss_tokens

    @property
    def hit_ratio(self) -> float:
        total = self.total_prompt_cache_tokens
        if total == 0:
            return 0.0
        return self.prompt_cache_hit_tokens / total


def extract_cache_metrics(usage: dict) -> CacheMetrics:
    """Extract cache metrics from a usage dict (handles both new and legacy fields)."""
    hit = int(usage.get("prompt_cache_hit_tokens", 0) or 0)
    miss = int(usage.get("prompt_cache_miss_tokens", 0) or 0)

    if hit == 0 and miss == 0:
        details = usage.get("prompt_tokens_details", {}) or {}
        hit = int(details.get("prompt_cache_hit_tokens", 0) or 0)
        miss = int(details.get("prompt_cache_miss_tokens", 0) or 0)
        if hit == 0 and miss == 0:
            hit = int(details.get("cached_tokens", 0) or 0)
            miss = max(int(usage.get("prompt_tokens", 0) or 0) - hit, 0)

    return CacheMetrics(
        prompt_cache_hit_tokens=hit,
        prompt_cache_miss_tokens=miss,
    )


def canonical_json(obj: Any) -> str:
    """Serialize to deterministic JSON for cache stability."""
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def canonicalize_tools(tools: list[dict]) -> list[dict]:
    """Sort tools by function name for deterministic cache prefix."""
    return sorted(tools, key=lambda t: t["function"]["name"])
