"""Tests for RunState and StepKind — explicit state machine types."""
from __future__ import annotations

import pytest


class TestStepKind:
    """StepKind enum — the phases of a tool-calling loop."""

    def test_all_phases_defined(self):
        from seekflow.state import StepKind

        phases = {p.value for p in StepKind}
        assert "prepare" in phases
        assert "model_call" in phases
        assert "parse_response" in phases
        assert "validate_tool_calls" in phases
        assert "policy_gate" in phases
        assert "execute_tools" in phases
        assert "append_results" in phases
        assert "finalize" in phases


class TestRunState:
    """RunState — typed, serializable snapshot of the runtime loop."""

    def test_default_initialization(self):
        from seekflow.state import RunState, StepKind

        state = RunState(
            run_id="test-1",
            model="deepseek-chat",
        )
        assert state.run_id == "test-1"
        assert state.step == 0
        assert state.current_phase == StepKind.PREPARE
        assert state.messages == []
        assert state.tool_results == []
        assert state.errors == []
        assert state.finish_reason is None

    def test_json_roundtrip(self):
        from seekflow.state import RunState, StepKind

        state = RunState(
            run_id="r1",
            step=3,
            current_phase=StepKind.EXECUTE_TOOLS,
            model="deepseek-v4-pro",
            trace_id="trace-abc",
        )
        data = state.model_dump(mode="json")
        restored = RunState.model_validate(data)
        assert restored.run_id == "r1"
        assert restored.step == 3
        assert restored.current_phase == StepKind.EXECUTE_TOOLS

    def test_record_error_appends(self):
        from seekflow.state import RunState

        state = RunState(run_id="r1", model="test")
        state.record_error("model_call", "Connection timeout")
        assert len(state.errors) == 1
        assert state.errors[0]["phase"] == "model_call"
        assert state.errors[0]["message"] == "Connection timeout"
