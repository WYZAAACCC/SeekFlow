"""Hidden tests for cache_cost.py — AGENTS CANNOT SEE THESE.

Tests edge cases in cache prefix and cost estimation.
"""

import time

from mini_agent_runtime.cache_cost import Usage, build_cache_prefix, estimate_cost_cny


def test_cache_prefix_independent_of_time():
    """Prefix must NOT depend on wall-clock time."""
    a = build_cache_prefix("sys", '{"tools":[]}')
    time.sleep(0.1)
    b = build_cache_prefix("sys", '{"tools":[]}')
    assert a == b, "Cache prefix changed over time — likely timestamp leak"


def test_cost_all_cached_is_cheap():
    """When all input tokens are cached, cost should be minimal."""
    usage = Usage(prompt_tokens=5000, cached_tokens=5000, completion_tokens=1000)
    cost = estimate_cost_cny(usage, input_price=1.74, cached_input_price=0.028, output_price=3.48)
    expected = (5000 * 0.028 + 1000 * 3.48) / 1_000_000
    assert abs(cost - expected) < 1e-9


def test_cache_prefix_different_for_different_system_prompts():
    a = build_cache_prefix("prompt A", "{}")
    b = build_cache_prefix("prompt B", "{}")
    assert a != b


def test_cache_prefix_different_for_different_tool_schemas():
    a = build_cache_prefix("sys", '{"tool_a": 1}')
    b = build_cache_prefix("sys", '{"tool_b": 1}')
    assert a != b
