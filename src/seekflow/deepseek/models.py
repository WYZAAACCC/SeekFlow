"""DeepSeek model profiles and capability registry."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DeepSeekModel = Literal["deepseek-v4-flash", "deepseek-v4-pro"]
ReasoningEffort = Literal["high", "max"]


@dataclass(frozen=True)
class ModelProfile:
    """Static profile for a DeepSeek model."""
    model: DeepSeekModel
    thinking_enabled: bool
    reasoning_effort: ReasoningEffort | None = None
    base_url: str = "https://api.deepseek.com"
    max_context_tokens: int = 1_000_000
    max_output_tokens: int = 384_000

    @property
    def is_reasoning_model(self) -> bool:
        return self.thinking_enabled


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
    "deepseek-chat": ModelProfile(
        model="deepseek-v4-flash", thinking_enabled=False,
    ),
    "deepseek-reasoner": ModelProfile(
        model="deepseek-v4-pro", thinking_enabled=True, reasoning_effort="high",
    ),
    "deepseek-v3": ModelProfile(
        model="deepseek-v4-pro", thinking_enabled=True, reasoning_effort="high",
    ),
}
