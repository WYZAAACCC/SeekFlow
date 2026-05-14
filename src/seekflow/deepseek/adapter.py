"""DeepSeekAdapter — single source of truth for all DeepSeek protocol compatibility.

Every DeepSeek-specific rule (thinking params, tool_choice removal, developer role,
model alias, max_tokens/max_completion_tokens, usage normalization) lives here.
No other module should scatter DeepSeek compatibility logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from seekflow.deepseek.models import (
    DEFAULT_PRIMARY,
    LEGACY_MODEL_MAP,
    ModelProfile,
)

# ── Capabilities descriptor ────────────────────────────────────────────────


@dataclass(frozen=True)
class DeepSeekCapabilities:
    """Static capability flags for DeepSeek V4 API."""
    supports_developer_role: bool = False
    supports_reasoning_effort: bool = True
    max_tokens_field: str = "max_tokens"
    supports_tool_choice_in_thinking: bool = False
    requires_reasoning_content_for_tool_calls: bool = True
    requires_assistant_content_for_tool_calls: bool = True
    supports_json_output: bool = True
    supports_context_caching: bool = True


# ── Thinking config ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ThinkingConfig:
    enabled: bool = True
    effort: Literal["high", "max"] = "high"


# ── Usage ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class NormalizedUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0


# ── Params that are ignored in thinking mode ────────────────────────────────

_THINKING_IGNORED_PARAMS: frozenset[str] = frozenset({
    "temperature", "top_p", "presence_penalty", "frequency_penalty",
})


# ── Adapter ─────────────────────────────────────────────────────────────────


class DeepSeekAdapter:
    """Centralize all DeepSeek compatibility transformations.

    Usage::

        adapter = DeepSeekAdapter()
        thinking = ThinkingConfig(enabled=True, effort="high")
        adapter.build_chat_params(
            model="deepseek-reasoner",
            messages=[...],
            tools=[...],
            thinking=thinking,
        )
    """

    @staticmethod
    def capabilities() -> DeepSeekCapabilities:
        return DeepSeekCapabilities()

    @staticmethod
    def resolve_model(model: str, thinking: ThinkingConfig | None = None) -> ModelProfile:
        """Resolve a model name (including legacy aliases) to a ModelProfile."""
        if model in LEGACY_MODEL_MAP:
            return LEGACY_MODEL_MAP[model]
        if thinking is None:
            return DEFAULT_PRIMARY
        if model in ("deepseek-v4-pro", "deepseek-v4-flash"):
            return ModelProfile(
                model=model,
                thinking_enabled=thinking.enabled,
                reasoning_effort=thinking.effort if thinking.enabled else None,
            )
        return DEFAULT_PRIMARY

    @staticmethod
    def normalize_model_name(model: str) -> str:
        """Map legacy model names to current ones without changing thinking."""
        if model in LEGACY_MODEL_MAP:
            return LEGACY_MODEL_MAP[model].model
        return model

    @staticmethod
    def normalize_messages(
        messages: list[dict[str, Any]],
        *,
        thinking: ThinkingConfig | None = None,
    ) -> list[dict[str, Any]]:
        """Normalize messages for DeepSeek API compatibility.

        - Converts developer role to system
        - Ensures required fields are present
        """
        result: list[dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role")
            m = dict(msg)
            if role == "developer":
                m["role"] = "system"
            result.append(m)
        return result

    @staticmethod
    def build_chat_params(
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        thinking: ThinkingConfig | None = None,
        response_format: Any | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Build a complete chat completion params dict compliant with DeepSeek V4.

        This is the single function that should assemble all params before
        sending to the DeepSeek API. It handles:

        - Model alias normalization
        - Thinking extra_body
        - tool_choice removal in thinking mode
        - Sampling param cleanup
        - max_completion_tokens → max_tokens
        - developer role → system
        - response_format
        """
        # Normalize model name
        actual_model = model
        if thinking is not None:
            resolved = DeepSeekAdapter.resolve_model(model, thinking)
            actual_model = resolved.model
            if thinking.enabled != resolved.thinking_enabled:
                # Model forced thinking on/off — use resolved profile's setting
                thinking = ThinkingConfig(
                    enabled=resolved.thinking_enabled,
                    effort=resolved.reasoning_effort or thinking.effort,
                )

        params: dict[str, Any] = {
            "model": actual_model,
            "messages": DeepSeekAdapter.normalize_messages(messages, thinking=thinking),
            **kwargs,
        }

        if tools:
            params["tools"] = tools

        if response_format is not None:
            params["response_format"] = response_format

        if stream:
            params["stream"] = True
            params["stream_options"] = {"include_usage": True}

        # max_completion_tokens compatibility
        if "max_completion_tokens" in params:
            if "max_tokens" not in params:
                params["max_tokens"] = params.pop("max_completion_tokens")
            else:
                params.pop("max_completion_tokens")

        # Thinking mode configuration
        if thinking is not None and thinking.enabled:
            extra_body = dict(params.get("extra_body") or {})
            extra_body["thinking"] = {"type": "enabled"}
            params["extra_body"] = extra_body
            params["reasoning_effort"] = thinking.effort

            # Remove params that have no effect in thinking mode
            params.pop("tool_choice", None)
            for key in sorted(_THINKING_IGNORED_PARAMS):
                params.pop(key, None)
        elif thinking is not None and not thinking.enabled:
            extra_body = dict(params.get("extra_body") or {})
            extra_body["thinking"] = {"type": "disabled"}
            params["extra_body"] = extra_body

        return params

    @staticmethod
    def normalize_usage(usage: Any) -> NormalizedUsage:
        """Normalize usage data from API response to NormalizedUsage."""
        if usage is None:
            return NormalizedUsage()

        if isinstance(usage, dict):
            prompt = int(usage.get("prompt_tokens", 0) or 0)
            completion = int(usage.get("completion_tokens", 0) or 0)
            total = int(usage.get("total_tokens", 0) or 0)

            # Cache tokens — try new fields first, then legacy
            hit = int(usage.get("prompt_cache_hit_tokens", 0) or 0)
            miss = int(usage.get("prompt_cache_miss_tokens", 0) or 0)

            if hit == 0 and miss == 0:
                details = usage.get("prompt_tokens_details", {}) or {}
                hit = int(details.get("prompt_cache_hit_tokens", 0) or 0)
                miss = int(details.get("prompt_cache_miss_tokens", 0) or 0)
                if hit == 0 and miss == 0:
                    cached = int(details.get("cached_tokens", 0) or 0)
                    hit = cached
                    miss = max(prompt - cached, 0)

            return NormalizedUsage(
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
                prompt_cache_hit_tokens=hit,
                prompt_cache_miss_tokens=miss,
            )

        # Object with attributes
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        total = int(getattr(usage, "total_tokens", 0) or 0)
        hit = int(getattr(usage, "prompt_cache_hit_tokens", 0) or 0)
        miss = int(getattr(usage, "prompt_cache_miss_tokens", 0) or 0)

        return NormalizedUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            prompt_cache_hit_tokens=hit,
            prompt_cache_miss_tokens=miss,
        )
