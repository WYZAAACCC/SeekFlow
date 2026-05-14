"""Test stream retry behavior — no retry after first yield."""
import pytest
from seekflow.errors import DeepSeekAPIError
from seekflow.retry import RetryPolicy, CircuitBreaker
from seekflow.retry_executor import RetryExecutor, StreamInterruptedError
from seekflow.types import _StreamChunk


def _chunk(content=""):
    return _StreamChunk(type="content", content=content)


def _server_error():
    err = DeepSeekAPIError("Server error")
    err.http_status = 503
    return err


class _FakeStreamClient:
    def __init__(self, chunks_list):
        self.chunks_list = list(chunks_list)
        self.calls: list[dict] = []

    def chat_stream(self, *, model, messages, tools=None, **kwargs):
        self.calls.append({"type": "chat_stream", "model": model, "kwargs": kwargs})
        if not self.chunks_list:
            raise RuntimeError("No more chunks")
        chunks = self.chunks_list.pop(0)
        for chunk in chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk


def test_stream_retries_before_first_yield():
    """If the stream fails before yielding any chunk, retry is allowed."""
    # First attempt fails immediately, second succeeds
    client = _FakeStreamClient([
        [_server_error()],  # first stream call — error before yielding
        [_chunk("hello"), _chunk(" world")],  # second stream call — succeeds
    ])
    policy = RetryPolicy(max_retries=3, max_elapsed_s=30.0, base_delay=0.01)
    cb = CircuitBreaker(threshold=3, cooldown=5.0)
    executor = RetryExecutor(client, policy=policy, circuit_breaker=cb)

    chunks = list(executor.chat_stream(model="test", messages=[{"role": "user", "content": "Hi"}]))
    assert len(client.calls) == 2


def test_stream_does_not_retry_after_first_yield():
    """If the stream yields chunks then fails, automatic retry is disabled."""
    client = _FakeStreamClient([
        [_chunk("hello"), _server_error()],  # yields one chunk then fails
        [_chunk("more")],  # would be second call but should never reach
    ])
    policy = RetryPolicy(max_retries=3, max_elapsed_s=30.0, base_delay=0.01)
    cb = CircuitBreaker(threshold=3, cooldown=5.0)
    executor = RetryExecutor(client, policy=policy, circuit_breaker=cb)

    with pytest.raises(StreamInterruptedError):
        list(executor.chat_stream(model="test", messages=[{"role": "user", "content": "Hi"}]))
