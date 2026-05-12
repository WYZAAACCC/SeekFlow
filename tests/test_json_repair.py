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


class TestJsonRepairEdgeCases:
    """Edge cases that must be handled for production reliability."""

    def test_nested_double_quotes_inside_single_quotes(self):
        raw = """{'key': 'he said "hello"'}"""
        result = repair_json_arguments(raw)
        assert result.ok
        assert result.value == {"key": 'he said "hello"'}

    def test_single_quotes_inside_double_quoted_values(self):
        raw = """{"message": "it's fine"}"""
        result = repair_json_arguments(raw)
        assert result.ok
        assert result.value == {"message": "it's fine"}

    def test_multiple_consecutive_markdown_blocks(self):
        raw = '```json\n{"a": 1}\n```\nSome text\n```json\n{"b": 2}\n```'
        result = repair_json_arguments(raw)
        assert result.ok
        assert "strip_markdown_code_block" in result.applied_rules

    def test_markdown_with_language_identifier_only(self):
        raw = '```\n{"city": "Beijing"}\n```'
        result = repair_json_arguments(raw)
        assert result.ok
        assert result.value == {"city": "Beijing"}

    def test_empty_string_input(self):
        result = repair_json_arguments("")
        assert not result.ok
        assert result.error is not None

    def test_whitespace_only_input(self):
        result = repair_json_arguments("   \n\t  ")
        assert not result.ok
        assert result.error is not None

    def test_large_json_performance(self):
        """10KB+ JSON should be repaired in under 50ms."""
        import time
        items = ",".join(f'"{i}": "value_{i}"' for i in range(700))
        raw = '{' + items + '}'
        assert len(raw) > 10000, f"Expected >10KB, got {len(raw)} bytes"
        start = time.perf_counter()
        result = repair_json_arguments(raw)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert result.ok
        assert elapsed_ms < 50, f"Repair took {elapsed_ms:.0f}ms, expected <50ms"

    def test_function_call_syntax_with_nested_parens(self):
        """Python function-call syntax with nested parentheses in values."""
        raw = 'get_data(query="select * from (select id from users)", limit=10)'
        result = repair_json_arguments(raw)
        assert result.ok
        assert result.value == {"query": "select * from (select id from users)", "limit": 10}
        assert "function_call_to_json" in result.applied_rules

    def test_function_call_mixed_types(self):
        raw = 'search(query="AI trends", limit=5, detailed=True)'
        result = repair_json_arguments(raw)
        assert result.ok
        assert result.value == {"query": "AI trends", "limit": 5, "detailed": True}
        assert "function_call_to_json" in result.applied_rules
        # python_literals_to_json does NOT fire here because
        # _extract_function_call_kwargs handles True/False/None internally

    def test_trailing_comma_in_nested_object(self):
        raw = '{"user": {"name": "Alice", "age": 30,}, "active": true}'
        result = repair_json_arguments(raw)
        assert result.ok
        assert result.value == {"user": {"name": "Alice", "age": 30}, "active": True}

    def test_trailing_comma_in_array(self):
        raw = '{"tags": ["python", "ai",], "count": 3}'
        result = repair_json_arguments(raw)
        assert result.ok
        assert result.value == {"tags": ["python", "ai"], "count": 3}

    def test_missing_brace_in_nested_array(self):
        raw = '{"items": [{"a": 1}, {"b": 2'
        result = repair_json_arguments(raw)
        assert result.ok
        assert "close_missing_braces" in result.applied_rules
        # LIFO stack must produce }] not ]}
        assert result.repaired.endswith("}]}")

    def test_line_comments_preserved_in_strings(self):
        """// inside string values should NOT be stripped."""
        raw = '{"url": "http://example.com/path", "debug": false}'
        result = repair_json_arguments(raw)
        assert result.ok
        assert result.value["url"] == "http://example.com/path"

    def test_line_comments_outside_strings_removed(self):
        raw = '{\n  "a": 1, // this is a comment\n  "b": 2\n}'
        result = repair_json_arguments(raw)
        assert result.ok
        assert result.value == {"a": 1, "b": 2}
        assert "strip_line_comments" in result.applied_rules

    def test_python_none_to_null(self):
        raw = '{"value": None}'
        result = repair_json_arguments(raw)
        assert result.ok
        assert result.value == {"value": None}
        assert "python_literals_to_json" in result.applied_rules

    def test_repaired_flags_accurate(self):
        """Each rule application must be tracked in applied_rules."""
        raw = "{'name': 'test',}"
        result = repair_json_arguments(raw)
        assert result.ok
        assert "single_quotes_to_double" in result.applied_rules
        assert "remove_trailing_commas" in result.applied_rules
        assert len(result.applied_rules) == 2  # no phantom rules

    def test_original_preserved_even_after_repair(self):
        raw = "completely invalid {{{ nonsense"
        result = repair_json_arguments(raw)
        assert result.original == raw
        assert not result.ok


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
