"""Tests for ToolRuntime retry integration (P0-3)."""
import pytest

from seekflow.retry import (
    CircuitBreaker,
    RetryPolicy,
)
from seekflow.tools.registry import ToolRegistry
from seekflow.types import ToolRuntimeResult


# --- Fake client for injecting failures ---

def _make_status_error(status_code: int) -> Exception:
    import httpx
    from openai import APIStatusError

    request = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")
    response = httpx.Response(status_code, request=request)
    return APIStatusError("error", response=response, body={})


class FakeFailingClient:
    """Returns failures then success."""

    def __init__(self, failures: list[Exception], final_content: str = "ok"):
        self._failures = failures
        self._final = final_content
        self._call = 0

    def chat(self, *, model, messages, tools=None, tool_choice=None, stream=False, **kwargs):
        if self._call < len(self._failures):
            err = self._failures[self._call]
            self._call += 1
            raise err
        self._call += 1
        from seekflow.types import ChatResponse
        return ChatResponse(content=self._final, finish_reason="stop")

    def chat_stream(self, *, model, messages, tools=None, **kwargs):
        if self._call < len(self._failures):
            err = self._failures[self._call]
            self._call += 1
            raise err
        self._call += 1
        from seekflow.types import StreamChunk
        yield StreamChunk(type="content", content=self._final)


class TestRuntimeRetry:
    """ToolRuntime retry integration — trace events and success path."""

    def test_retry_attempt_events_in_trace(self):
        """When a 503 triggers retry, the request eventually succeeds."""
        from seekflow.runtime import ToolRuntime
        from seekflow.retry_executor import RetryExecutor

        rt = ToolRuntime(
            tools=[],
            retry_policy=RetryPolicy.default().with_overrides(jitter=0.0),
        )
        fake = FakeFailingClient([_make_status_error(503)])
        rt._client = RetryExecutor(
            fake,
            policy=rt._retry_policy,
            circuit_breaker=rt._circuit_breaker,
        )

        result = rt.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])

        assert result.final == "ok"
        assert result.circuit_breaker_open is False
        assert fake._call == 2

    def test_circuit_breaker_open_returns_result_not_exception(self):
        """When circuit breaker is open, chat returns a result with error, not an exception."""
        from seekflow.runtime import ToolRuntime
        from seekflow.retry import CircuitBreakerState
        from seekflow.retry_executor import RetryExecutor

        rt = ToolRuntime(
            tools=[],
            retry_policy=RetryPolicy.default().with_overrides(max_retries=0, jitter=0.0),
        )
        # Wrap fake in RetryExecutor sharing the runtime's circuit breaker
        fake = FakeFailingClient([])
        rt._client = RetryExecutor(
            fake,
            policy=RetryPolicy.default().with_overrides(jitter=0.0),
            circuit_breaker=rt._circuit_breaker,
        )
        # Force circuit breaker open
        rt._circuit_breaker._state = CircuitBreakerState.OPEN
        import time
        rt._circuit_breaker._opened_at = time.monotonic()

        result = rt.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])

        assert result.circuit_breaker_open is True
        assert "circuit breaker" in result.final.lower()

    def test_circuit_breaker_state_property(self):
        """runtime.circuit_breaker_state returns current state as string."""
        from seekflow.runtime import ToolRuntime

        rt = ToolRuntime(tools=[], retry_policy=RetryPolicy.default())
        assert rt.circuit_breaker_state == "closed"

    def test_default_retry_policy_is_applied(self):
        """ToolRuntime uses RetryPolicy.default() when retry_policy not passed."""
        from seekflow.runtime import ToolRuntime

        rt = ToolRuntime(tools=[])
        assert rt._retry_policy is not None
        assert rt._retry_policy.max_retries == 4

    def test_no_retry_policy_works_like_before(self):
        """Without retry_policy, behavior is backward compatible."""
        from seekflow.runtime import ToolRuntime

        # Uses default retry — calls should still work
        fake = FakeFailingClient([])
        rt = ToolRuntime(
            tools=[],
            retry_policy=RetryPolicy.default().with_overrides(jitter=0.0),
        )
        rt._client = fake

        result = rt.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])
        assert result.final == "ok"


class TestCacheStats:
    """P1-3: cache stats on ToolRuntimeResult."""

    def test_result_includes_cache_stats(self):
        from seekflow.runtime import ToolRuntime

        def dummy(x: int) -> int:
            return x * 2

        rt = ToolRuntime(
            tools=[dummy],
            retry_policy=RetryPolicy.default().with_overrides(jitter=0.0),
        )
        # Bypass API with a fake client that returns a tool call then final
        fake = FakeFailingClient([])
        fake._failures = []  # force success path
        # Override to return a tool call response first, then content
        call_count = [0]

        def fake_chat(**kwargs):
            from seekflow.types import ChatResponse, ToolCall
            if call_count[0] == 0:
                call_count[0] += 1
                return ChatResponse(
                    content=None,
                    tool_calls=[ToolCall(id="c1", name="dummy", arguments={"x": 5})],
                    finish_reason="tool_calls",
                )
            return ChatResponse(content="done", finish_reason="stop")

        fake.chat = fake_chat
        rt._client = fake

        result = rt.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])
        assert result.cache_stats is not None
        assert "hits" in result.cache_stats
        assert "misses" in result.cache_stats
