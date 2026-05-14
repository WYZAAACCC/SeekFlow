"""Test that caching operations don't break DeepSeek protocol invariants."""
from seekflow._runtime_base import trim_messages
from seekflow.cache import append_only_compress


def test_tool_call_reasoning_not_compressed():
    """Cache compression must never remove reasoning_content from tool_calls."""
    messages = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "Q"},
        {"role": "assistant", "content": "", "reasoning_content": "I will call tools.",
         "tool_calls": [
             {"id": "call_1", "type": "function", "function": {"name": "f", "arguments": "{}"}},
         ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "result"},
    ]
    compressed = append_only_compress(messages, max_context_tokens=100000)
    # Find the assistant message with tool_calls
    assistant_msgs = [m for m in compressed if m.get("role") == "assistant" and m.get("tool_calls")]
    for m in assistant_msgs:
        assert "reasoning_content" in m
        assert m["reasoning_content"] is not None


def test_tool_call_blocks_not_split_by_cache_compression():
    """Cache compression must not separate assistant(tool_calls) from tool results."""
    messages = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "Q1"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "r1"},
        {"role": "user", "content": "Q2"},
    ]
    compressed = append_only_compress(messages, max_context_tokens=100000)

    # Find assistant with tool_calls — its tool result should follow
    for i, m in enumerate(compressed):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            call_ids = [tc["id"] for tc in m["tool_calls"]]
            for j, cid in enumerate(call_ids):
                result_idx = i + 1 + j
                if result_idx < len(compressed):
                    tool_msg = compressed[result_idx]
                    assert tool_msg.get("role") == "tool"
                    assert tool_msg.get("tool_call_id") == cid


def test_trim_preserves_tool_call_blocks_integration():
    """Verify tool_call + N tool_results stay together after trimming."""
    messages = [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "Old"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "old result"},
        {"role": "user", "content": "Latest"},
    ]
    trimmed = trim_messages(messages, max_context_tokens=120000)
    # With a large budget, everything is kept
    tool_msgs = [m for m in trimmed if m.get("role") == "tool"]
    # If the assistant with tool_calls is kept, the tool result must also be kept
    assistant_with_tc = [m for m in trimmed if m.get("role") == "assistant" and m.get("tool_calls")]
    if assistant_with_tc:
        assert len(tool_msgs) > 0
