"""Tests for P4-1: BatchClient with submit/poll/download."""
import json
import time
from unittest import mock

import pytest

from deepseek_toolkit.batch_client import BatchClient, BatchExpiredError, BatchTimeoutError
from deepseek_toolkit.client import DeepSeekClient


# ---------------------------------------------------------------------------
# Fake file/batch objects that mimic OpenAI SDK response types
# ---------------------------------------------------------------------------

class _FakeFile:
    def __init__(self, id: str, filename: str, bytes: int, purpose: str, status: str = "processed"):
        self.id = id
        self.filename = filename
        self.bytes = bytes
        self.purpose = purpose
        self.status = status


class _FakeBatch:
    def __init__(self, id: str, status: str, output_file_id: str | None = None,
                 error_file_id: str | None = None, request_counts: dict | None = None):
        self.id = id
        self.status = status
        self.output_file_id = output_file_id
        self.error_file_id = error_file_id
        self.request_counts = request_counts or {"total": 0, "completed": 0, "failed": 0}


def _make_fake_client(*, upload_side_effect=None, create_side_effect=None,
                      retrieve_side_effect=None, content_side_effect=None):
    """Create a DeepSeekClient with mocked files.batches endpoints."""
    client = mock.MagicMock(spec=DeepSeekClient)
    client.base_url = "https://api.deepseek.com"
    client.api_key = "sk-fake"

    files_mock = mock.MagicMock()
    batches_mock = mock.MagicMock()

    if upload_side_effect:
        files_mock.create.side_effect = upload_side_effect
    if create_side_effect:
        batches_mock.create.side_effect = create_side_effect
    if retrieve_side_effect:
        batches_mock.retrieve.side_effect = retrieve_side_effect
    if content_side_effect:
        files_mock.content.side_effect = content_side_effect

    client._client = mock.MagicMock()
    client._client.files = files_mock
    client._client.batches = batches_mock

    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBatchClientSubmit:
    """submit_batch tests."""

    def test_submit_returns_batch_id(self):
        fake_file = _FakeFile(id="file-123", filename="batch_input.jsonl", bytes=500, purpose="batch")
        fake_batch = _FakeBatch(id="batch-456", status="validating")

        client = _make_fake_client(
            upload_side_effect=[fake_file],
            create_side_effect=[fake_batch],
        )
        bc = BatchClient(client)

        requests = [
            {"custom_id": "req-0", "body": {"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]}},
        ]
        batch_id = bc.submit_batch(requests)
        assert batch_id == "batch-456"

    def test_submit_builds_jsonl_correctly(self):
        captured_file_content = None

        def capture_upload(**kwargs):
            nonlocal captured_file_content
            file_arg = kwargs.get("file")
            # OpenAI SDK sends file as a tuple: (filename, bytes/buffer, content_type)
            if isinstance(file_arg, tuple):
                _, buf, _ = file_arg
                if hasattr(buf, 'read'):
                    captured_file_content = buf.read()
                else:
                    captured_file_content = buf
            else:
                captured_file_content = file_arg
            return _FakeFile(id="file-1", filename="x.jsonl", bytes=100, purpose="batch")

        def capture_create(**kwargs):
            return _FakeBatch(id="batch-1", status="validating")

        client = _make_fake_client(
            upload_side_effect=[None],
            create_side_effect=[None],
        )
        client._client.files.create.side_effect = capture_upload
        client._client.batches.create.side_effect = capture_create

        bc = BatchClient(client)
        requests = [
            {"custom_id": "a", "body": {"model": "m", "messages": []}},
            {"custom_id": "b", "body": {"model": "m", "messages": []}},
        ]
        bc.submit_batch(requests)

        assert captured_file_content is not None
        content = captured_file_content
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        lines = content.strip().split("\n")
        assert len(lines) == 2
        parsed = [json.loads(line) for line in lines]
        assert parsed[0]["custom_id"] == "a"
        assert parsed[1]["custom_id"] == "b"
        assert parsed[0]["method"] == "POST"
        assert parsed[0]["url"] == "/v1/chat/completions"

    def test_submit_upload_failure_retries(self):
        call_count = 0

        def fail_then_succeed(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Upload failed")
            return _FakeFile(id="file-ok", filename="x.jsonl", bytes=100, purpose="batch")

        client = _make_fake_client(
            upload_side_effect=[Exception("fail1"), Exception("fail2"), _FakeFile(id="file-ok", filename="x.jsonl", bytes=100, purpose="batch")],
            create_side_effect=[_FakeBatch(id="batch-ok", status="validating")],
        )
        client._client.files.create.side_effect = fail_then_succeed

        bc = BatchClient(client)
        batch_id = bc.submit_batch([{"custom_id": "x", "body": {"model": "m", "messages": []}}])
        assert batch_id == "batch-ok"
        assert call_count == 3


class TestBatchClientPoll:
    """poll_batch tests."""

    def test_poll_returns_completed(self):
        client = _make_fake_client(
            retrieve_side_effect=[_FakeBatch(id="b1", status="completed", output_file_id="out-1")],
        )
        bc = BatchClient(client)
        status, batch_obj = bc.poll_batch("b1", poll_interval=0.01, max_wait=5.0)
        assert status == "completed"
        assert batch_obj.output_file_id == "out-1"

    def test_poll_waits_until_completed(self):
        # First call: validating, second call: completed
        client = _make_fake_client(
            retrieve_side_effect=[
                _FakeBatch(id="b1", status="running"),
                _FakeBatch(id="b1", status="running"),
                _FakeBatch(id="b1", status="completed", output_file_id="out-1"),
            ],
        )
        bc = BatchClient(client, poll_interval=0.01)
        status, batch = bc.poll_batch("b1", poll_interval=0.01, max_wait=5.0)
        assert status == "completed"

    def test_poll_failed_status(self):
        client = _make_fake_client(
            retrieve_side_effect=[_FakeBatch(id="b1", status="failed")],
        )
        bc = BatchClient(client)
        status, _ = bc.poll_batch("b1", poll_interval=0.01, max_wait=5.0)
        assert status == "failed"

    def test_poll_expired_raises(self):
        client = _make_fake_client(
            retrieve_side_effect=[_FakeBatch(id="b1", status="expired")],
        )
        bc = BatchClient(client)
        with pytest.raises(BatchExpiredError, match="b1"):
            bc.poll_batch("b1", poll_interval=0.01, max_wait=5.0)

    def test_poll_timeout_raises(self):
        # Always returns "running" — never completes
        client = _make_fake_client()

        def always_running(batch_id):
            return _FakeBatch(id="b1", status="running")

        client._client.batches.retrieve.side_effect = always_running

        bc = BatchClient(client)
        with pytest.raises(BatchTimeoutError, match="b1"):
            bc.poll_batch("b1", poll_interval=0.01, max_wait=0.05)


class TestBatchClientDownload:
    """download_results tests."""

    def test_download_returns_sorted_results(self):
        jsonl_content = (
            '{"custom_id": "req-1", "response": {"status_code": 200, "body": {"choices": [{"message": {"content": "b"}}]}}}\n'
            '{"custom_id": "req-0", "response": {"status_code": 200, "body": {"choices": [{"message": {"content": "a"}}]}}}\n'
        )

        client = _make_fake_client(
            retrieve_side_effect=[_FakeBatch(id="b1", status="completed", output_file_id="out-1")],
            content_side_effect=[jsonl_content],
        )
        bc = BatchClient(client)
        results = bc.download_results("b1")
        assert len(results) == 2
        # Results sorted by custom_id
        assert results[0]["custom_id"] == "req-0"
        assert results[1]["custom_id"] == "req-1"

    def test_download_with_failed_entries(self):
        jsonl_content = (
            '{"custom_id": "req-0", "response": {"status_code": 200, "body": {"choices": [{"message": {"content": "ok"}}]}}}\n'
            '{"custom_id": "req-1", "response": {"status_code": 400, "body": {"error": {"message": "bad request"}}}}\n'
        )

        client = _make_fake_client(
            retrieve_side_effect=[_FakeBatch(id="b1", status="completed", output_file_id="out-1")],
            content_side_effect=[jsonl_content],
        )
        bc = BatchClient(client)
        results = bc.download_results("b1")
        assert len(results) == 2
        assert results[0]["error"] is None
        assert results[1]["error"] is not None

    def test_download_empty_results(self):
        client = _make_fake_client(
            retrieve_side_effect=[_FakeBatch(id="b1", status="completed", output_file_id="out-1")],
            content_side_effect=[""],
        )
        bc = BatchClient(client)
        results = bc.download_results("b1")
        assert results == []


class TestBatchClientIntegration:
    """Full lifecycle tests."""

    def test_full_submit_poll_download_lifecycle(self):
        jsonl_response = (
            '{"custom_id": "req-0", "response": {"status_code": 200, "body": {"choices": [{"message": {"content": "hello"}}]}}}\n'
        )

        completed_batch = _FakeBatch(id="batch-1", status="completed", output_file_id="out-1")

        client = _make_fake_client(
            upload_side_effect=[_FakeFile(id="file-1", filename="b.jsonl", bytes=100, purpose="batch")],
            create_side_effect=[_FakeBatch(id="batch-1", status="validating")],
            retrieve_side_effect=[completed_batch, completed_batch],  # poll + download each call retrieve
            content_side_effect=[jsonl_response],
        )
        bc = BatchClient(client)

        batch_id = bc.submit_batch([
            {"custom_id": "req-0", "body": {"model": "deepseek-chat", "messages": [{"role": "user", "content": "hi"}]}},
        ])
        assert batch_id == "batch-1"

        status, _ = bc.poll_batch(batch_id, poll_interval=0.01, max_wait=5.0)
        assert status == "completed"

        results = bc.download_results(batch_id)
        assert len(results) == 1
        assert results[0]["custom_id"] == "req-0"
