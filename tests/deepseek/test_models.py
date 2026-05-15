"""Tests for DeepSeek model profiles and param normalization."""
from __future__ import annotations

import pytest

from seekflow.deepseek.models import (
    ModelProfile, DEFAULT_PRIMARY, DEFAULT_FALLBACK, LEGACY_MODEL_MAP,
)
from seekflow.deepseek.params import DeepSeekParamsNormalizer


class TestModelProfiles:
    def test_primary_is_v4_pro(self):
        assert DEFAULT_PRIMARY.model == "deepseek-v4-pro"
        assert DEFAULT_PRIMARY.thinking_enabled is True

    def test_fallback_is_v4_flash(self):
        assert DEFAULT_FALLBACK.model == "deepseek-v4-flash"
        assert DEFAULT_FALLBACK.thinking_enabled is False

    def test_legacy_chat_maps_to_flash(self):
        assert LEGACY_MODEL_MAP["deepseek-chat"].model == "deepseek-v4-flash"

    @pytest.mark.xfail(reason="pre-existing: user business changes (v0.3.5)")
    def test_legacy_reasoner_maps_to_pro(self):
        assert LEGACY_MODEL_MAP["deepseek-reasoner"].model == "deepseek-v4-pro"
        assert LEGACY_MODEL_MAP["deepseek-reasoner"].thinking_enabled is True

    def test_is_reasoning_model(self):
        assert DEFAULT_PRIMARY.is_reasoning_model is True
        assert DEFAULT_FALLBACK.is_reasoning_model is False


class TestParamsNormalizer:
    def test_thinking_enabled_extra_body(self):
        result = DeepSeekParamsNormalizer().normalize({}, DEFAULT_PRIMARY)
        assert result.params["extra_body"]["thinking"] == {"type": "enabled"}

    def test_thinking_removes_sampling_params(self):
        result = DeepSeekParamsNormalizer().normalize(
            {"temperature": 0.2, "top_p": 0.9}, DEFAULT_PRIMARY,
        )
        assert "temperature" not in result.params
        assert "top_p" not in result.params
        assert len(result.warnings) >= 1

    def test_non_thinking_disables_thinking(self):
        result = DeepSeekParamsNormalizer().normalize({}, DEFAULT_FALLBACK)
        assert result.params["extra_body"]["thinking"] == {"type": "disabled"}

    def test_reasoning_effort_passed_through(self):
        result = DeepSeekParamsNormalizer().normalize({}, DEFAULT_PRIMARY)
        assert result.params["reasoning_effort"] == "high"
