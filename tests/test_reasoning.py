"""Tests for ReasoningInspector (P2-1)."""
from seekflow.reasoning import (
    ConsistencyResult,
    check_consistency,
    extract_tool_names,
)


class TestExtractToolNames:
    """Extract tool names from reasoning text."""

    def test_extracts_english_tool_names_from_chinese_text(self):
        names = extract_tool_names(
            "我需要调用 get_weather 来查询天气，然后调用 get_time 获取时间",
            ["get_weather", "get_time", "search_knowledge"],
        )
        assert names == {"get_weather", "get_time"}

    def test_extracts_from_english_text(self):
        names = extract_tool_names(
            "I should call get_weather for the forecast",
            ["get_weather", "get_time"],
        )
        assert names == {"get_weather"}

    def test_no_match_returns_empty_set(self):
        names = extract_tool_names(
            "Let me think about this... The user wants to know the weather.",
            ["get_weather", "get_time"],
        )
        assert names == set()

    def test_empty_reasoning_returns_empty_set(self):
        assert extract_tool_names("", ["get_weather"]) == set()

    def test_substring_not_falsely_matched(self):
        """get_weather should not match get_weather_v2."""
        names = extract_tool_names(
            "I will use get_weather_v2 for this",
            ["get_weather", "get_weather_v2"],
        )
        assert names == {"get_weather_v2"}
        assert "get_weather" not in names

    def test_special_chars_in_tool_names_are_escaped(self):
        names = extract_tool_names(
            "Calling tool.name-test now",
            ["tool.name-test", "other_tool"],
        )
        assert names == {"tool.name-test"}


class TestCheckConsistency:
    """Check consistency between reasoning and actual tool calls."""

    def test_null_reasoning_returns_no_reasoning(self):
        result = check_consistency(None, ["get_weather"], ["get_weather"])
        assert result.status == "NO_REASONING"

    def test_empty_reasoning_returns_no_reasoning(self):
        result = check_consistency("", ["get_weather"], ["get_weather"])
        assert result.status == "NO_REASONING"

    def test_consistent_returns_consistent(self):
        result = check_consistency(
            "I should call get_weather",
            ["get_weather"],
            ["get_weather", "get_time"],
        )
        assert result.status == "CONSISTENT"

    def test_mismatch_returns_mismatch(self):
        result = check_consistency(
            "I should call get_weather for this",
            ["get_time"],  # actually called get_time
            ["get_weather", "get_time"],
        )
        assert result.status == "MISMATCH"
        assert "get_weather" in result.reasoning_mentions
        assert "get_time" in result.actual_calls

    def test_no_tool_mentions_but_actual_calls_is_consistent(self):
        """If reasoning doesn't mention tools, it's not a mismatch."""
        result = check_consistency(
            "Let me help the user with this request.",
            ["get_weather"],
            ["get_weather"],
        )
        # No tool names in reasoning → consistent (no false positive)
        assert result.status == "CONSISTENT"

    def test_performance_is_fast(self):
        """extract_tool_names should be fast (< 1ms for typical input)."""
        import time
        names = [f"tool_{i}" for i in range(100)]
        reasoning = " ".join(f"I should call {n}" for n in names[:20])

        start = time.perf_counter()
        for _ in range(100):
            extract_tool_names(reasoning, names)
        elapsed = (time.perf_counter() - start) / 100 * 1000  # ms per call

        assert elapsed < 1.0
