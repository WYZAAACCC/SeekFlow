"""JSON Schema validation for tool arguments — model hallucination defense."""
from __future__ import annotations

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


def validate_tool_arguments(
    schema: dict[str, Any],
    arguments: dict[str, Any],
) -> list[ValidationIssue]:
    """Validate tool arguments against the JSON Schema.

    Returns empty list on success, or a list of ValidationIssue.
    """
    if not schema or schema.get("type") != "object":
        return []
    if not schema.get("properties"):
        return []

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
