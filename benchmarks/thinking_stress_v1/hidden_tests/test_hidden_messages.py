"""Hidden tests for messages.py — AGENTS CANNOT SEE THESE.

Tests edge cases in message construction that go beyond public tests.
"""

from mini_agent_runtime.messages import build_next_messages


def test_reasoning_content_not_merged_into_content():
    """reasoning_content must stay separate, not concatenated into content."""
    history = [
        {"role": "user", "content": "analyze"},
        {
            "role": "assistant",
            "content": "Let me check.",
            "reasoning_content": "I should inspect the file.",
            "tool_calls": [
                {"id": "call_1", "function": {"name": "check", "arguments": "{}"}}
            ],
        },
    ]
    tool_results = [{"tool_call_id": "call_1", "content": "ok"}]
    messages = build_next_messages(history, tool_results)
    assistant = messages[1]
    assert "I should inspect" not in assistant.get("content", "")
    assert assistant.get("reasoning_content") == "I should inspect the file."


def test_empty_reasoning_preserved_not_added():
    """If reasoning_content was empty, keep it empty — don't drop."""
    history = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "Hello!",
            "reasoning_content": "",
        },
    ]
    messages = build_next_messages(history, [])
    assert "reasoning_content" in messages[1]
    assert messages[1]["reasoning_content"] == ""


def test_tool_results_preserve_order():
    """Tool results must match the order of tool_call_ids from assistant."""
    history = [
        {"role": "user", "content": "task"},
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "I'll run three tools.",
            "tool_calls": [
                {"id": "call_x", "function": {"name": "a", "arguments": "{}"}},
                {"id": "call_y", "function": {"name": "b", "arguments": "{}"}},
                {"id": "call_z", "function": {"name": "c", "arguments": "{}"}},
            ],
        },
    ]
    tool_results = [
        {"tool_call_id": "call_x", "content": "rx"},
        {"tool_call_id": "call_y", "content": "ry"},
        {"tool_call_id": "call_z", "content": "rz"},
    ]
    messages = build_next_messages(history, tool_results)
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["call_x", "call_y", "call_z"]


def test_no_false_reasoning_when_absent():
    """If assistant msg had no reasoning_content, don't add empty key."""
    history = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "Done.",
        },
    ]
    messages = build_next_messages(history, [])
    assert "reasoning_content" not in messages[1]
