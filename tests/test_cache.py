"""Tests for deepseek_toolkit.cache — prompt cache observation."""
from unittest.mock import MagicMock, patch
import pytest


class TestCacheSentinel:
    def test_first_request_establishes_baseline(self):
        from deepseek_toolkit.cache import CacheSentinel
        sentinel = CacheSentinel()
        advice = sentinel.check([{"role": "system", "content": "you are helpful"},
                                 {"role": "user", "content": "hi"}])
        assert advice.status == "first_request"

    def test_same_prefix_returns_stable(self):
        from deepseek_toolkit.cache import CacheSentinel
        sentinel = CacheSentinel()
        msgs = [{"role": "system", "content": "you are helpful"},
                {"role": "user", "content": "hi"}]
        sentinel.check(msgs)
        advice = sentinel.check(msgs)
        assert advice.status == "stable"

    def test_changed_prefix_returns_changed(self):
        from deepseek_toolkit.cache import CacheSentinel
        sentinel = CacheSentinel()
        sentinel.check([{"role": "system", "content": "v1"},
                        {"role": "user", "content": "hi"}])
        advice = sentinel.check([{"role": "system", "content": "v2"},
                                 {"role": "user", "content": "hi"}])
        assert advice.status == "changed"


class TestCachedTokensExtraction:
    def test_extract_cached_tokens_from_usage(self):
        from deepseek_toolkit.cache import extract_cached_tokens
        usage = {"prompt_tokens": 50000, "completion_tokens": 1000,
                 "total_tokens": 51000,
                 "prompt_tokens_details": {"cached_tokens": 48000}}
        assert extract_cached_tokens(usage) == 48000

    def test_extract_cached_tokens_none_when_missing(self):
        from deepseek_toolkit.cache import extract_cached_tokens
        usage = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
        assert extract_cached_tokens(usage) == 0
