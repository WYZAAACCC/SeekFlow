# Fix 429 infinite retry loop with attempt/deadline enforcement

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** bug
**State:** ready-for-agent

## What to build

`RetryExecutor._execute_with_retry()` and `_execute_stream_with_retry()` currently handle 429 rate-limit responses by sleeping for `Retry-After` seconds and `continue`-ing the loop — without incrementing the `attempt` counter. This means continuous 429 responses cause an infinite loop, permanently occupying the thread and starving service throughput.

The fix makes 429 handling respect the same bounds as server-error retries:
- Increment `attempt` before sleeping
- Check `attempt > policy.max_retries` and raise if exceeded
- Apply `total_deadline` (computed once at entry as `time.monotonic() + max_total_s`) so the loop cannot run unbounded even if `max_retries` is set high
- Apply `min(parse_retry_after(e), policy.max_delay)` so a maliciously large `Retry-After` header cannot cause an arbitrarily long sleep

## Acceptance criteria

- [ ] `_execute_with_retry()` increments `attempt` inside the 429 branch and exits after `max_retries` consecutive 429s
- [ ] `_execute_stream_with_retry()` applies the same fix
- [ ] A `total_deadline` is enforced: if `time.monotonic() > deadline`, the loop raises immediately
- [ ] `Retry-After` values larger than `policy.max_delay` are capped to `max_delay`
- [ ] Regression test: simulate continuous 429 → loop exits with last exception, does not hang
- [ ] Regression test: simulate 429 with 3600s Retry-After → capped to max_delay
- [ ] Regression test: deadline exceeded mid-loop → raises promptly

## Blocked by

None — can start immediately.
