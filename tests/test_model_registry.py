"""Test model registry and pricing unification."""
from seekflow.deepseek.models import (
    LEGACY_MODEL_MAP, DEFAULT_PRIMARY, DEFAULT_FALLBACK, ModelProfile,
)
from seekflow.deepseek.adapter import DeepSeekAdapter, ThinkingConfig


def test_alias_resolution_deepseek_chat():
    profile = DeepSeekAdapter.resolve_model("deepseek-chat")
    assert profile.model == "deepseek-v4-flash"
    assert profile.thinking_enabled is False


def test_alias_resolution_deepseek_reasoner():
    profile = DeepSeekAdapter.resolve_model("deepseek-reasoner")
    # deepseek-reasoner → v4-flash with thinking ON per official docs
    assert profile.model == "deepseek-v4-flash"
    assert profile.thinking_enabled is True
    assert profile.reasoning_effort == "high"


def test_legacy_model_map_deepseek_chat():
    assert "deepseek-chat" in LEGACY_MODEL_MAP
    assert LEGACY_MODEL_MAP["deepseek-chat"].model == "deepseek-v4-flash"


def test_legacy_model_map_deepseek_reasoner():
    assert "deepseek-reasoner" in LEGACY_MODEL_MAP
    # Must map to v4-flash (not v4-pro)
    assert LEGACY_MODEL_MAP["deepseek-reasoner"].model == "deepseek-v4-flash"


def test_default_primary_is_v4_pro():
    assert DEFAULT_PRIMARY.model == "deepseek-v4-pro"


def test_default_fallback_is_v4_flash():
    assert DEFAULT_FALLBACK.model == "deepseek-v4-flash"


def test_model_profile_context_length():
    assert DEFAULT_PRIMARY.max_context_tokens == 1_000_000
    assert DEFAULT_PRIMARY.max_output_tokens == 384_000


def test_normalize_model_name_legacy():
    name = DeepSeekAdapter.normalize_model_name("deepseek-chat")
    assert name == "deepseek-v4-flash"


def test_normalize_model_name_modern():
    name = DeepSeekAdapter.normalize_model_name("deepseek-v4-flash")
    assert name == "deepseek-v4-flash"
