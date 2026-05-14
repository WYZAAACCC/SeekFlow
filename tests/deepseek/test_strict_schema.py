"""Tests for DeepSeekStrictSchemaCompiler."""
from __future__ import annotations

import pytest

from seekflow.deepseek.strict_schema import (
    DeepSeekStrictSchemaCompiler,
    StrictSchemaError,
    base_url_for_request,
)


class TestStrictSchemaCompiler:
    def test_forces_required_and_no_extra_properties(self):
        compiler = DeepSeekStrictSchemaCompiler()
        schema = {
            "type": "object",
            "properties": {"city": {"type": "string"}, "date": {"type": "string"}},
        }
        out = compiler.compile(schema)
        assert out["required"] == ["city", "date"]
        assert out["additionalProperties"] is False

    def test_nested_object_rules(self):
        compiler = DeepSeekStrictSchemaCompiler()
        schema = {
            "type": "object",
            "properties": {
                "user": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                }
            },
        }
        out = compiler.compile(schema)
        assert out["additionalProperties"] is False
        assert out["properties"]["user"]["additionalProperties"] is False
        assert out["properties"]["user"]["required"] == ["name"]

    def test_unsupported_keywords_removed(self):
        compiler = DeepSeekStrictSchemaCompiler()
        schema = {
            "type": "object",
            "$defs": {},
            "properties": {
                "x": {"oneOf": [{"type": "string"}, {"type": "integer"}], "type": "string"}
            },
        }
        out = compiler.compile(schema)
        assert "$defs" not in out
        assert "oneOf" not in out["properties"]["x"]

    def test_non_object_top_level_raises(self):
        compiler = DeepSeekStrictSchemaCompiler()
        with pytest.raises(StrictSchemaError):
            compiler.compile({"type": "array", "items": {"type": "string"}})

    def test_compiler_adds_missing_additional_properties(self):
        """Compiler auto-adds additionalProperties=false, doesn't raise."""
        compiler = DeepSeekStrictSchemaCompiler()
        schema = {
            "type": "object",
            "properties": {
                "x": {
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                }
            },
        }
        out = compiler.compile(schema)
        assert out["additionalProperties"] is False
        assert out["properties"]["x"]["additionalProperties"] is False

    def test_compiler_fixes_required_list(self):
        """Compiler rewrites required to match properties exactly."""
        compiler = DeepSeekStrictSchemaCompiler()
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a", "b"],  # 'b' not in properties — will be fixed
        }
        out = compiler.compile(schema)
        assert out["required"] == ["a"]


class TestBaseUrlForRequest:
    def test_strict_tools_uses_beta(self):
        assert "beta" in base_url_for_request(strict_tools=True)

    def test_beta_feature_uses_beta(self):
        assert "beta" in base_url_for_request(beta_feature=True)

    def test_normal_uses_standard(self):
        assert base_url_for_request() == "https://api.deepseek.com"
