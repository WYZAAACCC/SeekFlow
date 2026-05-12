"""Tests for DeepSeekClient."""
import os
from unittest.mock import MagicMock, patch

import pytest
from deepseek_toolkit.client import DeepSeekClient
from deepseek_toolkit.types import ChatResponse, ToolCall


class TestDeepSeekClient:
    @pytest.fixture
    def mock_chat_completion(self):
        """Mock OpenAI().chat.completions.create to return a controlled response."""
        with patch("deepseek_toolkit.client.OpenAI") as mock_openai_class:
            mock_client = MagicMock()
            mock_openai_class.return_value = mock_client
            yield mock_client.chat.completions.create

    def test_api_key_from_param(self):
        client = DeepSeekClient(api_key="sk-explicit")
        assert client.api_key == "sk-explicit"

    def test_default_base_url(self):
        client = DeepSeekClient(api_key="sk-test")
        assert client.base_url == "https://api.deepseek.com"

    def test_custom_base_url(self):
        client = DeepSeekClient(api_key="sk-test", base_url="https://custom.api")
        assert client.base_url == "https://custom.api"

    def test_chat_returns_chat_response(self, mock_chat_completion):
        mock_choice = MagicMock()
        mock_choice.message.content = "Hello!"
        mock_choice.message.tool_calls = None
        mock_choice.message.reasoning_content = None
        mock_choice.finish_reason = "stop"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5
        mock_response.usage.total_tokens = 15

        mock_chat_completion.return_value = mock_response

        client = DeepSeekClient(api_key="sk-test")
        result = client.chat(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "hi"}],
        )

        assert isinstance(result, ChatResponse)
        assert result.content == "Hello!"
        assert result.finish_reason == "stop"
        assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    def test_chat_with_tool_calls(self, mock_chat_completion):
        mock_tc = MagicMock()
        mock_tc.id = "call_1"
        mock_tc.function.name = "get_weather"
        mock_tc.function.arguments = '{"city": "Hangzhou"}'

        mock_choice = MagicMock()
        mock_choice.message.content = None
        mock_choice.message.tool_calls = [mock_tc]
        mock_choice.message.reasoning_content = None
        mock_choice.finish_reason = "tool_calls"

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage.prompt_tokens = 20
        mock_response.usage.completion_tokens = 10
        mock_response.usage.total_tokens = 30

        mock_chat_completion.return_value = mock_response

        client = DeepSeekClient(api_key="sk-test")
        result = client.chat(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "weather?"}],
        )

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "get_weather"
        assert isinstance(result.tool_calls[0], ToolCall)
        assert result.finish_reason == "tool_calls"

    def test_api_key_from_env(self, mock_chat_completion):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-from-env"}):
            client = DeepSeekClient()
            assert client.api_key == "sk-from-env"
