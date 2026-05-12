"""Tests for deepseek_toolkit.errors — verify error hierarchy."""
import pytest
from deepseek_toolkit.errors import (
    DeepSeekToolkitError,
    ToolSchemaError,
    StrictSchemaError,
    ToolNotFoundError,
    ToolArgumentError,
    ToolExecutionError,
    MCPConnectionError,
    MCPToolExecutionError,
    EvalConfigError,
    DeepSeekAPIError,
    InsufficientBalanceError,
    AuthenticationError,
    RateLimitError,
    ContextLengthExceededError,
    ServiceUnavailableError,
)


class TestErrorHierarchy:
    def test_base_error_is_exception(self):
        with pytest.raises(DeepSeekToolkitError):
            raise DeepSeekToolkitError("base error")

    def test_tool_schema_error_is_base_error(self):
        with pytest.raises(DeepSeekToolkitError):
            raise ToolSchemaError("schema error")

    def test_strict_schema_error_is_base_error(self):
        with pytest.raises(DeepSeekToolkitError):
            raise StrictSchemaError("strict error")

    def test_tool_not_found_error_is_base_error(self):
        with pytest.raises(DeepSeekToolkitError):
            raise ToolNotFoundError("not found")

    def test_tool_argument_error_is_base_error(self):
        with pytest.raises(DeepSeekToolkitError):
            raise ToolArgumentError("bad arg")

    def test_tool_execution_error_is_base_error(self):
        with pytest.raises(DeepSeekToolkitError):
            raise ToolExecutionError("exec failed")

    def test_mcp_connection_error_is_base_error(self):
        with pytest.raises(DeepSeekToolkitError):
            raise MCPConnectionError("mcp conn failed")

    def test_mcp_tool_execution_error_is_base_error(self):
        with pytest.raises(DeepSeekToolkitError):
            raise MCPToolExecutionError("mcp exec failed")

    def test_eval_config_error_is_base_error(self):
        with pytest.raises(DeepSeekToolkitError):
            raise EvalConfigError("eval config error")

    def test_subclass_captured_by_specific_type(self):
        with pytest.raises(ToolNotFoundError):
            raise ToolNotFoundError("not found")

    def test_error_message_preserved(self):
        try:
            raise ToolExecutionError("something broke")
        except ToolExecutionError as e:
            assert str(e) == "something broke"


class TestDeepSeekAPIErrors:
    """DeepSeek API error types with HTTP status mapping and suggestions."""

    def test_insufficient_balance_error_carries_suggestion(self):
        error = InsufficientBalanceError()
        assert "余额" in error.suggestion or "balance" in error.suggestion.lower()
        assert error.http_status == 402

    def test_insufficient_balance_error_is_api_error(self):
        with pytest.raises(DeepSeekAPIError):
            raise InsufficientBalanceError()

    def test_authentication_error_has_http_401(self):
        error = AuthenticationError()
        assert error.http_status == 401
        assert len(error.suggestion) > 0

    def test_rate_limit_error_carries_remaining_and_reset(self):
        error = RateLimitError(remaining=0, reset=1700000000.0)
        assert error.remaining == 0
        assert error.reset == 1700000000.0
        assert error.http_status == 429

    def test_rate_limit_error_remaining_defaults_to_none(self):
        error = RateLimitError()
        assert error.remaining is None
        assert error.reset is None

    def test_context_length_exceeded_error_has_http_400(self):
        error = ContextLengthExceededError()
        assert error.http_status == 400
        assert len(error.suggestion) > 0

    def test_service_unavailable_error_has_http_503(self):
        error = ServiceUnavailableError()
        assert error.http_status == 503
        assert len(error.suggestion) > 0

    def test_all_api_errors_inherit_from_deepseek_api_error(self):
        for cls in [InsufficientBalanceError, AuthenticationError,
                     RateLimitError, ContextLengthExceededError,
                     ServiceUnavailableError, DeepSeekAPIError]:
            assert issubclass(cls, DeepSeekToolkitError), f"{cls.__name__} should be DeepSeekToolkitError"

    def test_api_errors_preserve_message(self):
        error = InsufficientBalanceError("余额不足，请充值")
        assert str(error) == "余额不足，请充值"


class TestMapHttpError:
    """Mapping HTTP status codes to DeepSeek-specific errors."""

    def test_402_maps_to_insufficient_balance(self):
        from deepseek_toolkit.errors import map_http_error
        error = map_http_error(402, "Insufficient balance")
        assert isinstance(error, InsufficientBalanceError)
        assert "Insufficient balance" in str(error)

    def test_401_maps_to_authentication(self):
        from deepseek_toolkit.errors import map_http_error
        error = map_http_error(401, "Invalid API key")
        assert isinstance(error, AuthenticationError)

    def test_429_maps_to_rate_limit_with_headers(self):
        from deepseek_toolkit.errors import map_http_error
        error = map_http_error(429, "Too many requests",
                               headers={"X-RateLimit-Remaining": "0",
                                        "X-RateLimit-Reset": "1700000000"})
        assert isinstance(error, RateLimitError)
        assert error.remaining == 0
        assert error.reset == 1700000000.0

    def test_400_context_length_maps_when_message_indicates(self):
        from deepseek_toolkit.errors import map_http_error
        error = map_http_error(400, "context length exceeded maximum")
        assert isinstance(error, ContextLengthExceededError)

    def test_503_maps_to_service_unavailable(self):
        from deepseek_toolkit.errors import map_http_error
        error = map_http_error(503, "Service unavailable")
        assert isinstance(error, ServiceUnavailableError)

    def test_unknown_status_returns_generic_api_error(self):
        from deepseek_toolkit.errors import map_http_error
        error = map_http_error(418, "I'm a teapot")
        assert isinstance(error, DeepSeekAPIError)
        assert error.http_status == 418

    def test_rate_limit_headers_missing_uses_none(self):
        from deepseek_toolkit.errors import map_http_error
        error = map_http_error(429, "Rate limited")
        assert error.remaining is None
        assert error.reset is None


class TestClientErrorMapping:
    """DeepSeekClient raises DeepSeekAPIError subclasses for HTTP errors."""

    def _make_fake_response(self, status_code, headers=None, text=""):
        """Build a minimal httpx.Response-like object for error testing."""
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.status_code = status_code
        resp.headers = headers or {}
        resp.text = text
        return resp

    def test_402_raises_insufficient_balance_error(self):
        from unittest.mock import patch
        from openai import APIStatusError
        from deepseek_toolkit.client import DeepSeekClient
        from deepseek_toolkit.errors import InsufficientBalanceError

        client = DeepSeekClient(api_key="sk-test")
        fake_resp = self._make_fake_response(402, text="Insufficient balance")

        with patch.object(client._client.chat.completions, "create",
                          side_effect=APIStatusError("Insufficient balance", response=fake_resp, body={})):
            with pytest.raises(InsufficientBalanceError):
                client.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])

    def test_401_raises_authentication_error(self):
        from unittest.mock import patch
        from openai import AuthenticationError as OpenAIAuthError
        from deepseek_toolkit.client import DeepSeekClient
        from deepseek_toolkit.errors import AuthenticationError

        client = DeepSeekClient(api_key="sk-test")
        fake_resp = self._make_fake_response(401, text="Invalid API key")

        with patch.object(client._client.chat.completions, "create",
                          side_effect=OpenAIAuthError("Invalid API key", response=fake_resp, body={})):
            with pytest.raises(AuthenticationError):
                client.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])

    def test_429_raises_rate_limit_error_with_remaining(self):
        from unittest.mock import patch
        from openai import APIStatusError
        from deepseek_toolkit.client import DeepSeekClient
        from deepseek_toolkit.errors import RateLimitError

        client = DeepSeekClient(api_key="sk-test")
        fake_resp = self._make_fake_response(429,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"},
            text="Rate limited")

        with patch.object(client._client.chat.completions, "create",
                          side_effect=APIStatusError("Rate limited", response=fake_resp, body={})):
            with pytest.raises(RateLimitError) as exc_info:
                client.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])
            assert exc_info.value.remaining == 0
            assert exc_info.value.reset == 1700000000.0

    def test_non_http_error_passes_through(self):
        from unittest.mock import patch
        from deepseek_toolkit.client import DeepSeekClient

        client = DeepSeekClient(api_key="sk-test")

        with patch.object(client._client.chat.completions, "create",
                          side_effect=ValueError("unrelated error")):
            with pytest.raises(ValueError):
                client.chat(model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])
