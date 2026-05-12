"""Tests for RetryExecutor wrapping DeepSeekClient."""
import time

import pytest
from openai import APIStatusError

from deepseek_toolkit.client import DeepSeekClient
from deepseek_toolkit.retry import (
    CircuitBreakerOpenError,
    RetryPolicy,
)
from deepseek_toolkit.retry_executor import RetryExecutor


# --- Fake client helpers ---

def _make_status_error(status_code: int, headers: dict | None = None) -> APIStatusError:
    """Create a fake APIStatusError with a given status code."""
    import httpx

    request = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")
    response = httpx.Response(status_code, headers=headers or {}, request=request)
    return APIStatusError("error", response=response, body={})


class FakeDeepSeekClient:
    """A test double that returns configurable failures then a success."""

    def __init__(self, failures: list[Exception]):
        self._failures = failures
        self._call_count = 0
        self.chat_calls: list[dict] = []

    def chat(self, *, model, messages, tools=None, tool_choice=None, stream=False, **kwargs):
        self.chat_calls.append({"model": model, "messages": messages, "tools": tools})
        if self._call_count < len(self._failures):
            err = self._failures[self._call_count]
            self._call_count += 1
            raise err
        self._call_count += 1
        from deepseek_toolkit.types import ChatResponse
        return ChatResponse(content="success", finish_reason="stop")

    def chat_stream(self, *, model, messages, tools=None, **kwargs):
        self.chat_calls.append({"model": model, "messages": messages, "tools": tools})
        if self._call_count < len(self._failures):
            err = self._failures[self._call_count]
            self._call_count += 1
            raise err
        self._call_count += 1
        from deepseek_toolkit.types import StreamChunk
        yield StreamChunk(type="content", content="hello")


class TestRetryExecutorBasic:
    """RetryExecutor retries on server errors, fails fast on client errors."""

    def test_503_triggers_retry_then_succeeds(self):
        fake = FakeDeepSeekClient([
            _make_status_error(503),
            _make_status_error(503),
        ])
        policy = RetryPolicy.default().with_overrides(jitter=0.0)
        executor = RetryExecutor(fake, policy=policy)

        result = executor.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])

        assert result.content == "success"
        assert fake._call_count == 3  # 2 failures + 1 success

    def test_400_fails_immediately_no_retry(self):
        fake = FakeDeepSeekClient([_make_status_error(400)])
        policy = RetryPolicy.default().with_overrides(jitter=0.0)
        executor = RetryExecutor(fake, policy=policy)

        with pytest.raises(APIStatusError) as exc_info:
            executor.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])

        assert exc_info.value.status_code == 400
        assert fake._call_count == 1  # No retries

    def test_max_retries_exhausted_raises_last_error(self):
        fake = FakeDeepSeekClient([
            _make_status_error(503),
            _make_status_error(503),
            _make_status_error(503),
            _make_status_error(503),
            _make_status_error(503),
        ])
        policy = RetryPolicy.default().with_overrides(max_retries=3, jitter=0.0)
        executor = RetryExecutor(fake, policy=policy)

        with pytest.raises(APIStatusError) as exc_info:
            executor.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])

        assert exc_info.value.status_code == 503
        # 1 initial + 3 retries = 4 total attempts
        assert fake._call_count == 4


class TestRateLimitHandling:
    """429 responses wait for Retry-After and don't consume retry budget."""

    def test_429_waits_for_retry_after_header(self):
        fake = FakeDeepSeekClient([
            _make_status_error(429, headers={"Retry-After": "0.01"}),
        ])
        policy = RetryPolicy.default().with_overrides(max_retries=2, jitter=0.0)
        executor = RetryExecutor(fake, policy=policy)

        start = time.monotonic()
        result = executor.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])
        elapsed = time.monotonic() - start

        assert result.content == "success"
        assert elapsed >= 0.01
        # 429 retries don't count towards max_retries
        assert fake._call_count == 2


class TestCircuitBreakerIntegration:
    """RetryExecutor records failures/successes to CircuitBreaker."""

    def test_circuit_breaker_opens_after_threshold_failures(self):
        from deepseek_toolkit.retry import CircuitBreaker

        cb = CircuitBreaker(threshold=2, cooldown=60.0)
        # Each chat fails with 503, max_retries=0 so no retry, just one failure per call
        fake = FakeDeepSeekClient([
            _make_status_error(503),
            _make_status_error(503),
        ])
        policy = RetryPolicy.default().with_overrides(max_retries=0, jitter=0.0)
        executor = RetryExecutor(fake, policy=policy, circuit_breaker=cb)

        # First call: fails, recorded
        with pytest.raises(APIStatusError):
            executor.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])

        # Second call: fails, opens circuit
        with pytest.raises(APIStatusError):
            executor.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])

        # Third call: circuit is open
        with pytest.raises(CircuitBreakerOpenError):
            executor.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])

    def test_successful_call_after_cooldown_restores_closed(self):
        from deepseek_toolkit.retry import CircuitBreaker, CircuitBreakerState

        cb = CircuitBreaker(threshold=1, cooldown=0.05)
        fake = FakeDeepSeekClient([
            _make_status_error(503),
        ])
        policy = RetryPolicy.default().with_overrides(max_retries=0, jitter=0.0)
        executor = RetryExecutor(fake, policy=policy, circuit_breaker=cb)

        # Fail once to open circuit
        with pytest.raises(APIStatusError):
            executor.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])
        assert cb.state == CircuitBreakerState.OPEN

        # Wait for cooldown
        time.sleep(0.06)

        # Create a fresh fake that returns success
        fake2 = FakeDeepSeekClient([])
        executor2 = RetryExecutor(fake2, policy=policy, circuit_breaker=cb)
        result = executor2.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])
        assert result.content == "success"
        assert cb.state == CircuitBreakerState.CLOSED


class TestRetryExecutorStreaming:
    """RetryExecutor retries chat_stream on failures."""

    def test_stream_retries_on_503(self):
        fake = FakeDeepSeekClient([
            _make_status_error(503),
        ])
        policy = RetryPolicy.default().with_overrides(jitter=0.0)
        executor = RetryExecutor(fake, policy=policy)

        chunks = list(executor.chat_stream(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}]))
        assert len(chunks) == 1
        assert chunks[0].type == "content"
        assert fake._call_count == 2
