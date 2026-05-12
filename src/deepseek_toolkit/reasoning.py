"""Reasoning content inspector for DeepSeek R1 models."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ConsistencyResult:
    """Result of checking reasoning consistency with actual tool calls."""

    status: str  # "CONSISTENT" | "MISMATCH" | "NO_REASONING"
    reasoning_mentions: list[str] = field(default_factory=list)
    actual_calls: list[str] = field(default_factory=list)


def extract_tool_names(reasoning: str, registered_names: list[str]) -> set[str]:
    """Extract tool names mentioned in reasoning text using word-boundary regex.

    Each tool name is escaped to avoid false matches from special characters,
    and word boundaries (\\b) prevent substring matches (e.g. get_weather
    won't match get_weather_v2).
    """
    if not reasoning or not registered_names:
        return set()

    found: set[str] = set()
    for name in registered_names:
        pattern = rf"\b{re.escape(name)}\b"
        if re.search(pattern, reasoning):
            found.add(name)
    return found


def check_consistency(
    reasoning: str | None,
    actual_tool_names: list[str],
    registered_names: list[str],
) -> ConsistencyResult:
    """Check whether reasoning mentions match the tools actually called.

    Returns:
        ConsistencyResult with status and details about any mismatch.
    """
    if not reasoning:
        return ConsistencyResult(status="NO_REASONING")

    mentions = extract_tool_names(reasoning, registered_names)

    if not mentions:
        # Reasoning doesn't mention any tool → not a mismatch
        return ConsistencyResult(
            status="CONSISTENT",
            actual_calls=list(actual_tool_names),
        )

    if set(mentions) == set(actual_tool_names):
        return ConsistencyResult(
            status="CONSISTENT",
            reasoning_mentions=sorted(mentions),
            actual_calls=list(actual_tool_names),
        )

    return ConsistencyResult(
        status="MISMATCH",
        reasoning_mentions=sorted(mentions),
        actual_calls=list(actual_tool_names),
    )
