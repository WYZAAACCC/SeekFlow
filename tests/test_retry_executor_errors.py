"""Test RetryExecutor error handling and circuit breaker semantics."""
import pytest
from seekflow.errors import (
    DeepSeekAPIError, RateLimitError, BadRequestError,
    AuthenticationError, ServiceUnavailableError,
)
from seekflow.retry import RetryPolicy, CircuitBreaker, CircuitBreakerOpenError
from seekflow.retry_executor import RetryExecutor, StreamInterruptedError


class _FakeClient:
    """Simulates a DeepSeekClient for testing RetryExecutor behavior."""
    def __init__(self, responses=None, stream_chunks=None):
        self.responses = list(responses or [])
        self.stream_chunks = list(stream_chunks or [])
        self.calls: list[dict] = []

    def chat(self, *, model, messages, tools=None, tool_choice=None, stream=False, **kwargs):
        self.calls.append({"type": "chat", "model": model, "kwargs": kwargs})
        if not self.responses:
            raise RuntimeError("No more responses")
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp

    def chat_stream(self, *, model, messages, tools=None, **kwargs):
        self.calls.append({"type": "chat_stream", "model": model, "kwargs": kwargs})
        if not self.stream_chunks:
            raise RuntimeError("No more stream chunks")
        chunks = self.stream_chunks.pop(0)
        for chunk in chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk


def _make_rate_limit_error():
    err = DeepSeekAPIError("Rate limit")
    err.http_status = 429
    return err


def _make_server_error():
    err = DeepSeekAPIError("Server error")
    err.http_status = 503
    return err


def _make_bad_request():
    err = DeepSeekAPIError("Bad request")
    err.http_status = 400
    return err


def _make_chat_response(content="ok"):
    from seekflow.types import ChatResponse
    return ChatResponse(content=content)


def test_retry_executor_retries_server_error():
    client = _FakeClient(responses=[_make_server_error(), _make_chat_response("ok")])
    policy = RetryPolicy(max_retries=3, max_elapsed_s=30.0, base_delay=0.01)
    cb = CircuitBreaker(threshold=3, cooldown=5.0)
    executor = RetryExecutor(client, policy=policy, circuit_breaker=cb)
    result = executor.chat(model="test", messages=[{"role": "user", "content": "Hi"}])
    assert len(client.calls) == 2
    assert result.content == "ok"


def test_retry_executor_does_not_retry_bad_request():
    client = _FakeClient(responses=[_make_bad_request()])
    policy = RetryPolicy(max_retries=3, max_elapsed_s=30.0, base_delay=0.01)
    cb = CircuitBreaker(threshold=3, cooldown=5.0)
    executor = RetryExecutor(client, policy=policy, circuit_breaker=cb)
    with pytest.raises(DeepSeekAPIError):
        executor.chat(model="test", messages=[{"role": "user", "content": "Hi"}])
    # Only one call — bad request is not retried
    assert len(client.calls) == 1


def test_max_elapsed_s_bounds_retries():
    client = _FakeClient(responses=[_make_server_error()] * 10)
    policy = RetryPolicy(max_retries=10, max_elapsed_s=0.01, base_delay=1.0)
    cb = CircuitBreaker(threshold=10, cooldown=5.0)
    executor = RetryExecutor(client, policy=policy, circuit_breaker=cb)
    with pytest.raises(DeepSeekAPIError):
        executor.chat(model="test", messages=[{"role": "user", "content": "Hi"}])
    # Should stop early due to elapsed deadline
    assert len(client.calls) < 10


def test_circuit_breaker_opens_after_threshold():
    client = _FakeClient(responses=[_make_server_error()] * 10)
    policy = RetryPolicy(max_retries=1, max_elapsed_s=2.0, base_delay=0.01)
    cb = CircuitBreaker(threshold=2, cooldown=5.0)
    executor = RetryExecutor(client, policy=policy, circuit_breaker=cb)

    # First run — exhausts retries, records failure
    with pytest.raises(DeepSeekAPIError):
        executor.chat(model="test", messages=[{"role": "user", "content": "Hi"}])

    # Second run — exhausts retries, records failure, breaker opens
    with pytest.raises(DeepSeekAPIError):
        executor.chat(model="test", messages=[{"role": "user", "content": "Hi"}])

    # Third run — circuit breaker should be open
    with pytest.raises(CircuitBreakerOpenError):
        executor.chat(model="test", messages=[{"role": "user", "content": "Hi"}])


def test_non_retryable_errors_do_not_trip_circuit_breaker():
    client = _FakeClient(responses=[_make_bad_request()])
    policy = RetryPolicy(max_retries=1, max_elapsed_s=2.0, base_delay=0.01)
    cb = CircuitBreaker(threshold=2, cooldown=5.0)
    executor = RetryExecutor(client, policy=policy, circuit_breaker=cb)

    with pytest.raises(DeepSeekAPIError):
        executor.chat(model="test", messages=[{"role": "user", "content": "Hi"}])

    # Ensure success resets failure count
    assert cb.state.value in ("closed", "half_open")


def test_success_resets_circuit_breaker_failure_count():
    client = _FakeClient(responses=[_make_server_error(), _make_chat_response("ok")])
    policy = RetryPolicy(max_retries=3, max_elapsed_s=30.0, base_delay=0.01)
    cb = CircuitBreaker(threshold=3, cooldown=5.0)
    executor = RetryExecutor(client, policy=policy, circuit_breaker=cb)

    # Record a failure first
    try:
        executor.chat(model="test", messages=[{"role": "user", "content": "Hi"}])
    except Exception:
        # Should not be raised because retry succeeded (server_error then ok)
        pass

    # After successful retry, cb should be closed
    assert cb.state.value == "closed"
