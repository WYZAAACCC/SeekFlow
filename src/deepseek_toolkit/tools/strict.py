"""Strict-mode schema compatibility checker for DeepSeek tools."""
from __future__ import annotations

from pydantic import BaseModel, Field


class StrictCheckIssue(BaseModel):
    level: str  # "warning" | "error"
    path: str
    message: str
    suggestion: str | None = None


class StrictCheckResult(BaseModel):
    ok: bool
    issues: list[StrictCheckIssue] = Field(default_factory=list)


def check_strict_compatibility(tools_schema: list[dict]) -> StrictCheckResult:
    """Check if a tools schema is compatible with DeepSeek strict mode."""
    issues: list[StrictCheckIssue] = []

    for i, tool in enumerate(tools_schema):
        func = tool.get("function", {})
        prefix = f"tools[{i}].function"

        name = func.get("name", "")
        if not name or not _is_valid_function_name(name):
            issues.append(StrictCheckIssue(
                level="error",
                path=f"{prefix}.name",
                message=f"Invalid function name: '{name}'",
                suggestion="Use letters, digits, underscores, and hyphens only.",
            ))

        description = func.get("description", "")
        if not description:
            issues.append(StrictCheckIssue(
                level="warning",
                path=f"{prefix}.description",
                message="Description is empty",
                suggestion="Provide a description for better model accuracy.",
            ))

        params = func.get("parameters")
        if not params:
            issues.append(StrictCheckIssue(
                level="error",
                path=f"{prefix}.parameters",
                message="Missing parameters definition",
                suggestion="Parameters must be an object with 'type': 'object'.",
            ))
            continue

        if params.get("type") != "object":
            issues.append(StrictCheckIssue(
                level="error",
                path=f"{prefix}.parameters.type",
                message="Parameters type must be 'object'",
                suggestion="Set 'type': 'object' in parameters.",
            ))

        properties = params.get("properties", {})
        if not properties:
            issues.append(StrictCheckIssue(
                level="warning",
                path=f"{prefix}.parameters.properties",
                message="No properties defined",
                suggestion="Define at least one property.",
            ))

        # Check nested schemas
        _check_schema_node(properties, f"{prefix}.parameters.properties", issues)
        _check_schema_node(params, f"{prefix}.parameters", issues)

    ok = not any(i.level == "error" for i in issues)
    return StrictCheckResult(ok=ok, issues=issues)


def _is_valid_function_name(name: str) -> bool:
    return all(c.isalnum() or c in "_-" for c in name) and len(name) > 0


def _check_additional_properties(
    node: dict, path: str, issues: list[StrictCheckIssue]
) -> None:
    """DeepSeek strict mode requires additionalProperties: false on every object."""
    if node.get("type") == "object" and "additionalProperties" not in node:
        issues.append(StrictCheckIssue(
            level="warning",
            path=path,
            message="DeepSeek strict mode recommends 'additionalProperties': false for object schemas",
            suggestion="Add 'additionalProperties': false to this object.",
        ))

    for key, value in node.items():
        if isinstance(value, dict):
            _check_additional_properties(value, f"{path}.{key}", issues)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    _check_additional_properties(item, f"{path}.{key}[{i}]", issues)


def _check_schema_node(
    node: dict, path: str, issues: list[StrictCheckIssue], depth: int = 0
) -> int:
    """Recursively check a schema node. Returns max depth reached."""
    if depth > 3:
        issues.append(StrictCheckIssue(
            level="warning",
            path=path,
            message="Schema nesting exceeds 3 levels, may cause strict-mode issues",
        ))
        return depth

    for key in ("anyOf", "oneOf", "allOf"):
        if key in node:
            issues.append(StrictCheckIssue(
                level="warning",
                path=path,
                message=f"'{key}' is present, may cause strict-mode issues",
                suggestion=f"Consider avoiding '{key}' for strict mode.",
            ))

    if "enum" in node and isinstance(node["enum"], list) and len(node["enum"]) == 0:
        issues.append(StrictCheckIssue(
            level="error",
            path=path,
            message="Empty enum is not allowed in strict mode",
            suggestion="Provide at least one enum value.",
        ))

    if "default" in node:
        issues.append(StrictCheckIssue(
            level="warning",
            path=path,
            message="'default' may cause strict-mode issues",
        ))

    if node.get("type") == "object":
        _check_additional_properties(node, path, issues)

    max_depth = depth
    for key, value in node.items():
        if isinstance(value, dict):
            child_depth = _check_schema_node(value, f"{path}.{key}", issues, depth + 1)
            max_depth = max(max_depth, child_depth)

    return max_depth
