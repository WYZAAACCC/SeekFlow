"""RetryExecutor wraps DeepSeekClient with retry and circuit breaker logic."""
from __future__ import annotations

import time
from collections.abc import Iterator

from openai import APIStatusError

from deepseek_toolkit.retry import (
    ALL_RETRY_CODES,
    RATE_LIMIT_HTTP_CODES,
    CircuitBreaker,
    CircuitBreakerOpenError,
    RetryPolicy,
    compute_delay,
)
from deepseek_toolkit.types import ChatResponse, StreamChunk


class RetryExecutor:
    """Wraps a DeepSeekClient-like object with retry and circuit breaker logic."""

    def __init__(
        self,
        client,
        *,
        policy: RetryPolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        on_retry: callable | None = None,
    ):
        self._client = client
        self._policy = policy or RetryPolicy.default()
        self._cb = circuit_breaker or CircuitBreaker(
            threshold=self._policy.circuit_breaker_threshold,
            cooldown=self._policy.cooldown,
        )
        self._on_retry = on_retry

    def chat(self, *, model, messages, tools=None, tool_choice=None, stream=False, **kwargs) -> ChatResponse:
        return self._execute_with_retry(
            lambda: self._client.chat(
                model=model, messages=messages, tools=tools,
                tool_choice=tool_choice, stream=stream, **kwargs
            )
        )

    def chat_stream(self, *, model, messages, tools=None, **kwargs) -> Iterator[StreamChunk]:
        return self._execute_stream_with_retry(
            lambda: self._client.chat_stream(
                model=model, messages=messages, tools=tools, **kwargs
            )
        )

    def _execute_with_retry(self, fn):
        old_state = self._cb.state
        self._cb.allow_request()  # raises CircuitBreakerOpenError if open
        self._notify_cb_change(old_state, self._cb.state, "allow_request")

        attempt = 0
        last_exception = None
        while attempt <= self._policy.max_retries:
            try:
                result = fn()
                old_state = self._cb.state
                self._cb.record_success()
                self._notify_cb_change(old_state, self._cb.state, "record_success")
                return result
            except APIStatusError as e:
                status = e.status_code
                if status in RATE_LIMIT_HTTP_CODES:
                    delay = self._parse_retry_after(e)
                    if e.response:
                        try:
                            h = dict(e.response.headers)
                            self._last_rate_limit = {
                                "remaining": int(h.get("x-ratelimit-remaining", -1)),
                                "reset": h.get("x-ratelimit-reset", ""),
                            }
                        except Exception:
                            pass
                    self._notify_retry("rate_limit", attempt, delay, status)
                    time.sleep(delay)
                    continue
                if status not in ALL_RETRY_CODES:
                    old_state = self._cb.state
                    self._cb.record_failure()
                    self._notify_cb_change(old_state, self._cb.state, "non_retryable")
                    raise
                last_exception = e
                if attempt < self._policy.max_retries:
                    delay = compute_delay(self._policy, attempt)
                    self._notify_retry("server_error", attempt, delay, status)
                    time.sleep(delay)
                attempt += 1

        old_state = self._cb.state
        self._cb.record_failure()
        self._notify_cb_change(old_state, self._cb.state, "max_retries_exhausted")
        raise last_exception

    def _execute_stream_with_retry(self, fn):
        old_state = self._cb.state
        self._cb.allow_request()
        self._notify_cb_change(old_state, self._cb.state, "allow_request")

        attempt = 0
        last_exception = None
        # Buffer chunks as we yield so we can skip duplicates on retry
        yielded_count = 0

        while attempt <= self._policy.max_retries:
            try:
                chunk_buffer: list = []
                for chunk in fn():
                    chunk_buffer.append(chunk)
                    if len(chunk_buffer) > yielded_count:
                        # Only yield chunks we haven't yielded before
                        for c in chunk_buffer[yielded_count:]:
                            yield c
                        yielded_count = len(chunk_buffer)
                old_state = self._cb.state
                self._cb.record_success()
                self._notify_cb_change(old_state, self._cb.state, "record_success")
                return
            except APIStatusError as e:
                status = e.status_code
                if status in RATE_LIMIT_HTTP_CODES:
                    delay = self._parse_retry_after(e)
                    if e.response:
                        try:
                            h = dict(e.response.headers)
                            self._last_rate_limit = {
                                "remaining": int(h.get("x-ratelimit-remaining", -1)),
                                "reset": h.get("x-ratelimit-reset", ""),
                            }
                        except Exception:
                            pass
                    self._notify_retry("rate_limit", attempt, delay, status)
                    time.sleep(delay)
                    continue
                if status not in ALL_RETRY_CODES:
                    old_state = self._cb.state
                    self._cb.record_failure()
                    self._notify_cb_change(old_state, self._cb.state, "non_retryable")
                    raise
                last_exception = e
                if attempt < self._policy.max_retries:
                    delay = compute_delay(self._policy, attempt)
                    self._notify_retry("server_error", attempt, delay, status)
                    time.sleep(delay)
                attempt += 1

        old_state = self._cb.state
        self._cb.record_failure()
        self._notify_cb_change(old_state, self._cb.state, "max_retries_exhausted")
        raise last_exception

    def _notify_retry(self, reason: str, attempt: int, delay: float, status_code: int) -> None:
        if self._on_retry:
            self._on_retry({
                "type": "retry_attempt",
                "reason": reason,
                "attempt": attempt,
                "delay_seconds": round(delay, 3),
                "status_code": status_code,
            })

    def _notify_cb_change(self, old, new, cause: str) -> None:
        if old != new and self._on_retry:
            self._on_retry({
                "type": "circuit_breaker_change",
                "old_state": old.value,
                "new_state": new.value,
                "cause": cause,
            })

    @staticmethod
    def _parse_retry_after(error: APIStatusError) -> float:
        """Parse Retry-After header from a 429 response, default to 1 second."""
        headers = getattr(error, "headers", None) or {}
        val = headers.get("Retry-After", headers.get("retry-after", "1"))
        try:
            return float(val)
        except (ValueError, TypeError):
            return 1.0
