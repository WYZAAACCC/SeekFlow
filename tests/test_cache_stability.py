"""Verify cache append_only_compress preserves system message prefix."""
from __future__ import annotations

from seekflow.cache import append_only_compress


def test_append_only_compress_does_not_change_system_message():
    original_system = "You are a helpful assistant."
    messages = [
        {"role": "system", "content": original_system},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
    ] * 20  # many messages to trigger compression

    result = append_only_compress(messages, max_context_tokens=100)

    # System message must be preserved exactly
    assert result[0]["role"] == "system"
    assert result[0]["content"] == original_system

    # Compressed context must be in a separate message
    if len(result) > 1:
        for msg in result[1:]:
            if "Compressed Context" in str(msg.get("content", "")):
                assert msg["role"] == "user"


def test_no_compression_when_under_limit():
    messages = [
        {"role": "system", "content": "Be helpful."},
        {"role": "user", "content": "Hi"},
    ]
    result = append_only_compress(messages, max_context_tokens=999999)
    assert result == messages
