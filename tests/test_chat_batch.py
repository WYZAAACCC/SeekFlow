"""Tests for P4-2: ToolRuntime.chat_batch() method."""
from unittest import mock

import pytest

from seekflow.batch_client import BatchClient, BatchTimeoutError
from seekflow.runtime import ToolRuntime
from seekflow.tools.decorator import tool
from seekflow.types import ChatResponse, ToolRuntimeResult


class FakeBatchClient:
    """Fake BatchClient for testing chat_batch without real API calls."""

    def __init__(self, results=None, error=None):
        self.results = results or []  # list of lists (one per request)
        self.error = error  # exception to raise from submit_batch
        self._submitted = None
        self._submit_count = 0
        self._poll_count = 0
        self._download_count = 0

    def submit_batch(self, requests: list[dict]) -> str:
        self._submit_count += 1
        self._submitted = requests
        if self.error:
            raise self.error
        return "batch-test-1"

    def poll_batch(self, batch_id: str, poll_interval: float = 30.0, max_wait: float = 3600.0):
        self._poll_count += 1
        fake_batch = mock.MagicMock()
        fake_batch.status = "completed"
        fake_batch.output_file_id = "out-1"
        return "completed", fake_batch

    def download_results(self, batch_id: str) -> list[dict]:
        self._download_count += 1
        return self.results


class TestChatBatchBasic:
    """Basic chat_batch functionality."""

    def test_chat_batch_returns_list_of_results(self):
        """3 simple requests (no tools) return 3 ToolRuntimeResult."""
        fake_bc = FakeBatchClient(results=[
            {"custom_id": "req-0", "status_code": 200,
             "response": {"choices": [{"message": {"content": "A"}}]}, "error": None},
            {"custom_id": "req-1", "status_code": 200,
             "response": {"choices": [{"message": {"content": "B"}}]}, "error": None},
            {"custom_id": "req-2", "status_code": 200,
             "response": {"choices": [{"message": {"content": "C"}}]}, "error": None},
        ])

        with mock.patch("seekflow.runtime.BatchClient", return_value=fake_bc):
            rt = ToolRuntime(tools=[])
            rt._client = mock.MagicMock()  # bypass _make_client
            results = rt.chat_batch(
                model="deepseek-chat",
                requests=[
                    {"messages": [{"role": "user", "content": "hi"}]},
                    {"messages": [{"role": "user", "content": "hello"}]},
                    {"messages": [{"role": "user", "content": "hey"}]},
                ],
            )

        assert len(results) == 3
        for r in results:
            assert isinstance(r, ToolRuntimeResult)
        assert results[0].final == "A"
        assert results[1].final == "B"
        assert results[2].final == "C"

    def test_chat_batch_passes_tools_to_jsonl(self):
        """Tools schema is included in the JSONL body."""
        fake_bc = FakeBatchClient(results=[
            {"custom_id": "req-0", "status_code": 200,
             "response": {"choices": [{"message": {"content": "ok"}}]}, "error": None},
        ])

        from seekflow.types import ToolPolicy

        @tool(trusted=True)
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b
        add_tool = add.with_policy(ToolPolicy(risk="read", capabilities={"read"}, parallel_safe=True))

        with mock.patch("seekflow.runtime.BatchClient", return_value=fake_bc):
            rt = ToolRuntime(tools=[add_tool])
            rt._client = mock.MagicMock()  # bypass _make_client
            rt.chat_batch(
                model="deepseek-chat",
                requests=[{"messages": [{"role": "user", "content": "1+1"}]}],
            )

        # Check that tools were passed in the JSONL body
        submitted = fake_bc._submitted
        assert len(submitted) == 1
        body = submitted[0]["body"]
        assert "tools" in body
        assert len(body["tools"]) == 1
        assert body["tools"][0]["function"]["name"] == "add"

    def test_chat_batch_results_sorted_by_request_order(self):
        """Results maintain request order even if batch returns out of order."""
        fake_bc = FakeBatchClient(results=[
            {"custom_id": "req-1", "status_code": 200,
             "response": {"choices": [{"message": {"content": "second"}}]}, "error": None},
            {"custom_id": "req-0", "status_code": 200,
             "response": {"choices": [{"message": {"content": "first"}}]}, "error": None},
        ])

        with mock.patch("seekflow.runtime.BatchClient", return_value=fake_bc):
            rt = ToolRuntime(tools=[])
            rt._client = mock.MagicMock()  # bypass _make_client
            results = rt.chat_batch(
                model="deepseek-chat",
                requests=[
                    {"messages": [{"role": "user", "content": "1st"}]},
                    {"messages": [{"role": "user", "content": "2nd"}]},
                ],
            )

        assert len(results) == 2
        assert results[0].final == "first"
        assert results[1].final == "second"


class TestChatBatchWithTools:
    """chat_batch with tool execution."""

    def test_batch_with_tool_call_executes_locally(self):
        """When a batch result contains a tool call, execute it locally."""
        fake_bc = FakeBatchClient(results=[
            {
                "custom_id": "req-0",
                "status_code": 200,
                "response": {
                    "choices": [{
                        "message": {
                            "content": None,
                            "tool_calls": [{
                                "id": "call-1",
                                "function": {"name": "add", "arguments": '{"a":1,"b":2}'}
                            }]
                        },
                        "finish_reason": "tool_calls"
                    }]
                },
                "error": None,
            },
        ])

        from seekflow.types import ToolPolicy

        @tool(trusted=True)
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b
        add_tool = add.with_policy(ToolPolicy(risk="read", capabilities={"read"}, parallel_safe=True, trusted=True))

        with mock.patch("seekflow.runtime.BatchClient", return_value=fake_bc):
            rt = ToolRuntime(tools=[add_tool])
            rt._client = mock.MagicMock()  # bypass _make_client
            results = rt.chat_batch(
                model="deepseek-chat",
                requests=[{"messages": [{"role": "user", "content": "1+2"}]}],
            )

        assert len(results) == 1
        r = results[0]
        assert len(r.tool_results) == 1
        assert r.tool_results[0].ok is True
        assert r.tool_results[0].result == 3

    def test_tool_call_error_recorded(self):
        """Tool execution error is recorded in the result."""
        fake_bc = FakeBatchClient(results=[
            {
                "custom_id": "req-0",
                "status_code": 200,
                "response": {
                    "choices": [{
                        "message": {
                            "content": None,
                            "tool_calls": [{
                                "id": "call-1",
                                "function": {"name": "risky", "arguments": '{}'}
                            }]
                        },
                        "finish_reason": "tool_calls"
                    }]
                },
                "error": None,
            },
        ])

        from seekflow.types import ToolPolicy

        @tool(trusted=True)
        def risky() -> str:
            raise ValueError("boom")
        risky_tool = risky.with_policy(ToolPolicy(risk="read", capabilities={"read"}, trusted=True, parallel_safe=True))

        with mock.patch("seekflow.runtime.BatchClient", return_value=fake_bc):
            rt = ToolRuntime(tools=[risky_tool])
            rt._client = mock.MagicMock()  # bypass _make_client
            results = rt.chat_batch(
                model="deepseek-chat",
                requests=[{"messages": [{"role": "user", "content": "go"}]}],
            )

        assert len(results) == 1
        r = results[0]
        assert len(r.tool_results) == 1
        assert r.tool_results[0].ok is False
        assert "boom" in str(r.tool_results[0].error)


class TestChatBatchErrors:
    """chat_batch error handling."""

    def test_failed_entry_marked_in_result(self):
        """A failed API entry produces a result with error."""
        fake_bc = FakeBatchClient(results=[
            {"custom_id": "req-0", "status_code": 200,
             "response": {"choices": [{"message": {"content": "ok"}}]}, "error": None},
            {"custom_id": "req-1", "status_code": 400,
             "response": None, "error": {"message": "bad request"}},
        ])

        with mock.patch("seekflow.runtime.BatchClient", return_value=fake_bc):
            rt = ToolRuntime(tools=[])
            rt._client = mock.MagicMock()  # bypass _make_client
            results = rt.chat_batch(
                model="deepseek-chat",
                requests=[
                    {"messages": [{"role": "user", "content": "hi"}]},
                    {"messages": [{"role": "user", "content": "bad"}]},
                ],
            )

        assert len(results) == 2
        assert results[0].final == "ok"
        assert "bad request" in results[1].final

    def test_batch_timeout_raises(self):
        """Timeout in batch polling raises BatchTimeoutError."""
        fake_bc = FakeBatchClient(error=BatchTimeoutError("timeout"))

        with mock.patch("seekflow.runtime.BatchClient", return_value=fake_bc):
            rt = ToolRuntime(tools=[])
            rt._client = mock.MagicMock()  # bypass _make_client
            with pytest.raises(BatchTimeoutError):
                rt.chat_batch(
                    model="deepseek-chat",
                    requests=[{"messages": [{"role": "user", "content": "hi"}]}],
                )

    def test_chat_batch_creates_deepseek_client_when_client_is_none(self):
        """When self._client is None, a DeepSeekClient is created and passed to BatchClient."""
        from seekflow.client import DeepSeekClient

        fake_bc = FakeBatchClient(results=[
            {"custom_id": "req-0", "status_code": 200,
             "response": {"choices": [{"message": {"content": "ok"}}]}, "error": None},
        ])

        captured_client = []

        def capture_batch_client(client, **kwargs):
            captured_client.append(client)
            return fake_bc

        with mock.patch("seekflow.runtime.BatchClient", side_effect=capture_batch_client):
            rt = ToolRuntime(tools=[], api_key="sk-test")
            # self._client is None by default — this is the real user path
            rt.chat_batch(
                model="deepseek-chat",
                requests=[{"messages": [{"role": "user", "content": "hi"}]}],
            )

        assert len(captured_client) == 1
        assert isinstance(captured_client[0], DeepSeekClient)
        assert hasattr(captured_client[0], "_client")  # has the OpenAI client
