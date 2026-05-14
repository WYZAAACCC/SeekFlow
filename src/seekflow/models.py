"""DeepSeek model registry — capabilities, pricing, deprecation."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ModelSpec:
    name: str
    supports_thinking: bool
    supports_tools: bool
    supports_json: bool
    supports_fim: bool
    max_context_tokens: int
    max_output_tokens: int
    input_cache_hit_price_cny: Decimal
    input_cache_miss_price_cny: Decimal
    output_price_cny: Decimal
    deprecated_alias_for: str | None = None


DEEPSEEK_MODELS: dict[str, ModelSpec] = {
    "deepseek-v4-flash": ModelSpec(
        name="deepseek-v4-flash",
        supports_thinking=True,
        supports_tools=True,
        supports_json=True,
        supports_fim=True,
        max_context_tokens=1_000_000,
        max_output_tokens=384_000,
        input_cache_hit_price_cny=Decimal("0.014"),
        input_cache_miss_price_cny=Decimal("0.14"),
        output_price_cny=Decimal("0.28"),
    ),
    "deepseek-v4-pro": ModelSpec(
        name="deepseek-v4-pro",
        supports_thinking=True,
        supports_tools=True,
        supports_json=True,
        supports_fim=True,
        max_context_tokens=1_000_000,
        max_output_tokens=384_000,
        input_cache_hit_price_cny=Decimal("0.028"),
        input_cache_miss_price_cny=Decimal("1.74"),
        output_price_cny=Decimal("3.48"),
    ),
    "deepseek-chat": ModelSpec(
        name="deepseek-chat",
        supports_thinking=False,
        supports_tools=True,
        supports_json=True,
        supports_fim=False,
        max_context_tokens=1_000_000,
        max_output_tokens=384_000,
        input_cache_hit_price_cny=Decimal("0.014"),
        input_cache_miss_price_cny=Decimal("0.14"),
        output_price_cny=Decimal("0.28"),
        deprecated_alias_for="deepseek-v4-flash",
    ),
    "deepseek-reasoner": ModelSpec(
        name="deepseek-reasoner",
        supports_thinking=True,
        supports_tools=True,
        supports_json=True,
        supports_fim=False,
        max_context_tokens=1_000_000,
        max_output_tokens=384_000,
        input_cache_hit_price_cny=Decimal("0.014"),
        input_cache_miss_price_cny=Decimal("0.14"),
        output_price_cny=Decimal("0.28"),
        deprecated_alias_for="deepseek-v4-flash",
    ),
}


def get_model_spec(model: str) -> ModelSpec:
    """Return the ModelSpec for a given model name."""
    if model in DEEPSEEK_MODELS:
        return DEEPSEEK_MODELS[model]
    raise KeyError(f"Unknown model: {model}")


def resolve_model(model: str) -> tuple[ModelSpec, list[str]]:
    """Resolve model name, returning spec and any deprecation warnings."""
    warnings: list[str] = []
    spec = get_model_spec(model)
    if spec.deprecated_alias_for:
        warnings.append(
            f"Model '{model}' is deprecated and maps to '{spec.deprecated_alias_for}'. "
            f"Please update to the current model name."
        )
    return spec, warnings
