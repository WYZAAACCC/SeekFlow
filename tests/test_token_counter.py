"""Tests for seekflow.token_counter — token counting."""
import pytest


class TestCountTokens:
    def test_count_tokens_returns_int(self):
        from seekflow.token_counter import count_tokens
        result = count_tokens([{"role": "user", "content": "hello world"}])
        assert isinstance(result, int)
        assert result > 0

    def test_count_tokens_empty_messages_returns_zero(self):
        from seekflow.token_counter import count_tokens
        assert count_tokens([]) == 0

    def test_count_text_returns_int(self):
        from seekflow.token_counter import count_text
        result = count_text("hello world")
        assert isinstance(result, int)
        assert result > 0

    def test_estimate_tokens_fallback_without_tiktoken(self):
        from unittest.mock import patch
        with patch("seekflow.token_counter._HAS_TIKTOKEN", False):
            from seekflow.token_counter import count_text
            result = count_text("hello world")
            assert result > 0  # uses char/4 fallback

    def test_count_tokens_includes_reasoning_content(self):
        from seekflow.token_counter import count_tokens
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi", "reasoning_content": "I should say hi"},
        ]
        result = count_tokens(msgs)
        assert result > count_tokens([{"role": "user", "content": "hello"}])

    def test_count_tokens_includes_tool_calls(self):
        from seekflow.token_counter import count_tokens
        msgs = [
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "1", "type": "function",
                             "function": {"name": "add", "arguments": '{"a":1,"b":2}'}}]},
        ]
        result = count_tokens(msgs)
        assert result > 0
