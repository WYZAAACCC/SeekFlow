"""Test cost tracking and budget enforcement."""
import pytest
from seekflow.cost import CostTracker, CostEntry
from seekflow.budget import BudgetGuard, BudgetExceeded, CostBudget, CostEstimator, PreflightEstimate


def test_cost_tracker_records():
    tracker = CostTracker()
    entry = tracker.record("deepseek-v4-flash", {
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "total_tokens": 1500,
    })
    assert entry.model == "deepseek-v4-flash"
    assert entry.prompt_tokens == 1000
    assert tracker.total_cost > 0


def test_cost_tracker_by_model():
    tracker = CostTracker()
    tracker.record("deepseek-v4-flash", {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150})
    tracker.record("deepseek-v4-flash", {"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300})
    by_model = tracker.by_model
    assert "deepseek-v4-flash" in by_model
    assert by_model["deepseek-v4-flash"]["calls"] == 2


def test_budget_guard_blocks_over_budget():
    budget = CostBudget(max_prompt_tokens=100)
    guard = BudgetGuard(budget)
    with pytest.raises(BudgetExceeded):
        guard.check_tokens(prompt_tokens=200)


def test_budget_guard_does_not_block_under_budget():
    budget = CostBudget(max_prompt_tokens=1000)
    guard = BudgetGuard(budget)
    # Should not raise
    guard.check_tokens(prompt_tokens=500)
    guard.record_usage(prompt_tokens=500, completion_tokens=100)


def test_budget_tight():
    budget = CostBudget.tight()
    assert budget.max_cny <= 0.1
    assert budget.max_prompt_tokens <= 100_000


def test_budget_generous():
    budget = CostBudget.generous()
    assert budget.max_cny >= 0.5


def test_cost_estimator_produces_estimate():
    estimator = CostEstimator()
    estimate = estimator.estimate(
        messages=[{"role": "user", "content": "Hello, how are you?"}],
        model="deepseek-v4-flash",
    )
    assert estimate.estimated_prompt_tokens > 0
    assert estimate.lower_bound_cost < estimate.upper_bound_cost
