"""DeepSeek model profiles, pricing, and unified registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

DeepSeekModel = Literal["deepseek-v4-flash", "deepseek-v4-pro"]
ReasonAffort = Literal["high", "max"]


# ── Pricing ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Pricing:
    """Per-model pricing in CNY per 1M tokens."""
    input_cache_hit_per_1m: Decimal
    input_cache_miss_per_1m: Decimal
    output_per_1m: Decimal
    effective_at: str = ""  # ISO date string
    source: str = "https://api-docs.deepseek.com/quick_start/pricing"

    @property
    def cache_hit_discount_ratio(self) -> Decimal:
        """How much cheaper cache-hit input is vs cache-miss."""
        if self.input_cache_miss_per_1m == Decimal(0):
            return Decimal(0)
        return Decimal(1) - (self.input_cache_hit_per_1m / self.input_cache_miss_per_1m)


# ── Model spec ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ModelSpec:
    """Full capability and pricing spec for a model."""
    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"
    context_length: int = 1_000_000
    max_output_tokens: int = 384_000
    supports_thinking: bool = True
    supports_tool_calls: bool = True
    supports_json_output: bool = True
    supports_context_caching: bool = True
    supports_fim_non_thinking_only: bool = True
    pricing: Pricing = field(default_factory=lambda: Pricing(
        input_cache_hit_per_1m=Decimal("0.002"),
        input_cache_miss_per_1m=Decimal("0.14"),
        output_per_1m=Decimal("0.28"),
    ))


# ── Legacy ModelProfile (backward compat) ───────────────────────────────────


@dataclass(frozen=True)
class ModelProfile:
    """Static profile for a DeepSeek model (lightweight, backward compat)."""
    model: DeepSeekModel
    thinking_enabled: bool
    reasoning_effort: ReasonAffort | None = None
    base_url: str = "https://api.deepseek.com"
    max_context_tokens: int = 1_000_000
    max_output_tokens: int = 384_000

    @property
    def is_reasoning_model(self) -> bool:
        return self.thinking_enabled


# ── Pricing table (single source of truth) ──────────────────────────────────

_PRICING_TABLE: dict[str, Pricing] = {
    "deepseek-v4-pro": Pricing(
        input_cache_hit_per_1m=Decimal("0.028"),
        input_cache_miss_per_1m=Decimal("1.74"),
        output_per_1m=Decimal("3.48"),
        effective_at="2026-05",
    ),
    "deepseek-v4-flash": Pricing(
        input_cache_hit_per_1m=Decimal("0.002"),
        input_cache_miss_per_1m=Decimal("0.14"),
        output_per_1m=Decimal("0.28"),
        effective_at="2026-05",
    ),
}

_SPEC_TABLE: dict[str, ModelSpec] = {
    "deepseek-v4-pro": ModelSpec(
        provider="deepseek", model="deepseek-v4-pro",
        context_length=1_000_000, max_output_tokens=384_000,
        supports_thinking=True, supports_tool_calls=True,
        supports_json_output=True, supports_context_caching=True,
        supports_fim_non_thinking_only=True,
        pricing=_PRICING_TABLE["deepseek-v4-pro"],
    ),
    "deepseek-v4-flash": ModelSpec(
        provider="deepseek", model="deepseek-v4-flash",
        context_length=1_000_000, max_output_tokens=384_000,
        supports_thinking=True, supports_tool_calls=True,
        supports_json_output=True, supports_context_caching=True,
        supports_fim_non_thinking_only=True,
        pricing=_PRICING_TABLE["deepseek-v4-flash"],
    ),
}


# ── Model profiles (backward compat) ────────────────────────────────────────

DEFAULT_PRIMARY = ModelProfile(
    model="deepseek-v4-pro",
    thinking_enabled=True,
    reasoning_effort="high",
    max_output_tokens=384_000,
)

DEFAULT_FALLBACK = ModelProfile(
    model="deepseek-v4-flash",
    thinking_enabled=False,
    max_output_tokens=384_000,
)

LEGACY_MODEL_MAP: dict[str, ModelProfile] = {
    # Per DeepSeek official docs: deepseek-chat → v4-flash non-thinking
    "deepseek-chat": ModelProfile(
        model="deepseek-v4-flash", thinking_enabled=False,
    ),
    # deepseek-reasoner → v4-flash thinking mode (NOT v4-pro)
    "deepseek-reasoner": ModelProfile(
        model="deepseek-v4-flash", thinking_enabled=True, reasoning_effort="high",
    ),
    # deepseek-v3 legacy — retired, map to v4-pro as closest capability match
    "deepseek-v3": ModelProfile(
        model="deepseek-v4-pro", thinking_enabled=True, reasoning_effort="high",
    ),
}


# ── ModelRegistry ───────────────────────────────────────────────────────────


class ModelRegistry:
    """Unified model registry — single source of truth for pricing and capabilities.

    Usage::

        reg = ModelRegistry.default()
        spec = reg.resolve("deepseek-chat", thinking=True)
        cost = reg.price_usage("deepseek-v4-flash", usage)
    """

    def __init__(self, specs: dict[str, ModelSpec] | None = None):
        self._specs = dict(specs or _SPEC_TABLE)

    @staticmethod
    def default() -> "ModelRegistry":
        """Return the default registry with DeepSeek official pricing."""
        return ModelRegistry()

    @staticmethod
    def from_yaml(path: str | Path) -> "ModelRegistry":
        """Load a registry from a YAML file.

        YAML format::

            deepseek-v4-pro:
              pricing:
                input_cache_hit_per_1m: 0.028
                input_cache_miss_per_1m: 1.74
                output_per_1m: 3.48
              context_length: 1000000
              max_output_tokens: 384000
        """
        import yaml
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        specs: dict[str, ModelSpec] = {}
        for name, entry in (data or {}).items():
            p = entry.get("pricing", {})
            p_data = p
            pricing = Pricing(
                input_cache_hit_per_1m=Decimal(str(p_data.get("input_cache_hit_per_1m", 0))),
                input_cache_miss_per_1m=Decimal(str(p_data.get("input_cache_miss_per_1m", 0))),
                output_per_1m=Decimal(str(p_data.get("output_per_1m", 0))),
                effective_at=str(p_data.get("effective_at", "")),
                source=str(p_data.get("source", "yaml")),
            )
            supports_fim = entry.get("supports_fim_non_thinking_only", True)
            spec = ModelSpec(
                provider=entry.get("provider", "deepseek"),
                model=name,
                context_length=entry.get("context_length", 1_000_000),
                max_output_tokens=entry.get("max_output_tokens", 384_000),
                supports_thinking=entry.get("supports_thinking", True),
                supports_tool_calls=entry.get("supports_tool_calls", True),
                supports_json_output=entry.get("supports_json_output", True),
                supports_context_caching=entry.get("supports_context_caching", True),
                supports_fim_non_thinking_only=supports_fim,
                pricing=pricing,
            )
            specs[name] = spec
        return ModelRegistry(specs)

    def resolve(self, model: str, thinking: bool | None = None) -> ModelSpec:
        """Resolve a model name to its full spec.

        Handles legacy aliases:
        - deepseek-chat → v4-flash
        - deepseek-reasoner → v4-flash
        - deepseek-v3 → v4-pro
        """
        # Normalize legacy names
        if model in LEGACY_MODEL_MAP:
            model = LEGACY_MODEL_MAP[model].model
        spec = self._specs.get(model)
        if spec is None:
            raise KeyError(f"Unknown model: {model}")
        return spec

    def get_pricing(self, model: str) -> Pricing:
        """Get pricing for a resolved model name."""
        return self.resolve(model).pricing

    def price_usage(self, model: str, usage: dict | Any) -> Decimal:
        """Calculate cost from a usage dict.

        *usage* may be a dict with ``prompt_tokens``, ``completion_tokens``,
        ``prompt_cache_hit_tokens``, ``prompt_cache_miss_tokens``,
        ``prompt_tokens_details``, or a ``NormalizedUsage``.
        """
        if hasattr(usage, "prompt_cache_hit_tokens"):
            hit = int(getattr(usage, "prompt_cache_hit_tokens", 0) or 0)
            miss = int(getattr(usage, "prompt_cache_miss_tokens", 0) or 0)
            prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        elif isinstance(usage, dict):
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            hit = int(usage.get("prompt_cache_hit_tokens", 0) or 0)
            miss = int(usage.get("prompt_cache_miss_tokens", 0) or 0)
            if hit == 0 and miss == 0:
                details = usage.get("prompt_tokens_details", {}) or {}
                hit = int(details.get("prompt_cache_hit_tokens", 0) or 0)
                miss = int(details.get("prompt_cache_miss_tokens", 0) or 0)
                if hit == 0 and miss == 0:
                    cached = int(details.get("cached_tokens", 0) or 0)
                    hit = cached
                    miss = max(prompt_tokens - cached, 0)
        else:
            return Decimal(0)

        pricing = self.get_pricing(model)
        one_m = Decimal(1_000_000)
        cost = (
            Decimal(hit) * pricing.input_cache_hit_per_1m / one_m
            + Decimal(miss) * pricing.input_cache_miss_per_1m / one_m
            + Decimal(completion_tokens) * pricing.output_per_1m / one_m
        )
        return cost.quantize(Decimal("0.000001"))

    def list_models(self) -> list[str]:
        """List all known model names."""
        return sorted(self._specs.keys())

    def __contains__(self, model: str) -> bool:
        m = model
        if m in LEGACY_MODEL_MAP:
            m = LEGACY_MODEL_MAP[m].model
        return m in self._specs
