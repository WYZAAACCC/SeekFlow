"""Tests for JSON repair and argument coercion."""
from deepseek_toolkit.repair.json_repair import repair_json_arguments
from deepseek_toolkit.repair.coercion import coerce_arguments


class TestJsonRepair:
    def test_single_quotes_to_double(self):
        result = repair_json_arguments("{'city': '杭州'}")
        assert result.ok
        assert result.value == {"city": "杭州"}
        assert "single_quotes_to_double" in result.applied_rules

    def test_remove_trailing_commas(self):
        result = repair_json_arguments('{"city": "杭州",}')
        assert result.ok
        assert result.value == {"city": "杭州"}
        assert "remove_trailing_commas" in result.applied_rules

    def test_strip_markdown_code_block(self):
        raw = '```json\n{"city": "杭州"}\n```'
        result = repair_json_arguments(raw)
        assert result.ok
        assert result.value == {"city": "杭州"}
        assert "strip_markdown_code_block" in result.applied_rules

    def test_python_bool_to_json(self):
        result = repair_json_arguments('{"ok": True, "value": None, "flag": False}')
        assert result.ok
        assert result.value == {"ok": True, "value": None, "flag": False}
        assert "python_literals_to_json" in result.applied_rules

    def test_extract_json_from_text(self):
        raw = '这里是参数：{"city": "杭州"}，请处理。'
        result = repair_json_arguments(raw)
        assert result.ok
        assert result.value == {"city": "杭州"}

    def test_already_valid_json(self):
        result = repair_json_arguments('{"city": "杭州"}')
        assert result.ok
        assert result.value == {"city": "杭州"}
        assert result.applied_rules == []

    def test_multiple_rules_applied(self):
        raw = '```json\n{"city": "杭州",}\n```'
        result = repair_json_arguments(raw)
        assert result.ok
        assert result.value == {"city": "杭州"}
        assert "strip_markdown_code_block" in result.applied_rules
        assert "remove_trailing_commas" in result.applied_rules

    def test_unrepairable_returns_failure(self):
        result = repair_json_arguments("not json at all {{{")
        assert not result.ok
        assert result.value is None
        assert result.error is not None

    def test_result_stores_original(self):
        raw = "{'city': '杭州'}"
        result = repair_json_arguments(raw)
        assert result.original == raw

    def test_int_and_float_values(self):
        result = repair_json_arguments('{"count": 42, "price": 3.14}')
        assert result.ok
        assert result.value == {"count": 42, "price": 3.14}


class TestCoercion:
    def test_coerce_string_to_integer(self):
        args = {"a": "12", "b": "30"}
        schema = {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
        }
        new_args, changes = coerce_arguments(args, schema)
        assert new_args == {"a": 12, "b": 30}
        assert len(changes) == 2

    def test_coerce_string_to_number(self):
        args = {"x": "3.14"}
        schema = {"type": "object", "properties": {"x": {"type": "number"}}}
        new_args, changes = coerce_arguments(args, schema)
        assert new_args == {"x": 3.14}

    def test_coerce_string_to_boolean(self):
        args = {"flag": "true", "off": "false"}
        schema = {
            "type": "object",
            "properties": {
                "flag": {"type": "boolean"},
                "off": {"type": "boolean"},
            },
        }
        new_args, changes = coerce_arguments(args, schema)
        assert new_args == {"flag": True, "off": False}

    def test_no_coercion_when_types_match(self):
        args = {"a": 12, "b": 30}
        schema = {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
        }
        new_args, changes = coerce_arguments(args, schema)
        assert new_args == {"a": 12, "b": 30}
        assert changes == []

    def test_missing_key_in_schema(self):
        args = {"a": "12", "unknown": "value"}
        schema = {"type": "object", "properties": {"a": {"type": "integer"}}}
        new_args, changes = coerce_arguments(args, schema)
        assert new_args["a"] == 12
        assert new_args["unknown"] == "value"
