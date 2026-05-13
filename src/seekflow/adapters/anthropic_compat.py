"""Anthropic-compatible endpoint adapter.

Converts Anthropic Messages API format to DeepSeek format for use with
POST https://api.deepseek.com/anthropic/v1/messages.
"""
from __future__ import annotations

import json


def _anthropic_to_deepseek_messages(anthropic_messages: list[dict]) -> list[dict]:
    """Convert Anthropic-format messages to DeepSeek-format messages."""
    result: list[dict] = []
    for msg in anthropic_messages:
        role = msg["role"]
        content = msg.get("content")

        if isinstance(content, str):
            # Plain string content — pass through
            result.append({"role": role, "content": content})
            continue

        if isinstance(content, list):
            text_parts: list[str] = []
            tool_calls: list[dict] = []
            tool_results: list[dict] = []

            for block in content:
                block_type = block.get("type")

                if block_type == "text":
                    text_parts.append(block.get("text", "").rstrip())

                elif block_type == "tool_use":
                    tool_calls.append({
                        "id": block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                        },
                    })

                elif block_type == "tool_result":
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": block.get("content", ""),
                    })

                elif block_type == "image":
                    raise ValueError(
                        "Image content blocks are not supported by DeepSeek V4. "
                        "Remove image blocks before sending."
                    )

            # Add assistant message with content and tool_calls
            if role == "assistant":
                assistant_msg: dict = {"role": role}
                if text_parts:
                    assistant_msg["content"] = " ".join(text_parts)
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                result.append(assistant_msg)
            elif role == "user":
                if tool_results:
                    # When user content contains tool results, emit separate tool messages
                    result.extend(tool_results)
                    if text_parts:
                        result.append({"role": "user", "content": " ".join(text_parts)})
                elif text_parts:
                    result.append({"role": role, "content": " ".join(text_parts)})
            else:
                if text_parts:
                    result.append({"role": role, "content": " ".join(text_parts)})
        else:
            result.append({"role": role, "content": str(content)})

    return result
