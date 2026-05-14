"""DeepSeek Strict Schema Compiler — beta endpoint strict mode support.

DeepSeek strict mode requires:
- base_url = https://api.deepseek.com/beta
- strict=true on every function
- all objects have additionalProperties=false + all properties required
- no unsupported JSON Schema keywords
"""
from __future__ import annotations

import copy
from typing import Any


UNSUPPORTED_KEYWORDS: frozenset[str] = frozenset({
    "$schema", "$defs", "definitions",
    "oneOf", "allOf", "not", "if", "then", "else",
    "prefixItems", "patternProperties", "additionalItems",
    "dependentRequired", "dependentSchemas",
})


class StrictSchemaError(ValueError):
    """Raised when a schema cannot be made strict-compatible."""
    pass


class DeepSeekStrictSchemaCompiler:
    """Compile generic JSON Schema into DeepSeek strict-compatible form.

    Rules:
    1. Remove unsupported keywords
    2. Force additionalProperties=false on all objects
    3. All object properties become required
    4. Validate: max nesting depth 3, top-level must be object
    """

    def compile(self, schema: dict[str, Any]) -> dict[str, Any]:
        compiled = copy.deepcopy(schema)
        self._strip_unsupported(compiled)
        self._force_object_rules(compiled)
        self._validate(compiled)
        return compiled

    def _strip_unsupported(self, node: Any) -> None:
        if isinstance(node, dict):
            for key in list(node.keys()):
                if key in UNSUPPORTED_KEYWORDS:
                    node.pop(key)
            for value in node.values():
                self._strip_unsupported(value)
        elif isinstance(node, list):
            for item in node:
                self._strip_unsupported(item)

    def _force_object_rules(self, node: Any) -> None:
        if not isinstance(node, dict):
            return

        if node.get("type") == "object":
            props = node.setdefault("properties", {})
            if not isinstance(props, dict):
                raise StrictSchemaError("object.properties must be a dict")
            node["required"] = list(props.keys())
            node["additionalProperties"] = False
            for child in props.values():
                self._force_object_rules(child)

        if node.get("type") == "array" and "items" in node:
            self._force_object_rules(node["items"])

    def _validate(self, schema: dict[str, Any]) -> None:
        if schema.get("type") != "object":
            raise StrictSchemaError("Top-level parameters schema must be an object")
        self._validate_node(schema, depth=0)

    def _validate_node(self, node: Any, depth: int) -> None:
        if not isinstance(node, dict):
            return
        if depth > 3:
            raise StrictSchemaError(f"Schema nesting exceeds 3 levels")

        if node.get("type") == "object":
            props = node.get("properties", {})
            required = node.get("required", [])
            if set(required) != set(props.keys()):
                raise StrictSchemaError("All object properties must be required")
            if node.get("additionalProperties") is not False:
                raise StrictSchemaError("additionalProperties must be false")
            # Only recurse into object children for depth tracking
            for value in props.values():
                if isinstance(value, dict):
                    self._validate_node(value, depth + 1)
        elif node.get("type") == "array" and "items" in node:
            items = node["items"]
            if isinstance(items, dict):
                self._validate_node(items, depth + 1)


def base_url_for_request(*, strict_tools: bool = False, beta_feature: bool = False) -> str:
    """Return the correct base URL for the given request features."""
    if strict_tools or beta_feature:
        return "https://api.deepseek.com/beta"
    return "https://api.deepseek.com"
