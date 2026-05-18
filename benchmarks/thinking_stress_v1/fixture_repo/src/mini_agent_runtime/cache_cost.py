"""Prompt cache prefix builder and cost estimator.

BUGS:
- build_cache_prefix includes timestamp, destroying cache stability.
- estimate_cost_cny ignores cached tokens (charges all input at full price).
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class Usage:
    prompt_tokens: int
    cached_tokens: int
    completion_tokens: int


def build_cache_prefix(system_prompt: str, tools_schema: str) -> str:
    """Build a cacheable prefix for DeepSeek prompt caching.

    BUG:
    Includes timestamp in prefix, destroying prompt cache.
    """
    return f"{time.time()}::{system_prompt}\nTOOLS:\n{tools_schema}"


def estimate_cost_cny(
    usage: Usage,
    input_price: float,
    cached_input_price: float,
    output_price: float,
) -> float:
    """Estimate cost in CNY given token usage.

    BUG:
    Charges cached tokens at full input price instead of cached rate.
    Prices are CNY per 1M tokens.
    """
    return (
        usage.prompt_tokens * input_price
        + usage.completion_tokens * output_price
    ) / 1_000_000
