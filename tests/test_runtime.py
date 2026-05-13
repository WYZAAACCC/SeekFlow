"""Tests for ToolRuntime."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from seekflow.tools.decorator import tool
from seekflow.tools.strict import StrictCheckIssue, StrictCheckResult
from seekflow.types import ChatResponse, ToolCall, ToolRuntimeResult


class TestToolRuntime:
    """Tests for the minimal tool calling loop."""

    @pytest.fixture
    def add_tool(self):
        @tool
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b
        return add

    @pytest.fixture
    def mock_two_round_client(self, add_tool):
        """Mock DeepSeekClient that returns tool_calls then final answer."""
        with patch("seekflow.runtime.DeepSeekClient") as mock_client_class:
            mock_client = MagicMock()

            # Round 1: model asks to call add(1, 2)
            resp1 = ChatResponse(
                content=None,
                tool_calls=[ToolCall(
                    id="call_1",
                    name="add",
                    arguments={"a": 1, "b": 2},
                )],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

            # Round 2: model returns final answer
            resp2 = ChatResponse(
                content="The result is 3",
                finish_reason="stop",
                usage={"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
            )

            mock_client.chat.side_effect = [resp1, resp2]
            mock_client_class.return_value = mock_client
            yield mock_client

    def test_basic_tool_loop(self, mock_two_round_client, add_tool):
        """A full tool loop: model calls tool, executor runs it, model gets result."""
        from seekflow.runtime import ToolRuntime

        runtime = ToolRuntime(tools=[add_tool], api_key="sk-test")
        result = runtime.chat(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "What is 1+2?"}],
        )

        assert isinstance(result, ToolRuntimeResult)
        assert result.final == "The result is 3"
        assert len(result.tool_results) == 1
        assert result.tool_results[0].name == "add"
        assert result.tool_results[0].ok is True
        assert result.tool_results[0].result == 3

        # Verify messages include assistant tool_call and tool result
        assert len(result.messages) >= 4  # user, assistant, tool, assistant

    def test_chat_without_tools(self):
        """Empty tool list degenerates to plain chat."""
        from seekflow.runtime import ToolRuntime

        with patch("seekflow.runtime.DeepSeekClient") as mock_client_class:
            mock_client = MagicMock()
            resp = ChatResponse(
                content="Hello, how can I help?",
                finish_reason="stop",
                usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            )
            mock_client.chat.return_value = resp
            mock_client_class.return_value = mock_client

            runtime = ToolRuntime(api_key="sk-test")
            result = runtime.chat(
                model="deepseek-chat",
                messages=[{"role": "user", "content": "Hi"}],
            )

        assert result.final == "Hello, how can I help?"
        assert result.tool_results == []

    def test_max_steps_exhausted(self, add_tool):
        """When the model keeps calling tools, stop after max_steps."""
        from seekflow.runtime import ToolRuntime

        with patch("seekflow.runtime.DeepSeekClient") as mock_client_class:
            mock_client = MagicMock()

            # Always return tool_calls so the loop never ends naturally
            resp = ChatResponse(
                content=None,
                tool_calls=[ToolCall(
                    id="call_x",
                    name="add",
                    arguments={"a": 1, "b": 1},
                )],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            )
            mock_client.chat.return_value = resp
            mock_client_class.return_value = mock_client

            runtime = ToolRuntime(tools=[add_tool], api_key="sk-test", max_steps=2)
            result = runtime.chat(
                model="deepseek-chat",
                messages=[{"role": "user", "content": "Loop forever"}],
            )

        assert "max_steps" in result.final
        assert len(result.tool_results) == 2

    def test_strict_fallback(self, add_tool):
        """strict=True + incompatible schema + fallback=True → auto fallback."""
        from seekflow.runtime import ToolRuntime

        with patch("seekflow.runtime.check_strict_compatibility") as mock_check:
            mock_check.return_value = StrictCheckResult(
                ok=False,
                issues=[StrictCheckIssue(
                    level="error",
                    path="tools[0].function.name",
                    message="Invalid function name",
                )],
            )

            with patch("seekflow.runtime.DeepSeekClient") as mock_client_class:
                mock_client = MagicMock()
                resp = ChatResponse(
                    content="Done",
                    finish_reason="stop",
                    usage={"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
                )
                mock_client.chat.return_value = resp
                mock_client_class.return_value = mock_client

                runtime = ToolRuntime(
                    tools=[add_tool],
                    api_key="sk-test",
                    strict=True,
                    strict_fallback=True,
                    trace=True,
                )
                result = runtime.chat(
                    model="deepseek-chat",
                    messages=[{"role": "user", "content": "Hi"}],
                )

        assert result.final == "Done"
        # Verify trace contains strict_fallback event
        assert result.trace is not None
        trace_dict = result.trace.to_dict()
        event_types = [e["type"] for e in trace_dict["events"]]
        assert "strict_fallback" in event_types

    def test_strict_no_fallback_raises(self, add_tool):
        """strict=True + incompatible schema + fallback=False → raises StrictSchemaError."""
        from seekflow.runtime import ToolRuntime
        from seekflow.errors import StrictSchemaError

        with patch("seekflow.runtime.check_strict_compatibility") as mock_check:
            mock_check.return_value = StrictCheckResult(
                ok=False,
                issues=[StrictCheckIssue(
                    level="error",
                    path="tools[0].function.name",
                    message="Invalid function name",
                )],
            )

            runtime = ToolRuntime(
                tools=[add_tool],
                api_key="sk-test",
                strict=True,
                strict_fallback=False,
            )

            with pytest.raises(StrictSchemaError):
                runtime.chat(
                    model="deepseek-chat",
                    messages=[{"role": "user", "content": "Hi"}],
                )

    def test_trace_recording(self, mock_two_round_client, add_tool):
        """trace=True produces full execution trace that can be saved."""
        import json
        import tempfile
        from pathlib import Path

        from seekflow.runtime import ToolRuntime

        runtime = ToolRuntime(tools=[add_tool], api_key="sk-test", trace=True)
        result = runtime.chat(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "What is 1+2?"}],
        )

        assert result.trace is not None
        trace_dict = result.trace.to_dict()
        assert "trace_id" in trace_dict
        assert trace_dict["model"] == "deepseek-chat"

        # Check that trace has expected event types
        event_types = [e["type"] for e in trace_dict["events"]]
        assert "model_request" in event_types
        assert "model_response" in event_types
        assert "tool_call_start" in event_types
        assert "tool_call_result" in event_types

        # Save to file and verify
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "trace.json"
            result.trace.save(str(path))
            with open(path) as f:
                data = json.load(f)
            assert data["trace_id"] == trace_dict["trace_id"]

    def test_tool_call_error_recorded(self, add_tool):
        """When a tool call fails (tool not found), the error is recorded."""
        from seekflow.runtime import ToolRuntime

        with patch("seekflow.runtime.DeepSeekClient") as mock_client_class:
            mock_client = MagicMock()

            # Model calls a tool that's not registered
            resp = ChatResponse(
                content=None,
                tool_calls=[ToolCall(
                    id="call_1",
                    name="nonexistent",
                    arguments={"x": 1},
                )],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            )
            mock_client.chat.return_value = resp
            mock_client_class.return_value = mock_client

            runtime = ToolRuntime(tools=[add_tool], api_key="sk-test", max_steps=1)
            result = runtime.chat(
                model="deepseek-chat",
                messages=[{"role": "user", "content": "Do something"}],
            )

        assert len(result.tool_results) == 1
        assert result.tool_results[0].ok is False
        assert "Tool not found" in result.tool_results[0].error

    # ── ThinkModeGuard: reasoning_content preservation ──────────────

    def test_reasoning_content_preserved_non_streaming_no_tools(self):
        """Non-streaming: reasoning_content survives into assistant message (no tool calls)."""
        from seekflow.runtime import ToolRuntime

        with patch("seekflow.runtime.DeepSeekClient") as mock_client_class:
            mock_client = MagicMock()
            resp = ChatResponse(
                content="Final answer",
                reasoning_content="Let me think about this carefully.",
                finish_reason="stop",
                usage={"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            )
            mock_client.chat.return_value = resp
            mock_client_class.return_value = mock_client

            runtime = ToolRuntime(api_key="sk-test")
            result = runtime.chat(
                model="deepseek-chat",
                messages=[{"role": "user", "content": "What is 2+2?"}],
            )

        # The assistant message stored in messages MUST carry reasoning_content
        assistant_msgs = [m for m in result.messages if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1
        assert assistant_msgs[0].get("reasoning_content") == "Let me think about this carefully."

    def test_reasoning_content_preserved_non_streaming_with_tools(self):
        """Non-streaming: reasoning_content survives in assistant msg (tool calls path).

        This path already works — regression guard.
        """
        from seekflow.runtime import ToolRuntime

        with patch("seekflow.runtime.DeepSeekClient") as mock_client_class:
            mock_client = MagicMock()

            resp1 = ChatResponse(
                content=None,
                reasoning_content="I need to use the add tool.",
                tool_calls=[ToolCall(
                    id="call_1", name="add", arguments={"a": 1, "b": 2},
                )],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
            resp2 = ChatResponse(
                content="Result is 3",
                finish_reason="stop",
                usage={"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            )
            mock_client.chat.side_effect = [resp1, resp2]
            mock_client_class.return_value = mock_client

            runtime = ToolRuntime(api_key="sk-test")
            result = runtime.chat(
                model="deepseek-chat",
                messages=[{"role": "user", "content": "Add 1+2"}],
            )

        # First assistant message must carry reasoning_content
        assistant_msgs = [m for m in result.messages if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 2
        assert assistant_msgs[0].get("reasoning_content") == "I need to use the add tool."

    def test_reasoning_content_preserved_streaming_with_tools(self):
        """Streaming: reasoning_content is included in assistant msg for next turn."""
        from seekflow.runtime import ToolRuntime
        from seekflow.types import _StreamChunk

        @tool
        def greet(name: str) -> str:
            """Greet someone."""
            return f"Hello, {name}!"

        with patch("seekflow.runtime.DeepSeekClient") as mock_client_class:
            mock_client = MagicMock()

            stream_1 = iter([
                _StreamChunk(type="reasoning", content="I should greet"),
                _StreamChunk(type="reasoning", content=" the user."),
                _StreamChunk(type="tool_call_start", tool_call_id="c1", tool_name="greet"),
                _StreamChunk(type="tool_call_delta", tool_call_id="c1", arguments_delta='{"name":'),
                _StreamChunk(type="tool_call_delta", tool_call_id="c1", arguments_delta=' "World"}'),
                _StreamChunk(type="tool_call_end", tool_call_id="c1", tool_name="greet", content='{"name": "World"}'),
                _StreamChunk(type="usage", usage={"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}),
            ])
            stream_2 = iter([
                _StreamChunk(type="content", content="Done."),
                _StreamChunk(type="usage", usage={"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}),
            ])
            mock_client.chat_stream.side_effect = [stream_1, stream_2]
            mock_client_class.return_value = mock_client

            runtime = ToolRuntime(tools=[greet], api_key="sk-test")
            list(runtime.chat_stream(
                model="deepseek-chat",
                messages=[{"role": "user", "content": "Greet World"}],
            ))

        # The messages sent to the SECOND API call must include reasoning_content
        # in the assistant message built after the first turn's tool call.
        assert mock_client.chat_stream.call_count >= 2
        second_call_messages = mock_client.chat_stream.call_args_list[1][1].get("messages", [])
        assistant_msgs = [m for m in second_call_messages if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 1
        assert assistant_msgs[0].get("reasoning_content") == "I should greet the user."

    def test_streaming_done_event_includes_reasoning(self):
        """Streaming done event carries accumulated reasoning_content (no tool calls)."""
        from seekflow.runtime import ToolRuntime
        from seekflow.types import _StreamChunk

        with patch("seekflow.runtime.DeepSeekClient") as mock_client_class:
            mock_client = MagicMock()
            mock_client.chat_stream.return_value = iter([
                _StreamChunk(type="reasoning", content="Let me think..."),
                _StreamChunk(type="content", content="Answer."),
                _StreamChunk(type="usage", usage={"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}),
            ])
            mock_client_class.return_value = mock_client

            runtime = ToolRuntime(api_key="sk-test")
            events = list(runtime.chat_stream(
                model="deepseek-chat",
                messages=[{"role": "user", "content": "Hi"}],
            ))

        done_events = [e for e in events if e.type == "done"]
        assert len(done_events) == 1
        assert done_events[0].reasoning_content == "Let me think..."


class TestRuntimeSaverIntegration:
    """Agent-level: RuntimeSaver captures steps, tokens, and tool calls."""

    @pytest.fixture
    def add_tool(self):
        @tool
        def add(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b
        return add

    def test_non_streaming_agent_saves_runtime_data(self, add_tool, tmp_path):
        """Non-streaming agent records steps, tokens, tool calls via RuntimeSaver."""
        from unittest.mock import patch, MagicMock
        from seekflow.runtime import ToolRuntime

        # Import from the benchmarks package (same-dir relative)
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "_archive" / "benchmarks" / "agents_comparison"))
        from comprehensive_saver import RuntimeSaver, get_framework_features

        saver = RuntimeSaver("SeekFlow", "test_agent", "deepseek-chat")

        with patch("seekflow.runtime.DeepSeekClient") as mock_client_class:
            mock_client = MagicMock()

            resp1 = ChatResponse(
                content=None,
                reasoning_content="I'll use the add tool.",
                tool_calls=[ToolCall(
                    id="call_1", name="add", arguments={"a": 1, "b": 2},
                )],
                finish_reason="tool_calls",
                usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )
            resp2 = ChatResponse(
                content="Result is 3",
                finish_reason="stop",
                usage={"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28},
            )
            mock_client.chat.side_effect = [resp1, resp2]
            mock_client_class.return_value = mock_client

            runtime = ToolRuntime(tools=[add_tool], api_key="sk-test", trace=True)

            # ── Simulate the integration that run_agent() will do ──
            messages = [{"role": "user", "content": "What is 1+2?"}]
            saver.start(task="Add 1+2", system_prompt="You are a math assistant.")
            saver.set_features(get_framework_features("SeekFlow"))

            result = runtime.chat(model="deepseek-chat", messages=messages)

            # Record step 1: model call with tool_calls
            step = saver.begin_step()
            saver.record_model_call(step, len(messages),
                                    content=resp1.content or "",
                                    reasoning=resp1.reasoning_content or "",
                                    finish_reason=resp1.finish_reason or "")
            saver.record_token_usage(step, resp1.usage or {})
            if result.tool_results:
                for tr in result.tool_results:
                    saver.record_tool_call(step, tr.name,
                                          tr.arguments,
                                          str(tr.result or ""),
                                          ok=tr.ok)

            # Step 2: final response (no tool calls)
            step = saver.begin_step()
            saver.record_model_call(step, len(messages) + 2,
                                    content=resp2.content or "",
                                    finish_reason=resp2.finish_reason or "")
            saver.record_token_usage(step, resp2.usage or {})

            saver.finish(final_output=result.final or "", messages=result.messages)

            # Save to temp dir
            import comprehensive_saver as cs
            orig_dir = cs.RUNTIME_DUMP_DIR
            cs.RUNTIME_DUMP_DIR = tmp_path / "runtime_dumps"
            cs.RUNTIME_DUMP_DIR.mkdir(parents=True, exist_ok=True)
            try:
                out_dir = saver.save()
            finally:
                cs.RUNTIME_DUMP_DIR = orig_dir

        # ── Assertions ──
        assert (tmp_path / "runtime_dumps" / "SeekFlow" / "test_agent").exists()
        assert (tmp_path / "runtime_dumps" / "SeekFlow" / "test_agent" / "summary.json").exists()
        assert (tmp_path / "runtime_dumps" / "SeekFlow" / "test_agent" / "message_trace.json").exists()
        assert (tmp_path / "runtime_dumps" / "SeekFlow" / "test_agent" / "runtime_dump.json").exists()

        # Verify summary
        import json
        summary = json.loads(
            (tmp_path / "runtime_dumps" / "SeekFlow" / "test_agent" / "summary.json")
            .read_text(encoding="utf-8")
        )
        assert summary["framework"] == "SeekFlow"
        assert summary["agent_type"] == "test_agent"
        assert summary["success"] is True
        assert summary["total_tokens"] == 43  # 15 + 28
        assert summary["steps"] == 2
        assert summary["tool_calls"] == 1
