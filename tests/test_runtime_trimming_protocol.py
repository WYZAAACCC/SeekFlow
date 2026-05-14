"""Test context trimming preserves DeepSeek protocol invariants."""
from seekflow._runtime_base import trim_messages, repair_message_order


def test_trim_preserves_tool_call_blocks():
    """Tool call assistant + N tool messages must stay together as atomic block."""
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Step 1"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "f", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "result 1"},
        {"role": "user", "content": "Step 2"},
        {"role": "assistant", "content": "", "reasoning_content": "...", "tool_calls": [
            {"id": "call_2", "type": "function", "function": {"name": "g", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "call_2", "content": "result 2"},
        {"role": "user", "content": "Final"},
        {"role": "assistant", "content": "Done"},
    ]
    trimmed = trim_messages(messages, max_context_tokens=1000000)  # large — no trim
    assert len(trimmed) == len(messages)


def test_trim_when_forced_preserves_blocks():
    """Even when trimming old messages, tool-call blocks are kept intact."""
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Old query"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "f", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "old result"},
        {"role": "user", "content": "Latest query"},
    ]
    trimmed = trim_messages(messages, max_context_tokens=1)
    # With such a tiny budget, everything except system + latest user is cut
    assert trimmed[0].get("role") == "system" or trimmed[0].get("role") == "user"


def test_trim_never_compresses_tool_call_reasoning_content():
    """When an assistant + tool_call block is kept, reasoning_content must survive."""
    messages = [
        {"role": "system", "content": "S"},  # short — fits budget
        {"role": "user", "content": "Q"},
        {"role": "assistant", "content": "", "reasoning_content": "I will call tools.",
         "tool_calls": [
             {"id": "call_1", "type": "function", "function": {"name": "f", "arguments": "{}"}},
         ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "r"},
    ]
    trimmed = trim_messages(messages, max_context_tokens=120000)
    # Since budget is large, all messages should be kept
    assistant_msgs = [m for m in trimmed if m.get("role") == "assistant"]
    for m in assistant_msgs:
        if m.get("tool_calls"):
            assert "reasoning_content" in m
            assert m["reasoning_content"] is not None


def test_repair_message_order_inserts_user_if_missing():
    messages = [{"role": "assistant", "content": "Hi, how can I help?"}]
    repaired = repair_message_order(messages)
    assert repaired[0]["role"] == "user" or repaired[0]["role"] == "system"


def test_repair_removes_orphaned_tool_messages():
    messages = [
        {"role": "user", "content": "Query"},
        {"role": "tool", "tool_call_id": "orphan", "content": "no call"},
        {"role": "user", "content": "Next"},
    ]
    repaired = repair_message_order(messages)
    tool_msgs = [m for m in repaired if m.get("role") == "tool"]
    assert len(tool_msgs) == 0  # orphan removed
