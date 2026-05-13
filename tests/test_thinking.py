"""Tests for thinking_mode first-class parameter."""
import warnings
from unittest.mock import patch, MagicMock


class TestThinkingModeParameter:
    """thinking_mode maps to extra_body={"thinking": {"type": ...}}."""

    @staticmethod
    def _make_mock_client():
        client = MagicMock()
        client.chat.return_value = MagicMock(
            content="done",
            reasoning_content=None,
            tool_calls=[],
            finish_reason="stop",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw=None,
        )
        return client

    def test_thinking_mode_enabled_maps_to_extra_body(self):
        from seekflow.runtime import ToolRuntime
        rt = ToolRuntime(tools=[], api_key="sk-test", max_steps=1)
        client = self._make_mock_client()
        rt._client = client

        rt.chat(
            model="deepseek-v4-pro",
            messages=[{"role": "user", "content": "hi"}],
            thinking_mode="enabled",
        )
        call_kwargs = client.chat.call_args.kwargs
        assert call_kwargs["extra_body"] == {"thinking": {"type": "enabled", "budget_tokens": 2048}}

    def test_thinking_mode_max_maps_to_extra_body(self):
        from seekflow.runtime import ToolRuntime
        rt = ToolRuntime(tools=[], api_key="sk-test", max_steps=1)
        client = self._make_mock_client()
        rt._client = client

        rt.chat(
            model="deepseek-v4-pro",
            messages=[{"role": "user", "content": "hi"}],
            thinking_mode="max",
        )
        call_kwargs = client.chat.call_args.kwargs
        assert call_kwargs["extra_body"] == {"thinking": {"type": "max"}}

    def test_thinking_mode_none_defaults_to_enabled_single_turn(self):
        """thinking_mode=None on single-turn → extra_body["thinking"]="enabled"."""
        from seekflow.runtime import ToolRuntime
        rt = ToolRuntime(tools=[], api_key="sk-test", max_steps=1)
        client = self._make_mock_client()
        rt._client = client

        rt.chat(
            model="deepseek-v4-pro",
            messages=[{"role": "user", "content": "hi"}],
        )
        call_kwargs = client.chat.call_args.kwargs
        assert call_kwargs["extra_body"]["thinking"] == {"type": "enabled", "budget_tokens": 2048}

    def test_thinking_mode_overrides_extra_body_thinking(self):
        from seekflow.runtime import ToolRuntime
        rt = ToolRuntime(tools=[], api_key="sk-test", max_steps=1)
        client = self._make_mock_client()
        rt._client = client

        rt.chat(
            model="deepseek-v4-pro",
            messages=[{"role": "user", "content": "hi"}],
            thinking_mode="enabled",
            extra_body={"thinking": {"type": "max"}, "temperature": 0.5},
        )
        call_kwargs = client.chat.call_args.kwargs
        assert call_kwargs["extra_body"]["thinking"] == {"type": "enabled", "budget_tokens": 2048}
        assert call_kwargs["extra_body"]["temperature"] == 0.5

    def test_chat_stream_supports_thinking_mode(self):
        from seekflow.runtime import ToolRuntime
        from seekflow.types import StreamEvent
        rt = ToolRuntime(tools=[], api_key="sk-test", max_steps=1)
        client = self._make_mock_client()

        # chat_stream for stream mode
        client.chat_stream.return_value = iter([
            StreamEvent(type="content", content="ok"),
            StreamEvent(type="done"),
        ])
        rt._client = client

        list(rt.chat_stream(
            model="deepseek-v4-pro",
            messages=[{"role": "user", "content": "hi"}],
            thinking_mode="enabled",
        ))
        call_kwargs = client.chat_stream.call_args.kwargs
        assert call_kwargs["extra_body"] == {"thinking": {"type": "enabled", "budget_tokens": 2048}}


class TestThinkingModeSmartDefault:
    """Smart defaults: single-turn enables thinking, multi-turn disables it."""

    SINGLE_TURN = [{"role": "user", "content": "hi"}]
    MULTI_TURN = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "add", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "ok"},
    ]

    @staticmethod
    def _make_mock_client():
        client = MagicMock()
        client.chat.return_value = MagicMock(
            content="done", reasoning_content=None, tool_calls=[],
            finish_reason="stop",
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw=None,
        )
        return client

    def test_single_turn_default_enables_thinking(self):
        """thinking_mode=None on single-turn → extra_body["thinking"]="enabled"."""
        from seekflow.runtime import ToolRuntime
        rt = ToolRuntime(tools=[], api_key="sk-test", max_steps=1)
        client = self._make_mock_client()
        rt._client = client

        rt.chat(model="deepseek-v4-pro", messages=self.SINGLE_TURN)
        call_kwargs = client.chat.call_args.kwargs
        assert call_kwargs["extra_body"]["thinking"] == {"type": "enabled", "budget_tokens": 2048}

    def test_multi_turn_default_disables_thinking_and_warns(self):
        """thinking_mode=None on multi-turn → extra_body["thinking"]="disabled" + UserWarning."""
        from seekflow.runtime import ToolRuntime
        rt = ToolRuntime(tools=[], api_key="sk-test", max_steps=1)
        client = self._make_mock_client()
        rt._client = client

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            rt.chat(model="deepseek-v4-pro", messages=self.MULTI_TURN)

        call_kwargs = client.chat.call_args.kwargs
        assert call_kwargs["extra_body"]["thinking"] == {"type": "disabled"}

        assert len(w) >= 1
        warning_msgs = [str(x.message) for x in w]
        assert any("automatically" in msg and "disabled" in msg for msg in warning_msgs), warning_msgs

    def test_multi_turn_explicit_enabled_respected(self):
        """thinking_mode="enabled" on multi-turn → not downgraded, no warning."""
        from seekflow.runtime import ToolRuntime
        rt = ToolRuntime(tools=[], api_key="sk-test", max_steps=1)
        client = self._make_mock_client()
        rt._client = client

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            rt.chat(model="deepseek-v4-pro", messages=self.MULTI_TURN, thinking_mode="enabled")

        call_kwargs = client.chat.call_args.kwargs
        assert call_kwargs["extra_body"]["thinking"] == {"type": "enabled", "budget_tokens": 2048}
        # No auto-downgrade warning
        warning_msgs = [str(x.message) for x in w]
        assert not any("automatically" in msg for msg in warning_msgs)

    def test_multi_turn_explicit_disabled_respected(self):
        """thinking_mode="disabled" on multi-turn → not changed, no warning."""
        from seekflow.runtime import ToolRuntime
        rt = ToolRuntime(tools=[], api_key="sk-test", max_steps=1)
        client = self._make_mock_client()
        rt._client = client

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            rt.chat(model="deepseek-v4-pro", messages=self.MULTI_TURN, thinking_mode="disabled")

        call_kwargs = client.chat.call_args.kwargs
        assert call_kwargs["extra_body"]["thinking"] == {"type": "disabled"}
        warning_msgs = [str(x.message) for x in w]
        assert not any("automatically" in msg for msg in warning_msgs)

    def test_multi_turn_explicit_max_respected(self):
        """thinking_mode="max" on multi-turn → not downgraded, no warning."""
        from seekflow.runtime import ToolRuntime
        rt = ToolRuntime(tools=[], api_key="sk-test", max_steps=1)
        client = self._make_mock_client()
        rt._client = client

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            rt.chat(model="deepseek-v4-pro", messages=self.MULTI_TURN, thinking_mode="max")

        call_kwargs = client.chat.call_args.kwargs
        assert call_kwargs["extra_body"]["thinking"] == {"type": "max"}
        warning_msgs = [str(x.message) for x in w]
        assert not any("automatically" in msg for msg in warning_msgs)

    def test_streaming_default_single_turn_enables_thinking(self):
        """chat_stream with thinking_mode=None on single-turn enables thinking."""
        from seekflow.runtime import ToolRuntime
        from seekflow.types import StreamEvent
        rt = ToolRuntime(tools=[], api_key="sk-test", max_steps=1)
        client = self._make_mock_client()
        client.chat_stream.return_value = iter([
            StreamEvent(type="content", content="ok"),
            StreamEvent(type="done"),
        ])
        rt._client = client

        list(rt.chat_stream(model="deepseek-v4-pro", messages=self.SINGLE_TURN))
        call_kwargs = client.chat_stream.call_args.kwargs
        assert call_kwargs["extra_body"]["thinking"] == {"type": "enabled", "budget_tokens": 2048}

    def test_streaming_default_multi_turn_disables_thinking(self):
        """chat_stream with thinking_mode=None on multi-turn disables thinking."""
        from seekflow.runtime import ToolRuntime
        from seekflow.types import StreamEvent
        rt = ToolRuntime(tools=[], api_key="sk-test", max_steps=1)
        client = self._make_mock_client()
        client.chat_stream.return_value = iter([
            StreamEvent(type="content", content="ok"),
            StreamEvent(type="done"),
        ])
        rt._client = client

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            list(rt.chat_stream(model="deepseek-v4-pro", messages=self.MULTI_TURN))

        call_kwargs = client.chat_stream.call_args.kwargs
        assert call_kwargs["extra_body"]["thinking"] == {"type": "disabled"}
        warning_msgs = [str(x.message) for x in w]
        assert any("automatically" in msg and "disabled" in msg for msg in warning_msgs)
