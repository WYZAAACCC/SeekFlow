"""Tests for seekflow.cost — cost tracking."""
import pytest
from seekflow.cost import CostTracker, PRICING


class TestPricingTable:
    def test_v4_pro_pricing(self):
        assert PRICING["deepseek-v4-pro"]["input"] == 1.74
        assert PRICING["deepseek-v4-pro"]["output"] == 3.48
        assert PRICING["deepseek-v4-pro"]["unit"] == "CNY/1M"

    def test_v4_flash_pricing(self):
        assert PRICING["deepseek-v4-flash"]["input"] == 0.14
        assert PRICING["deepseek-v4-flash"]["output"] == 0.28


class TestCostTracker:
    def test_record_calculates_cost(self):
        tracker = CostTracker()
        tracker.record("deepseek-v4-pro", {"prompt_tokens": 1000000, "completion_tokens": 500000, "total_tokens": 1500000})
        expected = 1.74 + 3.48 * 0.5  # 1M input + 0.5M output
        assert tracker.total_cost == pytest.approx(expected, 0.01)

    def test_record_with_cached_tokens(self):
        tracker = CostTracker()
        tracker.record("deepseek-v4-pro", {
            "prompt_tokens": 1000000, "completion_tokens": 100000, "total_tokens": 1100000,
            "prompt_tokens_details": {"cached_tokens": 500000},
        })
        # 500K cached input + 500K uncached input + 100K output
        expected = 0.5 * 0.028 + 0.5 * 1.74 + 0.1 * 3.48
        assert tracker.total_cost == pytest.approx(expected, 0.01)

    def test_unknown_model_falls_back_to_pro(self):
        tracker = CostTracker()
        tracker.record("unknown-model", {"prompt_tokens": 1000000, "completion_tokens": 0, "total_tokens": 1000000})
        assert tracker.total_cost == pytest.approx(1.74, 0.01)

    def test_reset_clears_all(self):
        tracker = CostTracker()
        tracker.record("deepseek-v4-pro", {"prompt_tokens": 1000000, "completion_tokens": 0, "total_tokens": 1000000})
        tracker.reset()
        assert tracker.total_cost == 0.0
        assert len(tracker.history) == 0

    def test_multiple_records_accumulate(self):
        tracker = CostTracker()
        tracker.record("deepseek-v4-pro", {"prompt_tokens": 1000000, "completion_tokens": 0, "total_tokens": 1000000})
        tracker.record("deepseek-v4-pro", {"prompt_tokens": 1000000, "completion_tokens": 0, "total_tokens": 1000000})
        assert tracker.total_cost == pytest.approx(3.48, 0.01)
        assert len(tracker.history) == 2

    def test_by_model_stats(self):
        tracker = CostTracker()
        tracker.record("deepseek-v4-pro", {"prompt_tokens": 1000000, "completion_tokens": 0, "total_tokens": 1000000})
        tracker.record("deepseek-v4-flash", {"prompt_tokens": 1000000, "completion_tokens": 0, "total_tokens": 1000000})
        stats = tracker.by_model
        assert "deepseek-v4-pro" in stats
        assert "deepseek-v4-flash" in stats
        assert stats["deepseek-v4-pro"]["cost"] == pytest.approx(1.74, 0.01)
        assert stats["deepseek-v4-flash"]["cost"] == pytest.approx(0.14, 0.01)

    def test_record_with_none_usage_does_not_crash(self):
        """record() with None usage should not crash — defense against missing stream usage."""
        tracker = CostTracker()
        entry = tracker.record("deepseek-v4-pro", None)
        assert entry.cost == 0.0
        assert tracker.total_cost == 0.0

    def test_record_with_object_usage_extracts_attributes(self):
        """record() with an attr-based object (like OpenAI CompletionUsage) extracts tokens."""
        class FakeUsage:
            prompt_tokens = 500000
            completion_tokens = 200000
            total_tokens = 700000
            prompt_tokens_details = type('d', (), {'cached_tokens': 100000})()

        tracker = CostTracker()
        entry = tracker.record("deepseek-v4-pro", FakeUsage())
        # 400K fresh input + 100K cached input + 200K output
        expected = 0.4 * 1.74 + 0.1 * 0.028 + 0.2 * 3.48
        assert tracker.total_cost == pytest.approx(expected, 0.01)
