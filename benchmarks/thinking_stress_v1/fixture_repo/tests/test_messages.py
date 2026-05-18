"""Tests for messages.py — Message protocol correctness."""

from mini_agent_runtime.messages import build_next_messages


def test_preserves_reasoning_content_when_assistant_has_tool_calls():
    history = [
        {"role": "user", "content": "analyze"},
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "I need to call inspect_file first.",
            "tool_calls": [
                {"id": "call_1", "function": {"name": "inspect_file", "arguments": "{}"}}
            ],
        },
    ]
    tool_results = [{"tool_call_id": "call_1", "content": '{"ok": true}'}]

    messages = build_next_messages(history, tool_results)

    assistant = messages[1]
    assert assistant["reasoning_content"] == "I need to call inspect_file first."
    assert assistant["tool_calls"][0]["id"] == "call_1"


def test_preserves_reasoning_content_empty():
    """reasoning_content present but empty should be preserved (not dropped)."""
    history = [
        {"role": "user", "content": "hello"},
        {
            "role": "assistant",
            "content": "Hi there.",
            "reasoning_content": "",
        },
    ]
    messages = build_next_messages(history, [])
    assert "reasoning_content" in messages[1]
    assert messages[1]["reasoning_content"] == ""


def test_multiple_assistant_messages_all_preserve_reasoning():
    history = [
        {"role": "user", "content": "task"},
        {
            "role": "assistant",
            "content": "Let me check.",
            "reasoning_content": "First step reasoning",
            "tool_calls": [
                {"id": "call_a", "function": {"name": "check", "arguments": "{}"}}
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_a",
            "content": "result",
        },
        {
            "role": "assistant",
            "content": "Now I know enough.",
            "reasoning_content": "After check, I can proceed.",
        },
    ]
    messages = build_next_messages(history, [])
    assert messages[1]["reasoning_content"] == "First step reasoning"
    assert messages[3]["reasoning_content"] == "After check, I can proceed."


def test_tool_messages_preserved_correctly():
    history = [
        {"role": "user", "content": "run"},
    ]
    tool_results = [
        {"tool_call_id": "call_x", "content": "result_x"},
        {"tool_call_id": "call_y", "content": "result_y"},
    ]
    messages = build_next_messages(history, tool_results)
    assert messages[1]["role"] == "tool"
    assert messages[1]["tool_call_id"] == "call_x"
    assert messages[2]["role"] == "tool"
    assert messages[2]["tool_call_id"] == "call_y"
