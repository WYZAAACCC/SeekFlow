"""Tests for StreamLedger — streaming deduplication and retry safety."""
from __future__ import annotations

from seekflow.stream_ledger import StreamLedger


class TestStreamLedger:
    def test_records_content_delta(self):
        ledger = StreamLedger()
        ledger.record_content("Hello ")
        ledger.record_content("World")
        assert ledger.emitted_content == "Hello World"
        assert ledger.emitted_count == 11

    def test_idempotent_tool_can_reuse(self):
        ledger = StreamLedger()
        ledger.record_tool_execution("call_1")
        assert ledger.can_execute_tool("call_1", idempotent=True) is True

    def test_non_idempotent_tool_blocked_on_retry(self):
        ledger = StreamLedger()
        ledger.record_tool_execution("call_1")
        assert ledger.can_execute_tool("call_1", idempotent=False) is False

    def test_new_tool_always_allowed(self):
        ledger = StreamLedger()
        assert ledger.can_execute_tool("call_1", idempotent=False) is True
        assert ledger.can_execute_tool("call_1", idempotent=True) is True

    def test_multiple_tools_tracked_independently(self):
        ledger = StreamLedger()
        ledger.record_tool_execution("call_1")
        ledger.record_tool_execution("call_2")
        assert ledger.can_execute_tool("call_1", idempotent=False) is False
        assert ledger.can_execute_tool("call_2", idempotent=False) is False
        assert ledger.can_execute_tool("call_3", idempotent=False) is True
