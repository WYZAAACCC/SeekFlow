"""Shared runtime utilities — used by both ToolRuntime and AsyncToolRuntime.

These are pure functions (no self), factored out to eliminate ~100 lines
of copy-paste duplication between the sync and async runtime implementations.
"""

from __future__ import annotations

from seekflow.token_counter import count_tokens


def estimate_tokens(messages: list[dict]) -> int:
    """Accurate token estimate using tiktoken when available."""
    return count_tokens(messages)


def trim_messages(
    messages: list[dict],
    max_context_tokens: int | None,
) -> list[dict]:
    """Trim oldest non-system messages to stay under max_context_tokens.

    Walks backwards, keeping tool-call/result pairs intact.
    """
    if max_context_tokens is None:
        return messages

    if estimate_tokens(messages) <= max_context_tokens:
        return messages

    system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
    rest = messages[1:] if system_msg else list(messages)

    kept: list[dict] = []
    budget = max_context_tokens - (
        estimate_tokens([system_msg]) if system_msg else 0
    )

    i = len(rest) - 1
    while i >= 0:
        chunk: list[dict] = []
        if rest[i].get("role") == "tool":
            chunk.append(rest[i])
            i -= 1
            while i >= 0:
                chunk.append(rest[i])
                if rest[i].get("role") == "assistant" and rest[i].get("tool_calls"):
                    i -= 1
                    break
                i -= 1
            else:
                continue
        else:
            chunk.append(rest[i])
            i -= 1

        cost = estimate_tokens(chunk)
        if budget - cost < 0:
            break
        budget -= cost
        kept = list(reversed(chunk)) + kept

    result = [system_msg] if system_msg else []
    result.extend(kept)
    return repair_message_order(result)


def repair_message_order(messages: list[dict]) -> list[dict]:
    """Ensure message list is API-valid: no orphaned tool messages,
    first non-system is a user."""
    if not messages:
        return messages

    cleaned: list[dict] = []
    for m in messages:
        if m.get("role") == "tool":
            if not cleaned or cleaned[-1].get("role") != "assistant" or not cleaned[-1].get("tool_calls"):
                continue
        cleaned.append(m)

    for j, m in enumerate(cleaned):
        if m.get("role") != "system":
            if m.get("role") != "user":
                cleaned.insert(j, {"role": "user", "content": ""})
            break
    else:
        cleaned.append({"role": "user", "content": ""})

    start = 0
    if cleaned and cleaned[0].get("role") == "system":
        start = 1
    while len(cleaned) > start and cleaned[start].get("role") not in ("user",):
        cleaned.pop(start)

    return cleaned
