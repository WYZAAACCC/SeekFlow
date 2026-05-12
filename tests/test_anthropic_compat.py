"""Tests for adapters.anthropic_compat — Anthropic-compatible endpoint."""
from unittest.mock import MagicMock, patch
import pytest


class TestAnthropicMessageConversion:
    def test_text_block_converted_to_content_string(self):
        from deepseek_toolkit.adapters.anthropic_compat import _anthropic_to_deepseek_messages
        result = _anthropic_to_deepseek_messages([
            {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        ])
        assert result[0]["role"] == "user"
        assert result[0]["content"] == "hello"

    def test_multiple_text_blocks_joined(self):
        from deepseek_toolkit.adapters.anthropic_compat import _anthropic_to_deepseek_messages
        result = _anthropic_to_deepseek_messages([
            {"role": "user", "content": [
                {"type": "text", "text": "part1 "},
                {"type": "text", "text": "part2"},
            ]},
        ])
        assert result[0]["content"] == "part1 part2"

    def test_tool_use_block_converted(self):
        from deepseek_toolkit.adapters.anthropic_compat import _anthropic_to_deepseek_messages
        result = _anthropic_to_deepseek_messages([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "tu1", "name": "get_weather", "input": {"city": "Beijing"}},
            ]},
        ])
        assert result[0]["role"] == "assistant"
        assert result[0]["tool_calls"][0]["function"]["name"] == "get_weather"
        assert result[0]["tool_calls"][0]["function"]["arguments"] == '{"city": "Beijing"}'

    def test_tool_result_block_converted(self):
        from deepseek_toolkit.adapters.anthropic_compat import _anthropic_to_deepseek_messages
        result = _anthropic_to_deepseek_messages([
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "tu1", "content": "Sunny, 28C"},
            ]},
        ])
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "tu1"
        assert result[0]["content"] == "Sunny, 28C"

    def test_image_block_raises_error(self):
        from deepseek_toolkit.adapters.anthropic_compat import _anthropic_to_deepseek_messages
        with pytest.raises(ValueError, match="image"):
            _anthropic_to_deepseek_messages([
                {"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "xxx"}},
                ]},
            ])

    def test_plain_string_content_passes_through(self):
        from deepseek_toolkit.adapters.anthropic_compat import _anthropic_to_deepseek_messages
        result = _anthropic_to_deepseek_messages([
            {"role": "user", "content": "just a string"},
        ])
        assert result[0]["content"] == "just a string"
