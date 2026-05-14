"""Test circuit breaker semantics — what counts and what doesn't."""
import pytest
from seekflow.retry import CircuitBreaker, CircuitBreakerOpenError, CircuitBreakerState


def test_circuit_breaker_starts_closed():
    cb = CircuitBreaker(threshold=3, cooldown=5.0)
    assert cb.state == CircuitBreakerState.CLOSED
    assert cb.allow_request() is True


def test_circuit_breaker_opens_after_threshold():
    cb = CircuitBreaker(threshold=2, cooldown=5.0)
    cb.record_failure()
    cb.record_failure()
    with pytest.raises(CircuitBreakerOpenError):
        cb.allow_request()


def test_success_resets_failure_count():
    cb = CircuitBreaker(threshold=3, cooldown=5.0)
    cb.record_failure()
    cb.record_failure()
    # Success resets count
    old_state = cb.state
    cb.record_success()
    # After success, count is 0 and state is CLOSED
    assert cb.state == CircuitBreakerState.CLOSED
    # Should allow requests
    assert cb.allow_request() is True


def test_half_open_transitions_back_to_open_on_failure():
    import time
    # Create breaker with short cooldown
    cb = CircuitBreaker(threshold=1, cooldown=0.01)
    cb.record_failure()
    time.sleep(0.02)
    # Now should be half-open
    assert cb.allow_request() is True
    # Failure in half-open → back to open
    cb.record_failure()
    with pytest.raises(CircuitBreakerOpenError):
        cb.allow_request()


def test_half_open_transitions_to_closed_on_success():
    import time
    cb = CircuitBreaker(threshold=1, cooldown=0.01)
    cb.record_failure()
    time.sleep(0.02)
    cb.allow_request()  # half-open
    cb.record_success()
    assert cb.state == CircuitBreakerState.CLOSED
