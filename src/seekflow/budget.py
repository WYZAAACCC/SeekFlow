"""Preflight cost estimation and hard budget enforcement."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seekflow.errors import SeekFlowError


class BudgetExceeded(SeekFlowError):
    """Raised when the preflight estimate exceeds the configured budget."""

    def __init__(self, limit: float, estimated: float, model: str = ""):
        self.limit = limit
        self.estimated = estimated
        self.model = model
        super().__init__(
            f"Estimated cost CNY {estimated:.6f} exceeds budget CNY {limit:.6f}"
            f" for model '{model}'. Reduce task scope or increase budget."
        )


@dataclass
class CostBudget:
    """Hard cost and resource limits for a single agent run."""

    max_cny: float = float("inf")
    max_prompt_tokens: int = 200_000
    max_completion_tokens: int = 8_000
    max_tool_calls: int = 20
    max_wall_time_s: int = 60

    @staticmethod
    def tight() -> CostBudget:
        """Conservative budget for low-cost runs."""
        return CostBudget(max_cny=0.05, max_prompt_tokens=50_000)

    @staticmethod
    def generous() -> CostBudget:
        """Generous budget for complex multi-step tasks."""
        return CostBudget(max_cny=1.00, max_prompt_tokens=500_000, max_tool_calls=50)


@dataclass
class PreflightEstimate:
    """Estimated cost and token consumption for a planned request."""

    lower_bound_cost: float = 0.0
    upper_bound_cost: float = 0.0
    estimated_prompt_tokens: int = 0
    estimated_completion_tokens: int = 0
    estimated_cache_hit: bool = False
    breakdown: dict[str, int] = field(default_factory=dict)


# Pricing CNY per 1M tokens
_PRICING: dict[str, dict[str, float]] = {
    "deepseek-chat":    {"input": 0.14, "cached_input": 0.014, "output": 0.28},
    "deepseek-v3":      {"input": 0.28, "cached_input": 0.028, "output": 1.12},
    "deepseek-v4-pro":  {"input": 1.74, "cached_input": 0.028, "output": 3.48},
    "deepseek-v4-flash":{"input": 0.14, "cached_input": 0.014, "output": 0.28},
    "__default__":      {"input": 1.74, "cached_input": 0.028, "output": 3.48},
}


class CostEstimator:
    """Estimate token consumption and cost BEFORE making API calls."""

    def estimate(
        self,
        messages: list[dict],
        model: str = "deepseek-v4-pro",
        thinking_budget: int = 0,
        max_steps: int = 1,
        tools_count: int = 0,
    ) -> PreflightEstimate:
        """Return a preflight cost estimate for the planned request."""
        # Rough token estimation: ~4 chars per token
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        estimated_prompt = max(total_chars // 4, 1)

        # Tool schema overhead (~100 tokens per tool)
        estimated_prompt += tools_count * 100

        # Thinking budget overhead
        estimated_prompt += thinking_budget

        # Completion estimate based on max_steps
        estimated_completion = 1024 * max_steps + thinking_budget * max_steps

        pricing = _PRICING.get(model, _PRICING["__default__"])
        lower_cost = (
            estimated_prompt * pricing["cached_input"] / 1_000_000
            + estimated_completion * pricing["output"] / 1_000_000
        )
        upper_cost = (
            estimated_prompt * pricing["input"] / 1_000_000
            + estimated_completion * pricing["output"] / 1_000_000
            + max_steps * 200 * pricing["output"] / 1_000_000  # tool result overhead
        )

        return PreflightEstimate(
            lower_bound_cost=round(lower_cost, 6),
            upper_bound_cost=round(upper_cost, 6),
            estimated_prompt_tokens=estimated_prompt,
            estimated_completion_tokens=estimated_completion,
            estimated_cache_hit=True,  # assume cache hit for lower bound
            breakdown={
                "messages": estimated_prompt,
                "tools_schema": tools_count * 100,
                "thinking_budget": thinking_budget,
                "completion": estimated_completion,
            },
        )
