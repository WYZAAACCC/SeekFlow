"""Structured output support — response_format and Pydantic integration."""
from __future__ import annotations

from typing import Any


def structured_output(model_cls: type) -> Any:
    """Return a factory that validates output against a Pydantic-like model.

    Usage:
        result = structured_output(MyModel)(raw_json)
    """
    def parse(raw: str):
        return model_cls.model_validate_json(raw)
    return parse


class StructuredOutputError(Exception):
    """Raised when structured output validation fails."""
    pass
