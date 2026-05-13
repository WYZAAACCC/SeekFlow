"""Lightweight DeepSeek API client wrapping the OpenAI SDK."""
from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

from openai import OpenAI, APIStatusError

from deepseek_toolkit.errors import map_http_error
from deepseek_toolkit.types import ChatResponse, ToolCall, _StreamChunk


def _usage_to_dict(usage: object) -> dict[str, Any]:
    """Convert an OpenAI Usage object to a plain dict."""
    if isinstance(usage, dict):
        return usage
    result: dict[str, Any] = {}
    for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
        val = getattr(usage, field, None)
        if val is not None:
            result[field] = val
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        details_dict: dict[str, Any] = {}
        for field in ("cached_tokens",):
            val = getattr(details, field, None)
            if val is not None:
                details_dict[field] = val
        if details_dict:
            result["prompt_tokens_details"] = details_dict
    return result


class DeepSeekClient:
    """Lightweight wrapper around OpenAI SDK for DeepSeek API."""

    api_key: str
    base_url: str
    timeout: float
    _client: OpenAI

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
        timeout: float = 60.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = (
            base_url
            if base_url != "https://api.deepseek.com"
            else os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        )
        self.timeout = timeout
        self._client = OpenAI(
            api_key=self.api_key, base_url=self.base_url, timeout=timeout,
        )

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> ChatResponse:
        """Send a chat completion request to DeepSeek."""
        client = self._client

        params: dict[str, Any] = {
            "model": model,
            "messages": messages,
            **kwargs,
        }
        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice

        try:
            response = client.chat.completions.create(**params)
        except APIStatusError as e:
            raise map_http_error(
                e.status_code,
                e.message,
                headers=dict(e.response.headers) if e.response else None,
            ) from e

        choice = response.choices[0]
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                # Parse string arguments at the API boundary so downstream
                # code always sees ToolCall.arguments as dict.
                raw_args: str = tc.function.arguments
                try:
                    parsed_args: dict[str, Any] = json.loads(raw_args)
                except json.JSONDecodeError:
                    parsed_args = {}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=parsed_args,
                ))

        reasoning = getattr(choice.message, "reasoning_content", None)
        if not isinstance(reasoning, str):
            reasoning = None

        usage_dict = None
        if response.usage:
            usage_dict = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
            # Preserve prompt_tokens_details for cache token tracking
            details = getattr(response.usage, "prompt_tokens_details", None)
            if details is not None:
                cached = getattr(details, "cached_tokens", 0)
                usage_dict["prompt_tokens_details"] = {"cached_tokens": cached}

        return ChatResponse(
            content=choice.message.content,
            reasoning_content=reasoning,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            usage=usage_dict,
            raw=response,
        )

    def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Iterator[_StreamChunk]:
        """Send a streaming chat completion request to DeepSeek.

        Yields _StreamChunk objects as the model generates tokens.
        Tool calls are accumulated and yielded as structured events.
        """
        client = self._client

        params: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            **kwargs,
        }
        if tools:
            params["tools"] = tools

        try:
            stream = client.chat.completions.create(**params)
        except APIStatusError as e:
            raise map_http_error(
                e.status_code,
                e.message,
                headers=dict(e.response.headers) if e.response else None,
            ) from e

        # Accumulate tool call deltas
        tool_call_buf: dict[int, dict[str, str]] = {}
        stream_usage: dict[str, Any] | None = None

        for event in stream:
            # Capture usage from the stream event (OpenAI SDK puts it on the last chunk)
            if hasattr(event, "usage") and event.usage is not None:
                stream_usage = _usage_to_dict(event.usage)

            delta = event.choices[0].delta if event.choices else None
            if delta is None:
                continue

            # Reasoning content chunk (DeepSeek R1)
            rc = getattr(delta, "reasoning_content", None)
            if rc:
                yield _StreamChunk(type="reasoning", content=rc)

            # Content chunk
            if delta.content:
                yield _StreamChunk(type="content", content=delta.content)

            # Tool call deltas
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_call_buf:
                        tool_call_buf[idx] = {
                            "id": tc_delta.id or "",
                            "name": "",
                            "arguments": "",
                        }
                    buf = tool_call_buf[idx]
                    if tc_delta.id:
                        buf["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            buf["name"] += tc_delta.function.name
                            yield _StreamChunk(
                                type="tool_call_start",
                                tool_call_id=buf["id"],
                                tool_name=tc_delta.function.name,
                            )
                        if tc_delta.function.arguments:
                            buf["arguments"] += tc_delta.function.arguments
                            yield _StreamChunk(
                                type="tool_call_delta",
                                tool_call_id=buf["id"],
                                arguments_delta=tc_delta.function.arguments,
                            )

            # Check finish reason
            if event.choices[0].finish_reason:
                for buf in tool_call_buf.values():
                    yield _StreamChunk(
                        type="tool_call_end",
                        tool_call_id=buf["id"],
                        tool_name=buf["name"],
                        content=buf["arguments"],
                    )
                break

        # Yield usage as a final chunk if captured
        if stream_usage:
            yield _StreamChunk(type="usage", usage=stream_usage)
