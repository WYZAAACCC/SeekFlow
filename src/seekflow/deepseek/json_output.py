"""DeepSeek JSON Output mode helpers.

DeepSeek JSON Output requires:
- response_format={"type": "json_object"}
- Prompt must contain the word "json"
- An example JSON output should be included
- max_tokens should be set appropriately
"""
from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class StructuredOutputError(ValueError):
    """Raised when JSON Output parsing or validation fails."""
    pass


def build_json_output_messages(
    *,
    user_prompt: str,
    schema: type[BaseModel],
    example: dict | None = None,
) -> list[dict]:
    """Build messages for a JSON Output request.

    Includes the schema and example in the system prompt as required
    by the DeepSeek JSON Output API.
    """
    system = (
        "You must output valid json only.\n\n"
        "Expected JSON schema:\n"
        f"{json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)}"
    )
    if example is not None:
        system += (
            "\n\nExample JSON output:\n"
            f"{json.dumps(example, ensure_ascii=False, indent=2)}"
        )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]


def parse_json_output(content: str, schema: type[T]) -> T:
    """Parse and validate JSON Output from a DeepSeek response."""
    if not content or not content.strip():
        raise StructuredOutputError("DeepSeek JSON Output returned empty content.")

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise StructuredOutputError(f"Invalid JSON in output: {exc}") from exc

    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise StructuredOutputError(f"Schema validation failed: {exc}") from exc
