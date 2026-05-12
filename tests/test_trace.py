"""Tests for Trace recording."""
import json
import tempfile
import os
from deepseek_toolkit.trace.recorder import TraceRecorder


class TestTraceRecorder:
    def test_record_event(self):
        tr = TraceRecorder()
        tr.record("tool_call_start", {"name": "add"})
        assert len(tr._record.events) == 1
        assert tr._record.events[0].type == "tool_call_start"
        assert tr._record.events[0].data == {"name": "add"}

    def test_record_has_timestamp(self):
        tr = TraceRecorder()
        tr.record("runtime_start")
        assert tr._record.events[0].timestamp > 0

    def test_finish_sets_ended_at(self):
        tr = TraceRecorder()
        tr.record("runtime_start")
        assert tr._record.ended_at is None
        tr.finish()
        assert tr._record.ended_at is not None

    def test_to_json(self):
        tr = TraceRecorder()
        tr.record("runtime_start")
        tr.finish()
        json_str = tr.to_json()
        data = json.loads(json_str)
        assert data["trace_id"] != ""
        assert len(data["events"]) == 1

    def test_save_to_file(self):
        tr = TraceRecorder()
        tr.record("runtime_start")
        tr.record("runtime_final")
        tr.finish()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as f:
            path = f.name
        try:
            tr.save(path)
            with open(path) as f:
                data = json.load(f)
            assert len(data["events"]) == 2
        finally:
            os.unlink(path)

    def test_disabled_does_not_record(self):
        tr = TraceRecorder(enabled=False)
        tr.record("runtime_start")
        assert len(tr._record.events) == 0

    def test_trace_id_unique(self):
        tr1 = TraceRecorder()
        tr2 = TraceRecorder()
        assert tr1._record.trace_id != tr2._record.trace_id
