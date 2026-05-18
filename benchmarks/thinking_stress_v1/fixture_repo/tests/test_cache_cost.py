"""Tests for cache_cost.py — Cache prefix stability and cost accounting."""

from mini_agent_runtime.cache_cost import Usage, build_cache_prefix, estimate_cost_cny


def test_cache_prefix_is_stable_for_same_inputs():
    a = build_cache_prefix("sys", '{"tools": []}')
    b = build_cache_prefix("sys", '{"tools": []}')
    assert a == b


def test_cost_charges_cached_tokens_at_cached_rate():
    usage = Usage(prompt_tokens=1000, cached_tokens=800, completion_tokens=200)
    cost = estimate_cost_cny(
        usage,
        input_price=1.74,
        cached_input_price=0.028,
        output_price=3.48,
    )
    # 200 uncached input * 1.74 + 800 cached * 0.028 + 200 output * 3.48 → /1M
    expected = ((200 * 1.74) + (800 * 0.028) + (200 * 3.48)) / 1_000_000
    assert abs(cost - expected) < 1e-9


def test_cost_zero_tokens():
    usage = Usage(prompt_tokens=0, cached_tokens=0, completion_tokens=0)
    cost = estimate_cost_cny(usage, 1.0, 0.5, 2.0)
    assert cost == 0.0


def test_cache_prefix_differs_for_different_inputs():
    a = build_cache_prefix("sys_a", '{"tools": []}')
    b = build_cache_prefix("sys_b", '{"tools": []}')
    assert a != b
