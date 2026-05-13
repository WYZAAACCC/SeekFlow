"""Cost tracking for DeepSeek API calls.

Pricing as of 2026-05, in CNY per 1M tokens.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# CNY per 1M tokens
PRICING: dict[str, dict] = {
    "deepseek-v4-pro": {
        "input": 1.74,
        "output": 3.48,
        "cached_input": 0.028,
        "unit": "CNY/1M",
    },
    "deepseek-v4-flash": {
        "input": 0.14,
        "output": 0.28,
        "cached_input": 0.002,
        "unit": "CNY/1M",
    },
}

_DEFAULT_MODEL = "deepseek-v4-pro"


@dataclass
class CostEntry:
    model: str
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    cost: float


class CostTracker:
    """Tracks cumulative API cost across calls."""

    def __init__(self):
        self.history: list[CostEntry] = []
        self._total_cost: float = 0.0

    @property
    def total_cost(self) -> float:
        return self._total_cost

    @property
    def by_model(self) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for entry in self.history:
            if entry.model not in result:
                result[entry.model] = {"cost": 0.0, "tokens": 0, "calls": 0}
            result[entry.model]["cost"] += entry.cost
            result[entry.model]["tokens"] += entry.prompt_tokens + entry.completion_tokens
            result[entry.model]["calls"] += 1
        return result

    @staticmethod
    def _resolve_usage(usage: dict | Any) -> dict:
        """Normalize usage to a dict, handling None and attr-based objects."""
        if usage is None:
            return {}
        if isinstance(usage, dict):
            return usage
        # Try attribute access for OpenAI SDK CompletionUsage objects
        try:
            prompt_tokens = getattr(usage, "prompt_tokens", 0)
            completion_tokens = getattr(usage, "completion_tokens", 0)
            total_tokens = getattr(usage, "total_tokens", 0)
            details = getattr(usage, "prompt_tokens_details", None) or {}
            cached_tokens = getattr(details, "cached_tokens", 0) if not isinstance(details, dict) else details.get("cached_tokens", 0)
            return {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "prompt_tokens_details": {"cached_tokens": cached_tokens},
            }
        except Exception:
            return {}

    def record(self, model: str, usage: dict | Any) -> CostEntry:
        usage = self._resolve_usage(usage)
        pricing = PRICING.get(model, PRICING[_DEFAULT_MODEL])
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        details = usage.get("prompt_tokens_details", {}) or {}
        cached_tokens = details.get("cached_tokens", 0)

        uncached_input = max(prompt_tokens - cached_tokens, 0)
        cost = (
            uncached_input / 1_000_000 * pricing["input"]
            + completion_tokens / 1_000_000 * pricing["output"]
            + cached_tokens / 1_000_000 * pricing.get("cached_input", 0)
        )

        entry = CostEntry(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cost=cost,
        )
        self.history.append(entry)
        self._total_cost += cost
        return entry

    def reset(self):
        self.history.clear()
        self._total_cost = 0.0
