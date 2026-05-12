"""Tests for deepseek_toolkit.retry — rate limit awareness."""
from unittest.mock import MagicMock, patch
import pytest


class TestRateLimitState:
    def test_rate_limit_state_defaults(self):
        from deepseek_toolkit.retry import RateLimitState
        state = RateLimitState()
        assert state.remaining is None
        assert state.reset_at is None
        assert state.is_limited is False

    def test_update_from_headers(self):
        from deepseek_toolkit.retry import RateLimitState
        state = RateLimitState()
        state.update_from_headers({
            "X-RateLimit-Remaining": "5",
            "X-RateLimit-Reset": "1700000000",
        })
        assert state.remaining == 5
        assert state.reset_at == 1700000000.0

    def test_is_near_limit_below_20_percent(self):
        from deepseek_toolkit.retry import RateLimitState
        state = RateLimitState()
        state.update_from_headers({"X-RateLimit-Remaining": "1", "X-RateLimit-Reset": "1700000000"})
        assert state.is_near_limit is True

    def test_is_not_near_limit_above_20_percent(self):
        from deepseek_toolkit.retry import RateLimitState
        state = RateLimitState()
        state.update_from_headers({"X-RateLimit-Remaining": "100", "X-RateLimit-Reset": "1700000000"})
        assert state.is_near_limit is False

    def test_is_limited_when_remaining_is_zero(self):
        from deepseek_toolkit.retry import RateLimitState
        state = RateLimitState()
        state.update_from_headers({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"})
        assert state.is_limited is True
