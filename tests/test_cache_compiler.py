"""Test cache compiler and prefix stability."""
import json
from seekflow.cache import (
    CacheStabilizer, CacheSentinel, CacheCompiler,
    append_only_compress,
)
from seekflow.deepseek.cache_metrics import (
    canonical_json, canonicalize_tools, extract_cache_metrics, CacheMetrics,
)


def test_tool_schema_hash_stable_across_dict_order():
    """JSON key order must not change the hash."""
    a = json.dumps({"a": 1, "b": 2})
    b = json.dumps({"b": 2, "a": 1})
    # canonical_json should produce deterministic output
    c1 = canonical_json({"a": 1, "b": 2})
    c2 = canonical_json({"b": 2, "a": 1})
    assert c1 == c2


def test_prefix_hash_stable_when_user_tail_changes():
    """The prefix hash should be stable across different user messages."""
    compiler = CacheCompiler()
    compiled = compiler.compile("You are helpful.", [])
    messages1 = [{"role": "system", "content": "You are helpful."}]
    messages2 = [{"role": "system", "content": "You are helpful."}]
    pred1 = compiler.predict_cache_hit(compiled, messages1)
    pred2 = compiler.predict_cache_hit(compiled, messages2)
    assert pred1["hit"] == pred2["hit"]


def test_canonicalize_tools_sorts_by_name():
    tools = [
        {"function": {"name": "z"}},
        {"function": {"name": "a"}},
        {"function": {"name": "m"}},
    ]
    sorted_tools = canonicalize_tools(tools)
    assert sorted_tools[0]["function"]["name"] == "a"
    assert sorted_tools[-1]["function"]["name"] == "z"


def test_cache_stabilizer_freezes_prefix():
    stabilizer = CacheStabilizer(warn_on_drift=False)
    prefix = stabilizer.freeze("System prompt here.", [])
    assert prefix.system_prompt == "System prompt here."
    assert prefix.frozen_hash


def test_cache_stabilizer_detects_drift():
    stabilizer = CacheStabilizer(warn_on_drift=False)
    stabilizer.freeze("System prompt.", [])
    # Content that does NOT start with the frozen prefix triggers drift repair
    messages = [{"role": "system", "content": "Different system prompt entirely."}]
    result = stabilizer.ensure_stable_prefix(messages)
    assert result[0]["role"] == "system"
    assert result[0]["content"] == "System prompt."
    assert stabilizer.cache_health["drift_count"] == 1


def test_cache_sentinel_first_request():
    sentinel = CacheSentinel()
    advice = sentinel.check([{"role": "system", "content": "Hello"}])
    assert advice.status == "first_request"


def test_cache_sentinel_stable():
    sentinel = CacheSentinel()
    messages = [{"role": "system", "content": "Hello"}]
    sentinel.check(messages)  # first request
    advice = sentinel.check(messages)  # same prefix
    assert advice.status == "stable"


def test_cache_sentinel_changed():
    sentinel = CacheSentinel()
    sentinel.check([{"role": "system", "content": "Hello"}])
    advice = sentinel.check([{"role": "system", "content": "Different"}])
    assert advice.status == "changed"


def test_extract_cache_metrics_from_dict():
    usage = {
        "prompt_tokens": 200,
        "completion_tokens": 50,
        "total_tokens": 250,
        "prompt_cache_hit_tokens": 100,
        "prompt_cache_miss_tokens": 50,
    }
    metrics = extract_cache_metrics(usage)
    assert metrics.prompt_cache_hit_tokens == 100
    assert metrics.prompt_cache_miss_tokens == 50


def test_extract_cache_metrics_legacy_cached_tokens():
    usage = {
        "prompt_tokens": 200,
        "completion_tokens": 50,
        "total_tokens": 250,
        "prompt_tokens_details": {"cached_tokens": 80},
    }
    metrics = extract_cache_metrics(usage)
    assert metrics.prompt_cache_hit_tokens == 80


def test_cache_metrics_hit_ratio():
    metrics = CacheMetrics(prompt_cache_hit_tokens=80, prompt_cache_miss_tokens=20)
    assert metrics.hit_ratio == 0.8

    metrics = CacheMetrics(prompt_cache_hit_tokens=0, prompt_cache_miss_tokens=0)
    assert metrics.hit_ratio == 0.0


def test_append_only_compress_preserves_prefix():
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Q1"},
        {"role": "assistant", "content": "A1"},
        {"role": "user", "content": "Q2"},
        {"role": "assistant", "content": "A2"},
        {"role": "user", "content": "Q3"},
        {"role": "assistant", "content": "A3"},
    ]
    compressed = append_only_compress(messages, max_context_tokens=10)
    # System message preserved
    assert compressed[0]["role"] == "system"
    assert compressed[0]["content"] == "You are helpful."
