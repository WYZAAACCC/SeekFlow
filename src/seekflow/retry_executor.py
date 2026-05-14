"""RetryExecutor wraps DeepSeekClient with retry and circuit breaker logic."""
from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from openai import APIStatusError, APIConnectionError, APITimeoutError

from seekflow.errors import (
    DeepSeekAPIError,
    RateLimitError,
)
from seekflow.retry import (
    ALL_RETRY_CODES,
    RATE_LIMIT_HTTP_CODES,
    CircuitBreaker,
    CircuitBreakerOpenError,
    RetryPolicy,
    compute_delay,
)
from seekflow.types import ChatResponse, _StreamChunk, ToolChoice


class StreamInterruptedError(Exception):
    """Raised when a stream is interrupted after bytes were already yielded.
    Automatic retry is disabled in this case to avoid duplicate/misordered tokens.
    """
    pass


class RetryExecutor:
    """Wraps a DeepSeekClient-like object with retry and circuit breaker logic."""

    def __init__(
        self,
        client: Any,
        *,
        policy: RetryPolicy | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        on_retry: callable[..., Any] | None = None,
    ) -> None:
        self._client = client
        self._policy = policy or RetryPolicy.default()
        self._cb = circuit_breaker or CircuitBreaker(
            threshold=self._policy.circuit_breaker_threshold,
            cooldown=self._policy.cooldown,
        )
        self._on_retry = on_retry
        self._last_rate_limit: dict[str, Any] | None = None

    def chat(
        self, *, model: str, messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: ToolChoice | None = None,
        stream: bool = False, **kwargs: Any,
    ) -> ChatResponse:
        return self._execute_with_retry(
            lambda: self._client.chat(
                model=model, messages=messages, tools=tools,
                tool_choice=tool_choice, stream=stream, **kwargs
            )
        )

    def chat_stream(self, *, model, messages, tools=None, **kwargs) -> Iterator[_StreamChunk]:
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
        last_exception: Exception | None = None
        deadline = time.monotonic() + self._policy.max_elapsed_s

        while attempt <= self._policy.max_retries:
            if time.monotonic() >= deadline:
                break
            try:
                result = fn()
                # Success: reset circuit breaker failure count
                old_state = self._cb.state
                self._cb.record_success()
                self._notify_cb_change(old_state, self._cb.state, "record_success")
                return result
            except (DeepSeekAPIError, APIStatusError) as e:
                status = self._extract_status(e)
                if not self._is_retryable_status(status):
                    # Non-retryable: re-raise, do NOT trip circuit breaker
                    raise
                last_exception = e
                delay = self._compute_delay(status, e, attempt)
                attempt += 1
                self._notify_retry("server_error", attempt, delay, status)
                if attempt > self._policy.max_retries or time.monotonic() >= deadline:
                    break
                time.sleep(delay)
            except (APITimeoutError, APIConnectionError) as e:
                # Connection errors are retryable and trip circuit breaker
                last_exception = e
                delay = compute_delay(self._policy, attempt)
                attempt += 1
                self._notify_retry("connection_error", attempt, delay, 0)
                if attempt > self._policy.max_retries or time.monotonic() >= deadline:
                    break
                time.sleep(delay)

        old_state = self._cb.state
        self._cb.record_failure()
        self._notify_cb_change(old_state, self._cb.state, "max_retries_exhausted")
        if last_exception is not None:
            raise last_exception
        raise RuntimeError("RetryExecutor exhausted attempts with no exception captured")

    def _execute_stream_with_retry(self, fn):
        old_state = self._cb.state
        self._cb.allow_request()
        self._notify_cb_change(old_state, self._cb.state, "allow_request")

        attempt = 0
        last_exception: Exception | None = None
        deadline = time.monotonic() + self._policy.max_elapsed_s

        while attempt <= self._policy.max_retries:
            if time.monotonic() >= deadline:
                break

            has_yielded = False
            try:
                for chunk in fn():
                    has_yielded = True
                    yield chunk
                # Stream completed successfully
                old_state = self._cb.state
                self._cb.record_success()
                self._notify_cb_change(old_state, self._cb.state, "record_success")
                return
            except (DeepSeekAPIError, APIStatusError) as e:
                if has_yielded:
                    raise StreamInterruptedError(
                        "Stream interrupted after bytes were yielded to the caller. "
                        "Automatic retry is disabled to prevent duplicate/misordered tokens."
                    ) from e
                status = self._extract_status(e)
                if not self._is_retryable_status(status):
                    raise
                last_exception = e
                delay = self._compute_delay(status, e, attempt)
                attempt += 1
                self._notify_retry("server_error", attempt, delay, status)
                if attempt > self._policy.max_retries or time.monotonic() >= deadline:
                    break
                time.sleep(delay)
            except (APITimeoutError, APIConnectionError) as e:
                if has_yielded:
                    raise StreamInterruptedError(
                        "Stream interrupted after bytes were yielded to the caller. "
                        "Automatic retry is disabled to prevent duplicate/misordered tokens."
                    ) from e
                last_exception = e
                delay = compute_delay(self._policy, attempt)
                attempt += 1
                self._notify_retry("connection_error", attempt, delay, 0)
                if attempt > self._policy.max_retries or time.monotonic() >= deadline:
                    break
                time.sleep(delay)

        old_state = self._cb.state
        self._cb.record_failure()
        self._notify_cb_change(old_state, self._cb.state, "max_retries_exhausted")
        if last_exception is not None:
            raise last_exception
        raise RuntimeError("RetryExecutor stream exhausted attempts with no exception captured")

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_status(e: Exception) -> int:
        if isinstance(e, DeepSeekAPIError):
            return getattr(e, "http_status", 0)
        if isinstance(e, APIStatusError):
            return e.status_code
        return 0

    @staticmethod
    def _is_retryable_status(status: int) -> bool:
        """Return True if status should be retried AND counted against circuit breaker."""
        return status in ALL_RETRY_CODES or status in (408, 409)

    def _compute_delay(self, status: int, error: Any, attempt: int) -> float:
        if status in RATE_LIMIT_HTTP_CODES:
            return min(self._parse_retry_after(error), self._policy.max_delay)
        return compute_delay(self._policy, attempt)

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
    def _parse_retry_after(error: Any) -> float:
        """Parse Retry-After header from a rate-limit response, default to 1 second."""
        if isinstance(error, RateLimitError) and error.reset is not None:
            remaining = max(error.reset - time.time(), 0)
            if remaining > 0:
                return min(remaining, 60.0)
        headers = getattr(error, "headers", None) or {}
        val = headers.get("Retry-After", headers.get("retry-after", "1"))
        try:
            return float(val)
        except (ValueError, TypeError):
            return 1.0
