"""Verify runtime does not mutate caller's message list or dicts."""
import copy
from unittest.mock import MagicMock, patch

from seekflow.runtime import ToolRuntime


def test_chat_does_not_mutate_input_messages():
    original = [{"role": "user", "content": "hi"}]
    before = copy.deepcopy(original)

    with patch("seekflow.runtime.DeepSeekClient") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client

        from seekflow.types import ChatResponse
        mock_client.chat.return_value = ChatResponse(
            content="ok", finish_reason="stop",
            usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        )

        runtime = ToolRuntime(tools=[], api_key="sk-test")
        runtime.chat(
            model="deepseek-v4-flash",
            messages=original,
        )

        assert original == before, f"Input messages mutated: {original} != {before}"


def test_chat_stream_does_not_mutate_input_messages():
    original = [{"role": "user", "content": "hi"}]
    before = copy.deepcopy(original)

    with patch("seekflow.runtime.DeepSeekClient") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client

        from seekflow.types import _StreamChunk
        mock_client.chat_stream.return_value = iter([
            _StreamChunk(type="content", content="Hello"),
            _StreamChunk(type="usage", usage={"total_tokens": 5}),
        ])

        runtime = ToolRuntime(tools=[], api_key="sk-test")
        list(runtime.chat_stream(
            model="deepseek-v4-flash",
            messages=original,
        ))

        assert original == before, f"Input messages mutated: {original} != {before}"
