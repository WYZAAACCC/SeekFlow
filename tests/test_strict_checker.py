"""Tests for strict schema compatibility checker."""
from deepseek_toolkit.tools.strict import check_strict_compatibility


class TestStrictChecker:
    def test_valid_schema_passes(self):
        schema = [
            {
                "type": "function",
                "function": {
                    "name": "add",
                    "description": "Add two numbers",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "a": {"type": "integer"},
                            "b": {"type": "integer"},
                        },
                        "required": ["a", "b"],
                    },
                },
            }
        ]
        result = check_strict_compatibility(schema)
        assert result.ok

    def test_missing_parameters(self):
        schema = [
            {
                "type": "function",
                "function": {
                    "name": "add",
                    "description": "Add",
                },
            }
        ]
        result = check_strict_compatibility(schema)
        assert not result.ok
        assert any(i.level == "error" for i in result.issues)

    def test_parameters_not_object(self):
        schema = [
            {
                "type": "function",
                "function": {
                    "name": "add",
                    "description": "Add",
                    "parameters": {"type": "array"},
                },
            }
        ]
        result = check_strict_compatibility(schema)
        assert not result.ok
        assert any(i.level == "error" for i in result.issues)

    def test_empty_description_warning(self):
        schema = [
            {
                "type": "function",
                "function": {
                    "name": "add",
                    "description": "",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        result = check_strict_compatibility(schema)
        assert any(i.level == "warning" for i in result.issues)

    def test_anyof_generates_warning(self):
        schema = [
            {
                "type": "function",
                "function": {
                    "name": "add",
                    "description": "Add",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "value": {"anyOf": [{"type": "integer"}, {"type": "string"}]}
                        },
                    },
                },
            }
        ]
        result = check_strict_compatibility(schema)
        assert any("anyof" in i.message.lower() for i in result.issues)

    def test_empty_enum_error(self):
        schema = [
            {
                "type": "function",
                "function": {
                    "name": "set_mode",
                    "description": "Set mode",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "mode": {"type": "string", "enum": []}
                        },
                    },
                },
            }
        ]
        result = check_strict_compatibility(schema)
        assert any(i.level == "error" for i in result.issues)

    def test_valid_with_multiple_tools(self):
        schema = [
            {
                "type": "function",
                "function": {
                    "name": "add",
                    "description": "Add two numbers",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "a": {"type": "integer"},
                            "b": {"type": "integer"},
                        },
                        "required": ["a", "b"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "echo",
                    "description": "Echo back",
                    "parameters": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                },
            },
        ]
        result = check_strict_compatibility(schema)
        assert result.ok

    def test_invalid_function_name(self):
        schema = [
            {
                "type": "function",
                "function": {
                    "name": "",
                    "description": "Bad name",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        result = check_strict_compatibility(schema)
        assert not result.ok

    def test_issues_have_path_and_message(self):
        schema = [
            {
                "type": "function",
                "function": {
                    "name": "add",
                    "description": "",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        result = check_strict_compatibility(schema)
        for issue in result.issues:
            assert issue.path != ""
            assert issue.message != ""
