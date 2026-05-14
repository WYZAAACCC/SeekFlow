"""DeepSeek parameter normalization and validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from seekflow.deepseek.models import ModelProfile

IGNORED_IN_THINKING: frozenset[str] = frozenset({
    "temperature", "top_p", "presence_penalty", "frequency_penalty",
})


@dataclass
class NormalizedParams:
    params: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


class DeepSeekParamsNormalizer:
    """Normalize chat completion params based on the model profile."""

    def normalize(
        self, params: dict[str, Any], profile: ModelProfile,
    ) -> NormalizedParams:
        out = dict(params)
        warnings: list[str] = []

        extra_body = dict(out.get("extra_body") or {})

        if profile.thinking_enabled:
            extra_body["thinking"] = {"type": "enabled"}
            if profile.reasoning_effort:
                out["reasoning_effort"] = profile.reasoning_effort

            removed = {}
            for key in sorted(IGNORED_IN_THINKING):
                if key in out:
                    removed[key] = out.pop(key)

            if removed:
                warnings.append(
                    "Removed sampling params ignored by DeepSeek thinking mode: "
                    + ", ".join(sorted(removed))
                )
        else:
            extra_body["thinking"] = {"type": "disabled"}

        out["extra_body"] = extra_body
        return NormalizedParams(params=out, warnings=warnings)
