"""Lightweight DeepSeek API client wrapping the OpenAI SDK."""
from __future__ import annotations

import os
from collections.abc import Iterator

from openai import OpenAI, APIStatusError

from deepseek_toolkit.errors import map_http_error, DeepSeekAPIError
from deepseek_toolkit.types import ChatResponse, ToolCall, StreamChunk


def _usage_to_dict(usage: object) -> dict:
    """Convert an OpenAI Usage object to a plain dict."""
    if isinstance(usage, dict):
        return usage
    result: dict = {}
    for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
        val = getattr(usage, field, None)
        if val is not None:
            result[field] = val
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        result["prompt_tokens_details"] = {}
        for field in ("cached_tokens",):
            val = getattr(details, field, None)
            if val is not None:
                result["prompt_tokens_details"][field] = val
    return result


class DeepSeekClient:
    """Lightweight wrapper around OpenAI SDK for DeepSeek API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
        timeout: float = 60.0,
    ):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = (
            base_url
            if base_url != "https://api.deepseek.com"
            else os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        )
        self.timeout = timeout
        self._client = OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=self.timeout)

    def chat(
        self,
        *,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str | dict | None = None,
        stream: bool = False,
        **kwargs,
    ) -> ChatResponse:
        """Send a chat completion request to DeepSeek."""
        client = self._client

        params: dict = {
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
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=tc.function.arguments,
                ))

        reasoning = getattr(choice.message, "reasoning_content", None)
        if not isinstance(reasoning, str):
            reasoning = None

        return ChatResponse(
            content=choice.message.content,
            reasoning_content=reasoning,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            } if response.usage else None,
            raw=response,
        )

    def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        **kwargs,
    ) -> Iterator[StreamChunk]:
        """Send a streaming chat completion request to DeepSeek.

        Yields StreamChunk objects as the model generates tokens.
        Tool calls are accumulated and yielded as structured events.
        """
        client = self._client

        params: dict = {
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
        tool_call_buf: dict[int, dict] = {}
        stream_usage: dict | None = None

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
                yield StreamChunk(type="reasoning", content=rc)

            # Content chunk
            if delta.content:
                yield StreamChunk(type="content", content=delta.content)

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
                            yield StreamChunk(
                                type="tool_call_start",
                                tool_call_id=buf["id"],
                                tool_name=tc_delta.function.name,
                            )
                        if tc_delta.function.arguments:
                            buf["arguments"] += tc_delta.function.arguments
                            yield StreamChunk(
                                type="tool_call_delta",
                                tool_call_id=buf["id"],
                                arguments_delta=tc_delta.function.arguments,
                            )

            # Check finish reason
            if event.choices[0].finish_reason:
                for buf in tool_call_buf.values():
                    yield StreamChunk(
                        type="tool_call_end",
                        tool_call_id=buf["id"],
                        tool_name=buf["name"],
                        content=buf["arguments"],
                    )
                break

        # Yield usage as a final chunk if captured
        if stream_usage:
            yield StreamChunk(type="usage", usage=stream_usage)
