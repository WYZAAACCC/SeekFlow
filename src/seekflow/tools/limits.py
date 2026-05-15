"""Resource limit enforcement — input/output size gating for tool execution."""
from __future__ import annotations

import json
from typing import Any


class ToolInputTooLarge(ValueError):
    """Raised when serialized tool arguments exceed max_input_bytes."""


class ToolOutputTooLarge(ValueError):
    """Raised when tool output exceeds max_output_bytes."""


def estimate_json_bytes(value: Any) -> int:
    """Estimate the UTF-8 byte size of *value* when serialized as JSON."""
    try:
        raw = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        raw = str(value)
    return len(raw.encode("utf-8"))


def enforce_input_limit(arguments: dict[str, Any], max_bytes: int) -> None:
    """Raise ToolInputTooLarge if *arguments* exceed *max_bytes*."""
    size = estimate_json_bytes(arguments)
    if size > max_bytes:
        raise ToolInputTooLarge(
            f"Tool arguments size ({size} bytes) exceeds limit ({max_bytes} bytes)"
        )


def serialize_bounded(value: Any, max_bytes: int) -> tuple[str, bool]:
    """Serialize *value* to a string, truncating safely if it exceeds *max_bytes*.

    Returns (serialized_string, was_truncated).
    Truncation is byte-safe: cuts at UTF-8 boundary and appends a notice.
    """
    if isinstance(value, str):
        raw = value
    else:
        try:
            raw = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            raw = str(value)

    b = raw.encode("utf-8")
    if len(b) <= max_bytes:
        return raw, False

    truncated_bytes = b[:max_bytes]
    truncated = truncated_bytes.decode("utf-8", errors="ignore")
    return truncated + "\n...[truncated by max_output_bytes]...", True
