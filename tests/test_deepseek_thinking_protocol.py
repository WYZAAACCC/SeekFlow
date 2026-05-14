"""Golden tests for DeepSeek thinking/tool-call protocol invariants.

validate_deepseek_messages returns list[ValidationIssue], not raises.
Use assert_deepseek_messages_valid for the raise-on-error variant.
"""
from __future__ import annotations

import pytest

from seekflow.deepseek.protocol import (
    ConversationState,
    validate_deepseek_messages,
    repair_deepseek_messages,
)
from seekflow.runtime_errors import DeepSeekProtocolError


def _assert_valid(messages, *, thinking_enabled=True):
    """Convenience: validate and raise on errors."""
    issues = validate_deepseek_messages(messages, thinking_enabled=thinking_enabled)
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        raise DeepSeekProtocolError(
            "; ".join(f"[{i.code}] {i.message}" for i in errors)
        )


class TestToolCallReasoningPreservation:
    """reasoning_content must be preserved exactly when tool_calls are present."""

    def test_assistant_tool_call_requires_reasoning_content(self):
        state = ConversationState(thinking_enabled=True)
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
        state = ConversationState(thinking_enabled=True)
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
            {"role": "assistant", "content": "", "reasoning_content": "r",
             "tool_calls": [{"id": "call_1", "type": "function",
                             "function": {"name": "w", "arguments": "{}"}}]},
            {"role": "user", "content": "非法插入"},  # breaks adjacency
            {"role": "tool", "tool_call_id": "call_1", "content": "24℃"},
        ]

        with pytest.raises(DeepSeekProtocolError):
            _assert_valid(messages, thinking_enabled=True)

    def test_valid_tool_sequence_passes(self):
        messages = [
            {"role": "user", "content": "查询天气"},
            {"role": "assistant", "content": "", "reasoning_content": "r",
             "tool_calls": [{"id": "call_1", "type": "function",
                             "function": {"name": "w", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "24℃"},
        ]
        # Should not raise
        _assert_valid(messages, thinking_enabled=True)

    def test_tool_call_id_mismatch_rejected(self):
        messages = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "", "reasoning_content": "r",
             "tool_calls": [{"id": "call_1", "type": "function",
                             "function": {"name": "w", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "wrong_id", "content": "x"},
        ]
        with pytest.raises(DeepSeekProtocolError):
            _assert_valid(messages, thinking_enabled=True)

    def test_non_thinking_does_not_require_reasoning_content(self):
        state = ConversationState(thinking_enabled=False)
        state.add_user("Hi")
        # Should not raise in non-thinking mode
        state.add_assistant(
            content="",
            tool_calls=[{
                "id": "call_1", "type": "function",
                "function": {"name": "test", "arguments": "{}"},
            }],
        )
        assert len(state.messages) == 2

    def test_validate_returns_issues_not_raises(self):
        """validate_deepseek_messages returns issues, doesn't raise."""
        issues = validate_deepseek_messages(
            [{"role": "developer", "content": "Hi"}],
            thinking_enabled=False,
        )
        assert isinstance(issues, list)
        assert any(i.code == "invalid_role" for i in issues)

    def test_null_content_repaired_to_empty(self):
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}},
            ]},
            {"role": "tool", "tool_call_id": "c1", "content": "r"},
        ]
        repaired = repair_deepseek_messages(messages, thinking_enabled=False)
        assert repaired[1]["content"] == ""
