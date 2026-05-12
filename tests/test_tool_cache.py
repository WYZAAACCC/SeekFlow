"""Tests for ToolCallCache LRU+TTL (P1-1)."""
import time

from deepseek_toolkit.tool_cache import ToolCallCache, make_cache_key
from deepseek_toolkit.types import ToolExecutionResult


def _make_result(name: str = "add", args: dict | None = None) -> ToolExecutionResult:
    return ToolExecutionResult(
        tool_call_id="id-1",
        name=name,
        arguments=args or {"a": 1, "b": 2},
        ok=True,
        result=3,
    )


class TestCacheKey:
    """make_cache_key produces consistent keys for equivalent arguments."""

    def test_same_args_same_key(self):
        k1 = make_cache_key("add", {"a": 1, "b": 2})
        k2 = make_cache_key("add", {"a": 1, "b": 2})
        assert k1 == k2

    def test_different_tool_name_different_key(self):
        k1 = make_cache_key("add", {"a": 1})
        k2 = make_cache_key("sub", {"a": 1})
        assert k1 != k2

    def test_argument_order_does_not_matter(self):
        k1 = make_cache_key("add", {"a": 1, "b": 2})
        k2 = make_cache_key("add", {"b": 2, "a": 1})
        assert k1 == k2

    def test_different_args_different_key(self):
        k1 = make_cache_key("add", {"a": 1})
        k2 = make_cache_key("add", {"a": 2})
        assert k1 != k2


class TestCacheHit:
    """Basic cache get/put behavior."""

    def test_put_then_get_hits(self):
        cache = ToolCallCache(max_size=10)
        key = make_cache_key("add", {"a": 1, "b": 2})
        result = _make_result()
        cache.put(key, result)
        cached = cache.get(key)
        assert cached is not None
        assert cached.result == 3

    def test_miss_returns_none(self):
        cache = ToolCallCache(max_size=10)
        assert cache.get(make_cache_key("add", {"a": 1})) is None

    def test_clear_removes_all_entries(self):
        cache = ToolCallCache(max_size=10)
        key = make_cache_key("add", {"a": 1})
        cache.put(key, _make_result())
        cache.clear()
        assert cache.get(key) is None


class TestLRUEviction:
    """Least-recently-used entries are evicted when capacity is reached."""

    def test_oldest_unused_evicted_when_full(self):
        cache = ToolCallCache(max_size=3)
        cache.put(make_cache_key("a", {"v": 1}), _make_result("a", {"v": 1}))
        cache.put(make_cache_key("b", {"v": 2}), _make_result("b", {"v": 2}))
        cache.put(make_cache_key("c", {"v": 3}), _make_result("c", {"v": 3}))

        # Access 'a' so it becomes most recently used
        assert cache.get(make_cache_key("a", {"v": 1})) is not None

        # Now 'b' is the LRU item
        cache.put(make_cache_key("d", {"v": 4}), _make_result("d", {"v": 4}))

        # 'b' should be evicted
        assert cache.get(make_cache_key("b", {"v": 2})) is None
        assert cache.get(make_cache_key("a", {"v": 1})) is not None
        assert cache.get(make_cache_key("c", {"v": 3})) is not None
        assert cache.get(make_cache_key("d", {"v": 4})) is not None

    def test_capacity_one(self):
        cache = ToolCallCache(max_size=1)
        cache.put(make_cache_key("a", {"v": 1}), _make_result("a", {"v": 1}))
        cache.put(make_cache_key("b", {"v": 2}), _make_result("b", {"v": 2}))
        assert cache.get(make_cache_key("a", {"v": 1})) is None
        assert cache.get(make_cache_key("b", {"v": 2})) is not None


class TestTTL:
    """Time-to-live expiration."""

    def test_expired_entry_returns_none(self):
        cache = ToolCallCache(max_size=10, ttl=0.05)
        key = make_cache_key("add", {"a": 1})
        cache.put(key, _make_result())
        assert cache.get(key) is not None
        time.sleep(0.06)
        assert cache.get(key) is None

    def test_no_ttl_entry_never_expires(self):
        cache = ToolCallCache(max_size=10, ttl=None)
        key = make_cache_key("add", {"a": 1})
        cache.put(key, _make_result())
        assert cache.get(key) is not None
        time.sleep(0.01)
        assert cache.get(key) is not None


class TestHitRate:
    """Cache hit/miss tracking."""

    def test_hit_rate_calculation(self):
        cache = ToolCallCache(max_size=10)
        key = make_cache_key("add", {"a": 1})
        # miss
        cache.get(key)
        # put and hit
        cache.put(key, _make_result())
        cache.get(key)
        cache.get(key)
        # 2 hits, 1 miss = 2/3
        assert cache.hit_rate == 2 / 3  # 2 hits / 3 total


class TestThreadSafety:
    """Concurrent access does not corrupt internal state."""

    def test_concurrent_puts_and_gets(self):
        import threading

        cache = ToolCallCache(max_size=1000)
        errors = []

        def worker(start: int):
            try:
                for i in range(start, start + 200):
                    key = make_cache_key("tool", {"i": i})
                    cache.put(key, _make_result("tool", {"i": i}))
                    cache.get(key)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i * 200,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
