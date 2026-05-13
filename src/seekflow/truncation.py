"""JSON-aware truncation with structure preservation."""
from __future__ import annotations

import enum
import json


class TruncationStrategy(enum.Enum):
    SIMPLE = "simple"
    JSON_AWARE = "json_aware"
    PRIORITY = "priority"


def truncate_result(
    result,
    max_result_chars: int,
    strategy: TruncationStrategy = TruncationStrategy.JSON_AWARE,
    keep_fields: list[str] | None = None,
):
    """Truncate a result (string or other) to fit within max_result_chars."""
    if not isinstance(result, str):
        return result

    if len(result) <= max_result_chars:
        return result

    if strategy == TruncationStrategy.SIMPLE:
        return _simple_truncate(result, max_result_chars)

    try:
        if strategy == TruncationStrategy.PRIORITY:
            return _priority_truncate(result, max_result_chars, keep_fields)
        return _json_aware_truncate(result, max_result_chars)
    except Exception:
        return _simple_truncate(result, max_result_chars)


def _simple_truncate(text: str, limit: int) -> str:
    suffix = f"[truncated: original {len(text)} chars]"
    if len(suffix) >= limit:
        return suffix[:limit]
    return text[:limit - len(suffix)] + suffix


def _json_aware_truncate(text: str, limit: int) -> str:
    data = json.loads(text)
    was_list = isinstance(data, list)
    if was_list:
        data = {"results": data}
    if not isinstance(data, dict):
        return _simple_truncate(text, limit)
    return _truncate_dict(data, limit, len(text), was_list)


def _priority_truncate(text: str, limit: int, keep_fields: list[str] | None) -> str:
    data = json.loads(text)
    was_list = isinstance(data, list)
    if was_list:
        data = {"results": data}
    if not isinstance(data, dict):
        return _simple_truncate(text, limit)

    # Reorder keys: keep_fields first (in specified order), then remaining in original order
    if keep_fields:
        keep_set = set(keep_fields)
        ordered = [k for k in keep_fields if k in data]
        ordered += [k for k in data if k not in keep_set]
        data = {k: data[k] for k in ordered}

    return _truncate_dict(data, limit, len(text), was_list)


def _truncate_dict(data: dict, limit: int, original_chars: int, was_list: bool = False) -> str:
    """Core truncation algorithm operating on a parsed dict."""

    def _probe_len(d: dict) -> int:
        probe = dict(d)
        probe["_truncation"] = {"truncated": True, "original_chars": original_chars}
        return len(json.dumps(probe, ensure_ascii=False))

    result: dict = {}
    truncated: list[str] = []
    items_kept = 0
    items_total = 0

    for key, value in data.items():
        if isinstance(value, list):
            kept: list = []
            for item in value:
                trial = dict(result)
                trial[key] = kept + [item]
                if _probe_len(trial) > limit:
                    break
                kept.append(item)
            result[key] = kept
            items_total = len(value)
            items_kept = len(kept)
            if items_kept < items_total:
                truncated.append(f"{key}[{items_kept}:]")
        else:
            trial = dict(result)
            trial[key] = value
            if _probe_len(trial) > limit:
                if isinstance(value, dict):
                    result[key] = {"...": "truncated"}
                truncated.append(key)
            else:
                result[key] = value

    # Shrink the last array field so body + minimal metadata fits
    for key, value in list(result.items()):
        if not isinstance(value, list) or not value:
            continue
        while value:
            probe = dict(result)
            probe["_truncation"] = {
                "truncated": bool(truncated) or was_list,
                "original_chars": original_chars,
            }
            if len(json.dumps(probe, ensure_ascii=False)) <= limit:
                break
            value.pop()
            items_kept = len(value)
        result[key] = value
        if items_kept < items_total:
            prefix = f"{key}["
            for i, t in enumerate(truncated):
                if t.startswith(prefix):
                    truncated[i] = f"{key}[{items_kept}:]"
                    break
            else:
                truncated.append(f"{key}[{items_kept}:]")

    body_len = len(json.dumps({k: v for k, v in result.items()}, ensure_ascii=False))

    # Try metadata levels from most detailed to most compact
    metadata_levels = [
        {
            "truncated": bool(truncated) or was_list,
            "original_chars": original_chars,
            "kept_chars": body_len,
            "truncated_fields": truncated,
            "items_kept": items_kept,
            "items_total": items_total,
        },
        {
            "truncated": bool(truncated) or was_list,
            "original_chars": original_chars,
            "kept_chars": body_len,
        },
        {
            "truncated": bool(truncated) or was_list,
            "original_chars": original_chars,
        },
    ]

    for meta in metadata_levels:
        out = dict(result)
        out["_truncation"] = meta
        output = json.dumps(out, ensure_ascii=False)
        if len(output) <= limit:
            return output

    # Absolute minimum: just a _truncation block, no data
    minimal = {"_truncation": {"truncated": True, "original_chars": original_chars}}
    output = json.dumps(minimal, ensure_ascii=False)
    if len(output) <= limit:
        return output

    return _simple_truncate(json.dumps(data, ensure_ascii=False), limit)
