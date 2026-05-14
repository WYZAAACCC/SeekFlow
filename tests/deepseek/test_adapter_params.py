"""Test DeepSeekAdapter parameter normalization."""
import pytest
from seekflow.deepseek.adapter import (
    DeepSeekAdapter,
    ThinkingConfig,
    NormalizedUsage,
)


def test_thinking_enabled_adds_extra_body_and_effort():
    params = DeepSeekAdapter.build_chat_params(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "Hi"}],
        thinking=ThinkingConfig(enabled=True, effort="high"),
    )
    assert params["model"] == "deepseek-v4-flash"
    assert params["extra_body"]["thinking"] == {"type": "enabled"}
    assert params["reasoning_effort"] == "high"


def test_thinking_removes_tool_choice():
    params = DeepSeekAdapter.build_chat_params(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "Hi"}],
        thinking=ThinkingConfig(enabled=True),
        tool_choice="auto",
    )
    assert "tool_choice" not in params


def test_non_thinking_can_keep_tool_choice():
    params = DeepSeekAdapter.build_chat_params(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "Hi"}],
        thinking=ThinkingConfig(enabled=False),
        tool_choice="none",
    )
    assert params.get("tool_choice") == "none"


def test_thinking_disabled_sets_extra_body():
    params = DeepSeekAdapter.build_chat_params(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "Hi"}],
        thinking=ThinkingConfig(enabled=False),
    )
    assert params["extra_body"]["thinking"] == {"type": "disabled"}


def test_thinking_removes_sampling_params():
    params = DeepSeekAdapter.build_chat_params(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "Hi"}],
        thinking=ThinkingConfig(enabled=True),
        temperature=0.7,
        top_p=0.9,
        presence_penalty=0.5,
        frequency_penalty=0.5,
    )
    assert "temperature" not in params
    assert "top_p" not in params
    assert "presence_penalty" not in params
    assert "frequency_penalty" not in params


def test_developer_role_converted_to_system():
    messages = [{"role": "developer", "content": "You are helpful."}]
    normalized = DeepSeekAdapter.normalize_messages(messages)
    assert normalized[0]["role"] == "system"


def test_max_completion_tokens_maps_to_max_tokens():
    params = DeepSeekAdapter.build_chat_params(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "Hi"}],
        thinking=ThinkingConfig(enabled=False),
        max_completion_tokens=4096,
    )
    assert params.get("max_tokens") == 4096
    assert "max_completion_tokens" not in params


def test_max_tokens_present_preserves_it():
    params = DeepSeekAdapter.build_chat_params(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "Hi"}],
        thinking=ThinkingConfig(enabled=False),
        max_tokens=2048,
        max_completion_tokens=4096,
    )
    assert params.get("max_tokens") == 2048


def test_deepseek_reasoner_alias_maps_to_flash_thinking():
    params = DeepSeekAdapter.build_chat_params(
        model="deepseek-reasoner",
        messages=[{"role": "user", "content": "Hi"}],
        thinking=ThinkingConfig(enabled=True, effort="high"),
    )
    assert params["model"] == "deepseek-v4-flash"
    assert params["extra_body"]["thinking"] == {"type": "enabled"}


def test_deepseek_chat_alias_maps_to_flash_non_thinking():
    params = DeepSeekAdapter.build_chat_params(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "Hi"}],
        thinking=ThinkingConfig(enabled=False),
    )
    assert params["model"] == "deepseek-v4-flash"
    assert params["extra_body"]["thinking"] == {"type": "disabled"}


def test_normalize_usage_dict():
    usage = NormalizedUsage(
        prompt_tokens=100, completion_tokens=50, total_tokens=150,
        prompt_cache_hit_tokens=80, prompt_cache_miss_tokens=20,
    )
    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 50
    assert usage.prompt_cache_hit_tokens == 80


def test_adapter_normalize_usage_from_dict():
    usage = DeepSeekAdapter.normalize_usage({
        "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150,
    })
    assert isinstance(usage, NormalizedUsage)
    assert usage.prompt_tokens == 100


def test_adapter_resolve_model():
    profile = DeepSeekAdapter.resolve_model("deepseek-chat")
    assert profile.model == "deepseek-v4-flash"
    assert profile.thinking_enabled is False


def test_adapter_resolve_reasoner():
    profile = DeepSeekAdapter.resolve_model("deepseek-reasoner")
    assert profile.model == "deepseek-v4-flash"
    assert profile.thinking_enabled is True


def test_response_format_preserved():
    params = DeepSeekAdapter.build_chat_params(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "Hi"}],
        thinking=ThinkingConfig(enabled=False),
        response_format={"type": "json_object"},
    )
    assert params["response_format"] == {"type": "json_object"}


def test_tools_preserved():
    tools = [{"type": "function", "function": {"name": "test", "description": "", "parameters": {}}}]
    params = DeepSeekAdapter.build_chat_params(
        model="deepseek-v4-flash",
        messages=[{"role": "user", "content": "Hi"}],
        tools=tools,
        thinking=ThinkingConfig(enabled=False),
    )
    assert params["tools"] == tools
