"""Error types for SeekFlow."""


class SeekFlowError(Exception):
    """Base error for all SeekFlow exceptions."""
    pass


# ── DeepSeek API errors ────────────────────────────────────────────────────

class DeepSeekAPIError(SeekFlowError):
    """Base error for DeepSeek API responses (HTTP-level errors)."""
    http_status: int = 0
    suggestion: str = ""


class AuthenticationError(DeepSeekAPIError):
    """401 — API key is invalid or missing."""
    http_status = 401
    suggestion = "请检查 API Key 是否正确设置。可在 https://platform.deepseek.com 查看。"


class InsufficientBalanceError(DeepSeekAPIError):
    """402 — Account balance is insufficient."""
    http_status = 402
    suggestion = "账户余额不足，请前往 https://platform.deepseek.com 充值。"


class RateLimitError(DeepSeekAPIError):
    """429 — Rate limit exceeded, with optional remaining/reset info."""

    http_status = 429
    suggestion = "请求频率过高，请稍后重试或降低并发。"

    def __init__(self, message: str = "", remaining: int | None = None, reset: float | None = None):
        super().__init__(message or self.suggestion)
        self.remaining = remaining
        self.reset = reset


class ContextLengthExceededError(DeepSeekAPIError):
    """400 — Input exceeds the model's context window."""
    http_status = 400
    suggestion = "输入内容超过模型上下文窗口限制。请减少输入长度或使用上下文压缩策略。"


class ServiceUnavailableError(DeepSeekAPIError):
    """503 — DeepSeek service is temporarily unavailable."""
    http_status = 503
    suggestion = "DeepSeek 服务暂时不可用，请稍后重试。"


# ── HTTP status → error mapping ────────────────────────────────────────────

def map_http_error(
    status_code: int,
    message: str = "",
    headers: dict | None = None,
) -> DeepSeekAPIError:
    """Map an HTTP status code (and optional message) to a DeepSeek error type."""
    headers = headers or {}

    if status_code == 401:
        return AuthenticationError(message)
    if status_code == 402:
        return InsufficientBalanceError(message)
    if status_code == 429:
        remaining = _parse_int_header(headers.get("X-RateLimit-Remaining"))
        reset = _parse_float_header(headers.get("X-RateLimit-Reset"))
        return RateLimitError(message, remaining=remaining, reset=reset)
    if status_code == 400:
        if "context" in message.lower() and ("length" in message.lower() or "exceed" in message.lower()):
            return ContextLengthExceededError(message)
    if status_code == 503:
        return ServiceUnavailableError(message)

    error = DeepSeekAPIError(message)
    error.http_status = status_code
    return error


def _parse_int_header(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _parse_float_header(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


class ToolSchemaError(SeekFlowError):
    """Error related to tool schema generation or validation."""
    pass


class StrictSchemaError(SeekFlowError):
    """Error when strict schema validation fails and fallback is disabled."""
    pass


class ToolNotFoundError(SeekFlowError):
    """Error when a requested tool is not found in the registry."""
    pass


class ToolArgumentError(SeekFlowError):
    """Error related to tool call arguments."""
    pass


class ToolExecutionError(SeekFlowError):
    """Error when tool execution fails."""
    pass


class MCPConnectionError(SeekFlowError):
    """Error when MCP server connection fails."""
    pass


class MCPToolExecutionError(SeekFlowError):
    """Error when MCP tool execution fails."""
    pass


class EvalConfigError(SeekFlowError):
    """Error related to eval configuration."""
    pass
