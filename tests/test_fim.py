"""Tests for seekflow.fim — FIM (Fill-in-the-Middle) completions."""
import pytest


class TestFIMResponse:
    def test_fim_response_holds_text_and_usage(self):
        from seekflow.fim import FIMResponse
        resp = FIMResponse(
            text="print('hello')",
            model="deepseek-v4-pro",
            finish_reason="stop",
            usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        assert resp.text == "print('hello')"
        assert resp.model == "deepseek-v4-pro"
        assert resp.finish_reason == "stop"
        assert resp.usage["total_tokens"] == 15

    def test_fim_response_usage_is_none_by_default(self):
        from seekflow.fim import FIMResponse
        resp = FIMResponse(text="x", model="m", finish_reason="length")
        assert resp.usage is None


class TestFIMChunk:
    def test_fim_chunk_holds_text_and_finish_reason(self):
        from seekflow.fim import FIMChunk
        chunk = FIMChunk(text="hello", finish_reason=None)
        assert chunk.text == "hello"
        assert chunk.finish_reason is None

    def test_fim_chunk_finish_reason_set_on_last(self):
        from seekflow.fim import FIMChunk
        chunk = FIMChunk(text="", finish_reason="stop")
        assert chunk.finish_reason == "stop"


class TestFIMComplete:
    def test_fim_complete_returns_response_with_text(self):
        from unittest.mock import patch, MagicMock
        from seekflow.fim import fim_complete, FIMResponse

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].text = "middle_content"
        mock_resp.choices[0].finish_reason = "stop"
        mock_resp.model = "deepseek-v4-pro"
        mock_resp.usage = MagicMock()
        mock_resp.usage.prompt_tokens = 10
        mock_resp.usage.completion_tokens = 5
        mock_resp.usage.total_tokens = 15
        mock_client.completions.create.return_value = mock_resp

        with patch("seekflow.fim._make_fim_client", return_value=mock_client):
            result = fim_complete(
                prefix="def greet():\n    ",
                suffix="\n\ngreet()",
                model="deepseek-v4-pro",
                api_key="sk-test",
            )
            assert isinstance(result, FIMResponse)
            assert result.text == "middle_content"

    def test_fim_complete_passes_max_tokens_and_temperature(self):
        from unittest.mock import patch, MagicMock
        from seekflow.fim import fim_complete

        mock_client = MagicMock()
        mock_client.completions.create.return_value = MagicMock(
            choices=[MagicMock(text="ok", finish_reason="stop")],
            model="m", usage=None,
        )
        with patch("seekflow.fim._make_fim_client", return_value=mock_client):
            fim_complete(
                prefix="a", suffix="b", model="deepseek-v4-pro",
                api_key="sk-test", max_tokens=100, temperature=0.5,
            )
            call_kwargs = mock_client.completions.create.call_args.kwargs
            assert call_kwargs["max_tokens"] == 100
            assert call_kwargs["temperature"] == 0.5

    def test_fim_complete_with_stop_sequences(self):
        from unittest.mock import patch, MagicMock
        from seekflow.fim import fim_complete

        mock_client = MagicMock()
        mock_client.completions.create.return_value = MagicMock(
            choices=[MagicMock(text="ok", finish_reason="stop")],
            model="m", usage=None,
        )
        with patch("seekflow.fim._make_fim_client", return_value=mock_client):
            fim_complete(
                prefix="a", suffix="b", model="deepseek-v4-pro",
                api_key="sk-test", stop=["\n\n"],
            )
            call_kwargs = mock_client.completions.create.call_args.kwargs
            assert call_kwargs["stop"] == ["\n\n"]


class TestFIMCompleteStream:
    def test_fim_complete_stream_yields_chunks(self):
        from unittest.mock import patch, MagicMock
        from seekflow.fim import fim_complete_stream, FIMChunk

        mock_client = MagicMock()
        events = []
        for text in ["print", "('hello", "')"]:
            e = MagicMock()
            e.choices = [MagicMock()]
            e.choices[0].text = text
            e.choices[0].finish_reason = None
            events.append(e)
        events[-1].choices[0].finish_reason = "stop"

        mock_client.completions.create.return_value = iter(events)

        with patch("seekflow.fim._make_fim_client", return_value=mock_client):
            chunks = list(fim_complete_stream(
                prefix="def f():", suffix="",
                model="deepseek-v4-pro", api_key="sk-test",
            ))
            assert len(chunks) == 3
            assert all(isinstance(c, FIMChunk) for c in chunks)
            assert chunks[-1].finish_reason == "stop"
            combined = "".join(c.text for c in chunks)
            assert combined == "print('hello')"
