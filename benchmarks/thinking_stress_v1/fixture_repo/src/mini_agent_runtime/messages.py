"""Message construction for DeepSeek multi-turn tool-call protocol.

BUG: drops reasoning_content from assistant messages during build_next_messages.
"""

from __future__ import annotations

from typing import Any


def build_next_messages(
    history: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build next API messages after tool execution.

    BUG:
    - Drops reasoning_content from previous assistant messages.
    - Does not preserve tool_call_id order reliably.
    """
    messages: list[dict[str, Any]] = []

    for msg in history:
        if msg.get("role") == "assistant":
            copied = {
                "role": "assistant",
                "content": msg.get("content", ""),
            }
            if "tool_calls" in msg:
                copied["tool_calls"] = msg["tool_calls"]
            # BUG: reasoning_content omitted
            messages.append(copied)
        else:
            messages.append(dict(msg))

    for result in tool_results:
        messages.append({
            "role": "tool",
            "tool_call_id": result["tool_call_id"],
            "content": result["content"],
        })

    return messages
