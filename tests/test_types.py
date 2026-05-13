"""Tests for seekflow.types — verify all Pydantic models behave correctly."""
from seekflow.types import (
    ToolDefinition,
    ToolCall,
    ToolExecutionResult,
    ChatResponse,
    ToolRuntimeResult,
)


class TestToolDefinition:
    def test_instantiate_with_required_fields(self):
        td = ToolDefinition(name="add", description="Add two numbers", parameters={"type": "object"})
        assert td.name == "add"
        assert td.description == "Add two numbers"
        assert td.source == "local"

    def test_default_values(self):
        td = ToolDefinition(name="add", description="Add", parameters={})
        assert td.func is None
        assert td.source == "local"
        assert td.metadata == {}

    def test_model_dump(self):
        td = ToolDefinition(name="add", description="Add two numbers", parameters={"type": "object"})
        d = td.model_dump()
        assert d["name"] == "add"
        assert d["source"] == "local"


class TestToolCall:
    def test_instantiate_minimal(self):
        tc = ToolCall(name="add", arguments={"a": 1, "b": 2})
        assert tc.name == "add"
        assert tc.arguments == {"a": 1, "b": 2}
        assert tc.id is None

    def test_arguments_always_dict(self):
        """Arguments normalized to dict at API boundary. String parsing
        happens in client.py before ToolCall construction."""
        tc = ToolCall(name="add", arguments={"a": 1})
        assert tc.arguments == {"a": 1}

    def test_arguments_defaults_to_empty_dict(self):
        tc = ToolCall(name="noop")
        assert tc.arguments == {}


class TestToolExecutionResult:
    def test_success_result(self):
        r = ToolExecutionResult(
            name="add",
            arguments={"a": 1, "b": 2},
            ok=True,
            result=3,
            elapsed_ms=150,
        )
        assert r.ok is True
        assert r.result == 3
        assert r.error is None

    def test_failure_result(self):
        r = ToolExecutionResult(
            name="add",
            arguments={"a": 1},
            ok=False,
            error="missing argument: b",
        )
        assert r.ok is False
        assert r.error == "missing argument: b"
        assert r.result is None

    def test_repair_tracking(self):
        r = ToolExecutionResult(
            name="add",
            arguments={"a": 1, "b": 2},
            ok=True,
            result=3,
            repaired=True,
            repair_notes=["single_quotes_to_double"],
        )
        assert r.repaired is True
        assert r.repair_notes == ["single_quotes_to_double"]


class TestChatResponse:
    def test_simple_text_response(self):
        cr = ChatResponse(content="Hello", finish_reason="stop")
        assert cr.content == "Hello"
        assert cr.tool_calls == []

    def test_with_tool_calls(self):
        tc = ToolCall(name="get_weather", arguments={"city": "Hangzhou"})
        cr = ChatResponse(
            content=None,
            tool_calls=[tc],
            finish_reason="tool_calls",
        )
        assert len(cr.tool_calls) == 1
        assert cr.tool_calls[0].name == "get_weather"

    def test_with_reasoning_content(self):
        cr = ChatResponse(
            content="answer",
            reasoning_content="Let me think...",
            finish_reason="stop",
            usage={"total_tokens": 100},
        )
        assert cr.reasoning_content == "Let me think..."
        assert cr.usage == {"total_tokens": 100}


class TestToolRuntimeResult:
    def test_minimal_result(self):
        rr = ToolRuntimeResult(final="result", messages=[{"role": "user", "content": "hi"}])
        assert rr.final == "result"
        assert rr.tool_results == []
        assert rr.trace is None
        assert rr.usage is None

    def test_with_tool_results(self):
        tr = ToolExecutionResult(name="add", arguments={"a": 1, "b": 2}, ok=True, result=3)
        rr = ToolRuntimeResult(
            final="result is 3",
            messages=[{"role": "user", "content": "1+2"}],
            tool_results=[tr],
            usage={"total_tokens": 50},
        )
        assert len(rr.tool_results) == 1
        assert rr.tool_results[0].name == "add"
        assert rr.usage == {"total_tokens": 50}
