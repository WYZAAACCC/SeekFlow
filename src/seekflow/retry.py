"""Retry policy configuration and circuit breaker state machine."""
from __future__ import annotations

import dataclasses
import enum
import random
import threading
import time

from seekflow.errors import SeekFlowError

# Error code classification for DeepSeek API
RETRYABLE_HTTP_CODES = (503, 502, 504, 500)
RATE_LIMIT_HTTP_CODES = (429,)
NON_RETRYABLE_HTTP_CODES = (400, 401, 402, 403, 404)

ALL_RETRY_CODES = RETRYABLE_HTTP_CODES + RATE_LIMIT_HTTP_CODES + (408, 409)


def is_retryable(status_code: int) -> bool:
    """Check if an HTTP status code warrants a retry (including rate limits)."""
    return status_code in ALL_RETRY_CODES


def compute_delay(policy: RetryPolicy, attempt: int) -> float:
    """Compute backoff delay for a given attempt using exponential backoff + jitter.

    delay = min(base_delay * (backoff_factor ** attempt) + random(0, base_delay), max_delay)
    """
    base = policy.base_delay * (policy.backoff_factor ** attempt)
    jitter = random.uniform(0, policy.base_delay * policy.jitter * 10)
    return min(base + jitter, policy.max_delay)


@dataclasses.dataclass(frozen=True)
class RetryPolicy:
    """Configuration for retry and circuit breaker behavior."""

    max_retries: int = 4
    max_elapsed_s: float = 60.0
    base_delay: float = 1.0
    backoff_factor: float = 2.0
    max_delay: float = 60.0
    jitter: float = 0.1
    circuit_breaker_threshold: int = 5
    cooldown: float = 30.0

    @staticmethod
    def default() -> RetryPolicy:
        return RetryPolicy()

    @staticmethod
    def aggressive() -> RetryPolicy:
        return RetryPolicy(max_retries=8, base_delay=0.5)

    @staticmethod
    def gentle() -> RetryPolicy:
        return RetryPolicy(max_retries=2, base_delay=5.0, max_elapsed_s=30.0)

    def with_overrides(self, **kwargs) -> RetryPolicy:
        return dataclasses.replace(self, **kwargs)


class CircuitBreakerState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class RateLimitState:
    """Tracks DeepSeek rate limit status from response headers."""

    NEAR_LIMIT_THRESHOLD = 0.2

    def __init__(self):
        self.remaining: int | None = None
        self.reset_at: float | None = None

    def update_from_headers(self, headers: dict[str, str]) -> None:
        remaining = headers.get("X-RateLimit-Remaining")
        reset = headers.get("X-RateLimit-Reset")
        if remaining is not None:
            try:
                self.remaining = int(remaining)
            except (ValueError, TypeError):
                self.remaining = None
        if reset is not None:
            try:
                self.reset_at = float(reset)
            except (ValueError, TypeError):
                self.reset_at = None

    @property
    def is_limited(self) -> bool:
        return self.remaining is not None and self.remaining == 0

    @property
    def is_near_limit(self) -> bool:
        if self.remaining is None:
            return False
        # Consider near-limit if remaining is 0 or if we don't know the total
        # but remaining is low (< 20%)
        return self.remaining <= 5  # conservative: < 5 requests remaining


class CircuitBreakerOpenError(SeekFlowError):
    """Raised when a request is attempted while the circuit breaker is open."""

    def __init__(self, remaining_cooldown: float):
        self.remaining_cooldown = remaining_cooldown
        super().__init__(
            f"Circuit breaker is open. "
            f"Cooldown remaining: {remaining_cooldown:.1f}s"
        )


class CircuitBreaker:
    """Three-state circuit breaker: Closed -> Open -> HalfOpen -> Closed."""

    def __init__(self, threshold: int = 5, cooldown: float = 30.0):
        self._threshold = threshold
        self._cooldown = cooldown
        self._failure_count = 0
        self._state = CircuitBreakerState.CLOSED
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitBreakerState:
        with self._lock:
            return self._state

    def allow_request(self) -> bool:
        with self._lock:
            if self._state == CircuitBreakerState.CLOSED:
                return True
            if self._state == CircuitBreakerState.HALF_OPEN:
                return True
            # OPEN state
            elapsed = time.monotonic() - (self._opened_at or 0)
            if elapsed >= self._cooldown:
                self._state = CircuitBreakerState.HALF_OPEN
                return True
            remaining = self._cooldown - elapsed
            raise CircuitBreakerOpenError(remaining)

    def record_success(self) -> None:
        with self._lock:
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._state = CircuitBreakerState.CLOSED
            self._failure_count = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._state = CircuitBreakerState.OPEN
                self._opened_at = time.monotonic()
            elif self._failure_count >= self._threshold:
                self._state = CircuitBreakerState.OPEN
                self._opened_at = time.monotonic()
