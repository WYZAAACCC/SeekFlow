"""Runtime-specific error types."""
from __future__ import annotations


class SeekFlowError(Exception):
    """Base error for SeekFlow runtime."""


class DeepSeekProtocolError(SeekFlowError):
    """Raised when a message sequence violates DeepSeek API protocol."""


class ToolExecutionError(SeekFlowError):
    """Raised when tool execution fails."""


class SecurityPolicyError(SeekFlowError):
    """Raised when a tool call violates security policy."""
