"""Argument type coercion to match tool parameter schemas."""
from __future__ import annotations


def coerce_arguments(args: dict, parameters_schema: dict) -> tuple[dict, list[str]]:
    """Coerce argument values to match the expected types in the schema.

    Returns (corrected_args, change_log).
    """
    new_args = dict(args)
    changes: list[str] = []
    properties = parameters_schema.get("properties", {})

    for key, value in new_args.items():
        if key not in properties:
            continue

        prop_schema = properties[key]
        expected_type = prop_schema.get("type")
        if expected_type is None:
            continue

        new_value, changed = _coerce_value(key, value, expected_type)
        if changed:
            new_args[key] = new_value
            changes.append(f"coerced {key}: {type(value).__name__} -> {type(new_value).__name__}")

    return new_args, changes


def _coerce_value(key: str, value, expected_type: str) -> tuple:
    """Coerce a single value. Returns (new_value, changed)."""
    if expected_type == "integer":
        if isinstance(value, str) and _looks_like_int(value):
            return int(value), True
    elif expected_type == "number":
        if isinstance(value, str) and _looks_like_number(value):
            return float(value), True
    elif expected_type == "boolean":
        if isinstance(value, str):
            if value.lower() == "true":
                return True, True
            if value.lower() == "false":
                return False, True
    return value, False


def _looks_like_int(s: str) -> bool:
    try:
        int(s)
        return True
    except ValueError:
        return False


def _looks_like_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False
