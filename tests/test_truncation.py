"""Tests for JSON-aware truncation (P3-1)."""
import json

from seekflow.truncation import (
    TruncationStrategy,
    truncate_result,
)


class TestSimpleTruncation:
    """SIMPLE strategy — current char-slicing behavior."""

    def test_string_under_limit_unchanged(self):
        result = truncate_result("hello", 100, TruncationStrategy.SIMPLE)
        assert result == "hello"

    def test_string_over_limit_truncated(self):
        result = truncate_result("hello world this is a long text that exceeds the character limit", 60, TruncationStrategy.SIMPLE)
        assert len(result) <= 60
        assert "truncated" in result.lower()

    def test_non_string_unchanged(self):
        result = truncate_result(42, 10, TruncationStrategy.SIMPLE)
        assert result == 42


class TestJsonAwareTruncation:
    """JSON_AWARE strategy — structure-preserving truncation."""

    def test_valid_json_under_limit_unchanged(self):
        data = json.dumps({"city": "杭州", "temp": 25})
        result = truncate_result(data, 500, TruncationStrategy.JSON_AWARE)
        parsed = json.loads(result)
        assert parsed["city"] == "杭州"
        assert parsed["temp"] == 25

    def test_large_array_truncated_but_elements_preserved(self):
        items = [{"id": i, "name": f"item_{i}"} for i in range(100)]
        data = json.dumps({"results": items})
        result = truncate_result(data, 800, TruncationStrategy.JSON_AWARE)
        parsed = json.loads(result)
        assert len(parsed["results"]) < 100
        assert len(parsed["results"]) > 0
        assert parsed["results"][0]["id"] == 0
        assert "_truncation" in parsed

    def test_non_json_falls_back_to_simple(self):
        result = truncate_result("just plain text not json here and more text", 30, TruncationStrategy.JSON_AWARE)
        assert "truncated" in result.lower()
        assert len(result) <= 30

    def test_empty_object_unchanged(self):
        result = truncate_result("{}", 100, TruncationStrategy.JSON_AWARE)
        assert json.loads(result) == {}

    def test_pure_array_under_limit_unchanged(self):
        result = truncate_result("[1, 2, 3, 4, 5]", 100, TruncationStrategy.JSON_AWARE)
        parsed = json.loads(result)
        assert parsed == [1, 2, 3, 4, 5]

    def test_large_pure_array_wrapped_in_object(self):
        # Create an array that exceeds the limit
        items = [{"id": i, "name": f"item_{i}"} for i in range(100)]
        data = json.dumps(items)
        result = truncate_result(data, 500, TruncationStrategy.JSON_AWARE)
        parsed = json.loads(result)
        assert "results" in parsed
        assert len(parsed["results"]) < 100
        assert "_truncation" in parsed

    def test_truncation_metadata_accurate(self):
        items = [{"id": i, "value": "x" * 50} for i in range(50)]
        data = json.dumps({"data": items, "meta": {"version": 1}})
        result = truncate_result(data, 600, TruncationStrategy.JSON_AWARE)
        parsed = json.loads(result)
        meta = parsed.get("_truncation", {})
        assert meta.get("truncated") is True
        assert meta["original_chars"] == len(data)
        assert meta["kept_chars"] <= 600

    def test_output_does_not_exceed_limit(self):
        items = [{"id": i, "text": "x" * 100} for i in range(100)]
        data = json.dumps({"results": items})
        result = truncate_result(data, 500, TruncationStrategy.JSON_AWARE)
        assert len(result) <= 500

    def test_performance_under_5ms(self):
        import time

        items = [{"id": i, "name": f"item_{i}", "data": "x" * 100} for i in range(200)]
        data = json.dumps({"results": items})  # ~50KB

        start = time.perf_counter()
        for _ in range(20):
            truncate_result(data, 8000, TruncationStrategy.JSON_AWARE)
        elapsed = (time.perf_counter() - start) / 20 * 1000

        assert elapsed < 5.0
