"""Core data types for SeekFlow."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

# ── Type aliases ─────────────────────────────────────────────────
ToolChoice = Literal["auto", "none", "required"] | dict[str, Any]
"""Valid tool_choice values for DeepSeek API."""

RiskLevel = Literal["read", "write", "network", "code_exec", "destructive"]


class ToolPolicy(BaseModel):
    """Security and execution policy for a tool.

    Defines what a tool is allowed to do, its risk level, resource
    limits, and whether it requires human approval.
    """

    capabilities: set[str] = Field(default_factory=set)
    risk: RiskLevel = "read"
    timeout_s: float = 30.0
    max_input_bytes: int = 1_000_000
    max_output_bytes: int = 100_000
    parallel_safe: bool = False
    requires_approval: bool = False
    allowed_domains: set[str] = Field(default_factory=set)
    workspace_root: Path | None = None
    path_params: frozenset[str] = Field(default_factory=frozenset)
    url_params: frozenset[str] = Field(default_factory=frozenset)


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any] | None = None
    source: str = "local"
    metadata: dict[str, Any] = Field(default_factory=dict)
    policy: ToolPolicy | None = None

    def with_policy(self, policy: ToolPolicy) -> ToolDefinition:
        """Return a copy of this definition with *policy* attached."""
        return self.model_copy(update={"policy": policy})


class ToolCall(BaseModel):
    """A tool call from the model.

    When the API returns valid JSON, ``arguments`` is a dict.
    When JSON is malformed, ``arguments`` is the raw string so the
    repair pipeline can attempt salvage.
    """
    id: str | None = None
    name: str
    arguments: dict | str = Field(default_factory=dict)
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


class _StreamChunk(BaseModel):
    """Internal transport unit from streaming API. Use StreamEvent for public API."""
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
