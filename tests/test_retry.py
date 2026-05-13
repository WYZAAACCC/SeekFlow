"""Tests for RetryPolicy and CircuitBreaker."""
import time

import pytest

from seekflow.retry import (
    RETRYABLE_HTTP_CODES,
    RATE_LIMIT_HTTP_CODES,
    NON_RETRYABLE_HTTP_CODES,
    RetryPolicy,
    CircuitBreaker,
    CircuitBreakerState,
    CircuitBreakerOpenError,
    compute_delay,
    is_retryable,
)


class TestRetryPolicyDefaults:
    """RetryPolicy preset defaults."""

    def test_default_preset_has_reasonable_values(self):
        p = RetryPolicy.default()
        assert p.max_retries == 4
        assert p.base_delay == 1.0
        assert p.backoff_factor == 2.0
        assert p.max_delay == 60.0
        assert p.circuit_breaker_threshold == 5
        assert p.cooldown == 30.0

    def test_aggressive_preset_retries_more_with_shorter_delay(self):
        p = RetryPolicy.aggressive()
        assert p.max_retries == 8
        assert p.base_delay == 0.5
        # Should still have reasonable defaults for other fields
        assert p.max_delay > 0

    def test_gentle_preset_retries_less_with_longer_delay(self):
        p = RetryPolicy.gentle()
        assert p.max_retries == 2
        assert p.base_delay == 5.0

    def test_with_overrides_creates_new_instance_with_merged_fields(self):
        p = RetryPolicy.default().with_overrides(max_retries=10, base_delay=2.0)
        assert p.max_retries == 10
        assert p.base_delay == 2.0
        # Unchanged fields stay at default
        assert p.backoff_factor == 2.0
        assert p.cooldown == 30.0

    def test_with_overrides_returns_new_object_original_unchanged(self):
        original = RetryPolicy.default()
        modified = original.with_overrides(max_retries=100)
        assert original.max_retries == 4
        assert modified.max_retries == 100
        assert original is not modified


class TestCircuitBreakerStateMachine:
    """CircuitBreaker three-state machine: Closed -> Open -> HalfOpen -> Closed."""

    def test_initial_state_is_closed_and_allows_requests(self):
        cb = CircuitBreaker(threshold=3, cooldown=60.0)
        assert cb.state == CircuitBreakerState.CLOSED
        assert cb.allow_request() is True

    def test_consecutive_failures_open_the_circuit(self):
        cb = CircuitBreaker(threshold=2, cooldown=60.0)
        cb.record_failure()
        assert cb.state == CircuitBreakerState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitBreakerState.OPEN

    def test_open_circuit_rejects_requests(self):
        cb = CircuitBreaker(threshold=1, cooldown=60.0)
        cb.record_failure()
        assert cb.state == CircuitBreakerState.OPEN
        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            cb.allow_request()
        assert "cooldown" in str(exc_info.value).lower()
        assert exc_info.value.remaining_cooldown > 0

    def test_open_circuit_transitions_to_half_open_after_cooldown(self):
        cb = CircuitBreaker(threshold=1, cooldown=0.05)
        cb.record_failure()
        assert cb.state == CircuitBreakerState.OPEN
        time.sleep(0.06)
        assert cb.allow_request() is True
        assert cb.state == CircuitBreakerState.HALF_OPEN

    def test_half_open_success_transitions_to_closed(self):
        cb = CircuitBreaker(threshold=1, cooldown=0.05)
        cb.record_failure()
        time.sleep(0.06)
        cb.allow_request()  # enters HalfOpen
        cb.record_success()
        assert cb.state == CircuitBreakerState.CLOSED

    def test_half_open_failure_returns_to_open(self):
        cb = CircuitBreaker(threshold=1, cooldown=0.05)
        cb.record_failure()
        time.sleep(0.06)
        cb.allow_request()  # enters HalfOpen
        cb.record_failure()
        assert cb.state == CircuitBreakerState.OPEN

    def test_success_resets_failure_count_in_closed_state(self):
        cb = CircuitBreaker(threshold=3, cooldown=60.0)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        # Success should reset the failure counter
        cb.record_failure()
        assert cb.state == CircuitBreakerState.CLOSED

    def test_circuit_breaker_is_thread_safe(self):
        import threading

        cb = CircuitBreaker(threshold=100, cooldown=60.0)
        errors = []

        def hammer():
            try:
                for _ in range(500):
                    if cb.allow_request():
                        cb.record_failure()
                    cb.record_success()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=hammer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestErrorCodeClassification:
    """RETRYABLE / RATE_LIMIT / NON_RETRYABLE HTTP code constants."""

    def test_retryable_codes_include_server_errors(self):
        assert 500 in RETRYABLE_HTTP_CODES
        assert 502 in RETRYABLE_HTTP_CODES
        assert 503 in RETRYABLE_HTTP_CODES
        assert 504 in RETRYABLE_HTTP_CODES

    def test_rate_limit_code_is_429(self):
        assert 429 in RATE_LIMIT_HTTP_CODES

    def test_non_retryable_codes_include_client_errors(self):
        assert 400 in NON_RETRYABLE_HTTP_CODES
        assert 401 in NON_RETRYABLE_HTTP_CODES
        assert 403 in NON_RETRYABLE_HTTP_CODES
        assert 404 in NON_RETRYABLE_HTTP_CODES

    def test_is_retryable_returns_true_for_503(self):
        assert is_retryable(503) is True

    def test_is_retryable_returns_true_for_429(self):
        assert is_retryable(429) is True

    def test_is_retryable_returns_false_for_400(self):
        assert is_retryable(400) is False

    def test_is_retryable_returns_false_for_200(self):
        assert is_retryable(200) is False


class TestBackoffComputation:
    """Exponential backoff with jitter."""

    def test_compute_delay_first_attempt_equals_base_delay(self):
        import random
        random.seed(0)
        p = RetryPolicy.default()
        delay = compute_delay(p, attempt=0)
        assert delay >= p.base_delay
        assert delay < p.base_delay * 2  # jitter capped at base_delay

    def test_compute_delay_increases_exponentially(self):
        p = RetryPolicy.default().with_overrides(jitter=0.0)
        d0 = compute_delay(p, attempt=0)
        d1 = compute_delay(p, attempt=1)
        d2 = compute_delay(p, attempt=2)
        assert d1 > d0
        assert d2 > d1

    def test_compute_delay_respects_max_delay(self):
        p = RetryPolicy.default().with_overrides(max_delay=5.0, jitter=0.0)
        delay = compute_delay(p, attempt=100)
        assert delay <= p.max_delay

    def test_compute_delay_without_jitter_matches_formula(self):
        p = RetryPolicy.default().with_overrides(jitter=0.0)
        expected = p.base_delay * (p.backoff_factor ** 2)
        assert compute_delay(p, attempt=2) == expected
