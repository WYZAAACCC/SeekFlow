"""Core data types for DeepSeek Toolkit."""
from typing import Any, Callable

from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any] | None = None
    source: str = "local"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    id: str | None = None
    name: str
    arguments: str | dict
    raw: dict | None = None


class ToolExecutionResult(BaseModel):
    tool_call_id: str | None = None
    name: str
    arguments: dict
    ok: bool
    result: Any | None = None
    error: str | None = None
    elapsed_ms: int | None = None
    repaired: bool = False
    repair_notes: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: dict | None = None
    raw: Any | None = None


class StreamChunk(BaseModel):
    """A single chunk from a streaming response."""
    type: str  # "content", "reasoning", "tool_call_start", "tool_call_delta", "tool_call_end", "usage"
    content: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None
    arguments_delta: str | None = None
    usage: dict | None = None


class StreamEvent(BaseModel):
    """An event yielded by ToolRuntime.chat_stream()."""
    type: str  # "content", "reasoning", "tool_call_start", "tool_call_result", "done"
    content: str | None = None
    reasoning_content: str | None = None
    tool_name: str | None = None
    tool_result: Any | None = None
    finish_reason: str | None = None
    usage: dict | None = None


class ToolRuntimeResult(BaseModel):
    final: str
    messages: list[dict]
    tool_results: list[ToolExecutionResult] = Field(default_factory=list)
    trace: Any | None = None
    usage: dict | None = None
    circuit_breaker_open: bool = False
    cache_stats: dict | None = None
    reasoning_contents: list[str] = Field(default_factory=list)
    empty_content_retries: int = 0
    hallucinated_tool_retries: int = 0
