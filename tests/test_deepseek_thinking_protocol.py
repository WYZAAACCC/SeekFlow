"""Golden tests for DeepSeek thinking/tool-call protocol invariants."""
from __future__ import annotations

import pytest

from seekflow.deepseek.protocol import ConversationState, validate_deepseek_messages
from seekflow.runtime_errors import DeepSeekProtocolError


class TestToolCallReasoningPreservation:
    """reasoning_content must be preserved exactly when tool_calls are present."""

    def test_assistant_tool_call_requires_reasoning_content(self):
        state = ConversationState()
        state.add_user("查询天气")

        with pytest.raises(DeepSeekProtocolError):
            state.add_assistant(
                content=None,
                reasoning_content=None,
                tool_calls=[{
                    "id": "call_1", "type": "function",
                    "function": {"name": "weather", "arguments": '{"city":"杭州"}'},
                }],
            )

    def test_reasoning_content_preserved_exactly(self):
        state = ConversationState()
        reasoning = "我需要调用天气工具来获取杭州的当前温度。" * 5

        state.add_user("查询天气")
        state.add_assistant(
            content=None,
            reasoning_content=reasoning,
            tool_calls=[{
                "id": "call_1", "type": "function",
                "function": {"name": "weather", "arguments": '{"city":"杭州"}'},
            }],
        )

        assert state.messages[-1]["reasoning_content"] == reasoning

    def test_tool_message_must_follow_assistant(self):
        messages = [
            {"role": "user", "content": "查询天气"},
            {"role": "assistant", "content": None, "reasoning_content": "r",
             "tool_calls": [{"id": "call_1", "type": "function",
                             "function": {"name": "w", "arguments": "{}"}}]},
            {"role": "user", "content": "非法插入"},  # breaks adjacency
            {"role": "tool", "tool_call_id": "call_1", "content": "24℃"},
        ]

        with pytest.raises(DeepSeekProtocolError):
            validate_deepseek_messages(messages)

    def test_valid_tool_sequence_passes(self):
        messages = [
            {"role": "user", "content": "查询天气"},
            {"role": "assistant", "content": None, "reasoning_content": "r",
             "tool_calls": [{"id": "call_1", "type": "function",
                             "function": {"name": "w", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "24℃"},
        ]
        validate_deepseek_messages(messages)

    def test_tool_call_id_mismatch_rejected(self):
        messages = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": None, "reasoning_content": "r",
             "tool_calls": [{"id": "call_1", "type": "function",
                             "function": {"name": "w", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "wrong_id", "content": "x"},
        ]
        with pytest.raises(DeepSeekProtocolError):
            validate_deepseek_messages(messages)
