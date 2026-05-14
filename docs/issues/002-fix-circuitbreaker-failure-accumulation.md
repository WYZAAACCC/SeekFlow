# Fix CircuitBreaker: reset failure_count on all success + exclude non-retryable errors

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** bug
**State:** ready-for-agent

## What to build

Two bugs in `CircuitBreaker`:

1. **`record_success()` only resets `failure_count` in `HALF_OPEN` state.** In `CLOSED` state, scattered intermittent failures accumulate forever without being cleared by intervening successes. This means `failure_count` can reach `threshold` from occasional blips, falsely opening the breaker even though the service is mostly healthy.

   Fix: `record_success()` resets `self.failure_count = 0` unconditionally, regardless of current state. The HALF_OPEN → CLOSED transition is preserved as additional behavior.

2. **Non-retryable HTTP errors (400/401/403) counted against the upstream circuit breaker.** Auth failures and bad-request errors are caller-side problems, not upstream service failures. Counting them toward the breaker threshold causes false-positive circuit opens from misconfigured API keys or invalid parameters.

   Fix: In `RetryExecutor._execute_with_retry()` (and stream variant), non-retryable status codes that are immediately re-raised should NOT call `self._cb.record_failure()`. Only server errors (500/502/503/504) exhausted through all retries, and rate limits that hit the attempt/deadline cap, should record failure on the breaker.

## Acceptance criteria

- [ ] `CircuitBreaker.record_success()` sets `failure_count = 0` in ALL states (CLOSED, HALF_OPEN, OPEN)
- [ ] `CircuitBreaker.record_success()` in HALF_OPEN still transitions to CLOSED
- [ ] Non-retryable HTTP codes (400/401/402/403/404) do NOT call `record_failure()` — the error is re-raised without affecting the breaker
- [ ] Server errors exhausted through all retry attempts DO call `record_failure()`
- [ ] Regression test: 4 failures + 1 success + 1 failure in CLOSED state does NOT open the breaker
- [ ] Regression test: 5 consecutive failures with NO successes still opens the breaker
- [ ] Regression test: 401 error raised immediately does not increment breaker failure_count

## Blocked by

None — can start immediately.
