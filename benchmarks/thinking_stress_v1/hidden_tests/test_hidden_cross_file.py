"""Hidden cross-file integration tests — AGENTS CANNOT SEE THESE.

Tests that bugs interact across module boundaries.
"""

from mini_agent_runtime.messages import build_next_messages
from mini_agent_runtime.tool_runtime import execute_parallel_tool_calls


def test_reasoning_preserved_through_multi_turn_tool_loop():
    """End-to-end: reasoning_content survives a complete multi-turn tool-call cycle.

    Simulates: user msg → assistant (reasoning + tool_calls) → tool results →
    build_next_messages → next assistant (more reasoning) → more tools →
    build_next_messages again.

    If messages.py drops reasoning_content, the second assistant loses context
    and the tool call sequence breaks.
    """
    # Turn 1: assistant plans and calls tool
    turn1 = [
        {"role": "user", "content": "analyze security"},
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "I should check the security module first. It likely has path traversal and SSRF bugs.",
            "tool_calls": [
                {"id": "call_1", "function": {"name": "read_file", "arguments": '{"path": "security.py"}'}}
            ],
        },
    ]
    tool_results_1 = [{"tool_call_id": "call_1", "content": "def safe_join(...) ... def validate_url(...) ..."}]

    messages_1 = build_next_messages(turn1, tool_results_1)

    # Turn 2: assistant reasons more based on file content, plans next tools
    turn2 = messages_1 + [
        {
            "role": "assistant",
            "content": "",
            "reasoning_content": "Found two bugs: safe_join has string prefix + encoded traversal bypass. validate_url only blocks localhost string. I need to fix both with ipaddress and resolve().",
            "tool_calls": [
                {"id": "call_2", "function": {"name": "apply_patch", "arguments": '{"path": "security.py"}'}}
            ],
        },
    ]

    tool_results_2 = [{"tool_call_id": "call_2", "content": "ok"}]
    messages_2 = build_next_messages(turn2, tool_results_2)

    # Verify: reasoning_content survived both turns
    assistants = [m for m in messages_2 if m["role"] == "assistant"]
    assert len(assistants) == 2, f"Expected 2 assistant messages, got {len(assistants)}"

    # First assistant's reasoning preserved
    assert assistants[0].get("reasoning_content") == (
        "I should check the security module first. It likely has path traversal and SSRF bugs."
    ), f"First reasoning lost: {assistants[0].get('reasoning_content')}"

    # Second assistant's reasoning preserved
    assert "ipaddress" in assistants[1].get("reasoning_content", ""), (
        f"Second reasoning corrupted: {assistants[1].get('reasoning_content')}"
    )

    # Tool results in correct order
    tool_msgs = [m for m in messages_2 if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["call_1", "call_2"]


def test_tool_result_order_matches_tool_call_order():
    """The tool_runtime must return results matching tool_call_id sequence order.

    This isn't just about stable output — the DeepSeek API protocol requires
    tool results to match the original tool_calls order for the model to
    correctly associate results with calls.
    """
    import time

    calls = [
        {"id": "t1", "function": {"name": "slow", "arguments": {"value": "a", "delay": 0.03}}},
        {"id": "t2", "function": {"name": "slow", "arguments": {"value": "b", "delay": 0.01}}},
        {"id": "t3", "function": {"name": "slow", "arguments": {"value": "c", "delay": 0.02}}},
    ]

    def slow(value: str, delay: float):
        time.sleep(delay)
        return value

    results = execute_parallel_tool_calls(calls, {"slow": slow})

    # Verify correct order and correct content mapping
    assert [r["tool_call_id"] for r in results] == ["t1", "t2", "t3"]
    assert [r["content"] for r in results] == ["a", "b", "c"]
