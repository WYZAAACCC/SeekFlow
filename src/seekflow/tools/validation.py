"""JSON Schema validation for tool arguments — model hallucination defense."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str


class ToolArgumentValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        joined = "; ".join(f"{i.path}: {i.message}" for i in issues[:5])
        super().__init__(joined)


def close_object_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a copy where every object node defaults to additionalProperties=False.

    This blocks LLM-hallucinated extra arguments that are not declared in the
    tool's parameter schema.
    """
    def _close(node: Any) -> Any:
        if isinstance(node, dict):
            node = copy.deepcopy(node)
            if node.get("type") == "object" or "properties" in node:
                node.setdefault("type", "object")
                node.setdefault("additionalProperties", False)
                props = node.get("properties", {})
                for _key, sub in list(props.items()):
                    props[_key] = _close(sub)
            if node.get("type") == "array" and "items" in node:
                node["items"] = _close(node["items"])
            for key in ("anyOf", "oneOf", "allOf"):
                if key in node and isinstance(node[key], list):
                    node[key] = [_close(x) for x in node[key]]
            return node
        return node
    return _close(schema)


def validate_tool_arguments(
    schema: dict[str, Any],
    arguments: dict[str, Any],
    *,
    close_schema: bool = True,
) -> list[ValidationIssue]:
    """Validate tool arguments against the JSON Schema.

    By default, closes the schema (additionalProperties=False) to reject
    hallucinated extra arguments. Pass close_schema=False to skip.

    Returns empty list on success, or a list of ValidationIssue.
    """
    if not schema or schema.get("type") != "object":
        return []
    if not schema.get("properties"):
        return []

    if close_schema:
        schema = close_object_schema(schema)

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(arguments), key=lambda e: list(e.absolute_path))

    if not errors:
        return []

    return [
        ValidationIssue(
            path=".".join(str(p) for p in error.absolute_path) or "$",
            message=error.message,
        )
        for error in errors
    ]
