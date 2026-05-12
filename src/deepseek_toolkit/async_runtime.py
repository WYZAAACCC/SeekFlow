"""Async runtime — asyncio-native ToolRuntime for FastAPI and async apps."""
from __future__ import annotations

import asyncio
import json
import time
import warnings
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI, APIStatusError

from deepseek_toolkit.errors import StrictSchemaError, map_http_error
from deepseek_toolkit.files import embed_files_into_message
from deepseek_toolkit.reasoning import check_consistency
from deepseek_toolkit.retry import (
    ALL_RETRY_CODES,
    RATE_LIMIT_HTTP_CODES,
    CircuitBreaker,
    CircuitBreakerOpenError,
    RetryPolicy,
    compute_delay,
)
from deepseek_toolkit.tool_cache import ToolCallCache
from deepseek_toolkit.tools.executor import ToolExecutor
from deepseek_toolkit.tools.registry import ToolRegistry
from deepseek_toolkit.tools.strict import check_strict_compatibility
from deepseek_toolkit.trace.recorder import TraceRecorder
from deepseek_toolkit.truncation import TruncationStrategy
from deepseek_toolkit.types import (
    ChatResponse,
    StreamEvent,
    ToolCall,
    ToolRuntimeResult,
)
from deepseek_toolkit.runtime import _apply_thinking_mode


class AsyncToolRuntime:
    """Async mirror of ToolRuntime — full feature parity for asyncio-native apps.

    Supports: retry + circuit breaker, tool cache, trace recording,
    context window management, strict check, MCP, parallel tool execution,
    empty-content recovery, and reasoning consistency checking.
    """

    def __init__(
        self,
        tools: list,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
        max_steps: int = 10,
        repair: bool = True,
        max_result_chars: int = 6000,
        strict: bool = False,
        strict_fallback: bool = True,
        timeout: float = 120.0,
        max_context_tokens: int | None = None,
        retry_policy: RetryPolicy | None = None,
        cache_size: int = 128,
        cache_ttl: float | None = None,
        truncation_strategy: TruncationStrategy = TruncationStrategy.JSON_AWARE,
    ):
        self._registry = ToolRegistry()
        for t in tools:
            self._registry.register(t)
        self._api_key = api_key
        self._base_url = base_url
        self._max_steps = max_steps
        self._repair = repair
        self._max_result_chars = max_result_chars
        self._strict = strict
        self._strict_fallback = strict_fallback
        self._timeout = timeout
        self._max_context_tokens = max_context_tokens
        self._truncation_strategy = truncation_strategy
        self._retry_policy = retry_policy or RetryPolicy.default()
        self._circuit_breaker = CircuitBreaker(
            threshold=self._retry_policy.circuit_breaker_threshold,
            cooldown=self._retry_policy.cooldown,
        )
        self._cache_size = cache_size
        self._cache_ttl = cache_ttl
        self._active_cache: ToolCallCache | None = None
        self._last_messages: list[dict[str, Any]] = []
        # MCP
        self._mcp_servers: list = []
        self._mcp_connected = False
        self._mcp_executor: Any = None

    def _connect_mcp(self) -> None:
        """Connect to MCP servers and register their tools."""
        if self._mcp_connected or not self._mcp_servers:
            return
        from deepseek_toolkit.mcp.executor import MCPToolExecutor
        self._mcp_executor = MCPToolExecutor(list(self._mcp_servers))
        self._mcp_executor.connect_and_register(self._registry)
        self._mcp_connected = True

    # ── Context management (delegates to _runtime_base) ─────────────

    @staticmethod
    def _estimate_tokens(messages: list[dict]) -> int:
        from deepseek_toolkit._runtime_base import estimate_tokens
        return estimate_tokens(messages)

    def _trim_messages(self, messages: list[dict]) -> list[dict]:
        from deepseek_toolkit._runtime_base import trim_messages
        return trim_messages(messages, self._max_context_tokens)

    # ── Async retry with circuit breaker ────────────────────────────

    async def _retry_request(self, fn, operation_name: str = "request"):
        self._circuit_breaker.allow_request()
        attempt = 0
        last_exception = None
        while attempt <= self._retry_policy.max_retries:
            try:
                result = await fn()
                self._circuit_breaker.record_success()
                return result
            except APIStatusError as e:
                status = e.status_code
                if status in RATE_LIMIT_HTTP_CODES:
                    headers = dict(e.response.headers) if e.response else {}
                    retry_after = float(headers.get("Retry-After", "1"))
                    await asyncio.sleep(retry_after)
                    continue
                if status not in ALL_RETRY_CODES:
                    self._circuit_breaker.record_failure()
                    raise map_http_error(status, e.message,
                        headers=dict(e.response.headers) if e.response else None) from e
                last_exception = e
                if attempt < self._retry_policy.max_retries:
                    delay = compute_delay(self._retry_policy, attempt)
                    await asyncio.sleep(delay)
                attempt += 1
        self._circuit_breaker.record_failure()
        raise last_exception  # type: ignore[misc]

    # ── Main chat loop ──────────────────────────────────────────────

    async def chat_async(
        self,
        *,
        model: str,
        messages: list[dict],
        files: list[str] | None = None,
        thinking_mode: str | None = None,
        response_format: str | None = None,
        **kwargs,
    ) -> ToolRuntimeResult:
        kwargs = _apply_thinking_mode(thinking_mode, kwargs, messages=messages)
        if response_format:
            kwargs["response_format"] = {"type": response_format}

        if files:
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user":
                    messages[i] = embed_files_into_message(messages[i], files)
                    break

        self._connect_mcp()

        recorder = TraceRecorder(enabled=True)
        recorder._record.model = model

        client = AsyncOpenAI(
            api_key=self._api_key, base_url=self._base_url, timeout=self._timeout,
        )
        self._active_cache = (
            ToolCallCache(max_size=self._cache_size, ttl=self._cache_ttl)
            if self._cache_size > 0 else None
        )
        executor = ToolExecutor(
            self._registry, repair=self._repair,
            max_result_chars=self._max_result_chars,
            cache=self._active_cache,
            truncation_strategy=self._truncation_strategy,
        )

        tools_schema = self._registry.to_deepseek_tools(strict=self._strict)

        if self._strict and tools_schema:
            check_result = check_strict_compatibility(tools_schema)
            if not check_result.ok:
                if self._strict_fallback:
                    recorder.record("strict_fallback", {
                        "issues": [i.model_dump(mode="json") for i in check_result.issues],
                    })
                else:
                    raise StrictSchemaError(
                        f"Schema incompatible with strict mode: "
                        f"{check_result.issues[0].message}"
                    )

        working_messages = list(messages)
        tool_results: list = []
        reasoning_contents: list[str] = []

        for step in range(self._max_steps):
            working_messages = self._trim_messages(working_messages)

            recorder.record("model_request", {
                "step": step, "model": model,
                "message_count": len(working_messages),
                "tool_count": len(tools_schema),
            })

            params: dict = {"model": model, "messages": working_messages, **kwargs}
            if tools_schema:
                params["tools"] = tools_schema

            try:
                raw_response = await self._retry_request(
                    lambda: client.chat.completions.create(**params),
                    operation_name="chat_completion",
                )
            except CircuitBreakerOpenError:
                recorder.finish()
                self._last_messages = working_messages
                return ToolRuntimeResult(
                    final="Circuit breaker is open — requests are temporarily blocked.",
                    messages=working_messages,
                    circuit_breaker_open=True,
                    cache_stats=self._active_cache.stats if self._active_cache else None,
                    reasoning_contents=reasoning_contents,
                )

            choice = raw_response.choices[0]
            tool_calls = []
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    tool_calls.append(ToolCall(
                        id=tc.id, name=tc.function.name,
                        arguments=tc.function.arguments,
                    ))

            rc = getattr(choice.message, "reasoning_content", None)
            if isinstance(rc, str):
                reasoning_contents.append(rc)

            recorder.record("model_response", {
                "step": step,
                "finish_reason": choice.finish_reason,
                "has_content": choice.message.content is not None,
                "tool_call_count": len(tool_calls),
            })

            # Reasoning consistency check
            if rc and tool_calls:
                registered_names = [td.name for td in self._registry.list()]
                actual_names = [tc.name for tc in tool_calls]
                result = check_consistency(rc, actual_names, registered_names)
                if result.status == "MISMATCH":
                    recorder.record("reasoning_mismatch", {
                        "step": step,
                        "reasoning_mentions": result.reasoning_mentions,
                        "actual_calls": result.actual_calls,
                    })

            # No tool calls → done (with empty-content recovery)
            if not tool_calls:
                content = choice.message.content or ""
                if not content.strip() and step < self._max_steps - 1:
                    working_messages.append({
                        "role": "user",
                        "content": "Your last response was empty. Please provide an answer.",
                    })
                    continue

                assistant_msg: dict[str, Any] = {"role": "assistant", "content": content}
                if rc:
                    assistant_msg["reasoning_content"] = rc
                working_messages.append(assistant_msg)
                recorder.finish()
                self._last_messages = working_messages
                return ToolRuntimeResult(
                    final=content, messages=working_messages,
                    tool_results=tool_results,
                    trace=recorder,
                    usage={
                        "prompt_tokens": raw_response.usage.prompt_tokens,
                        "completion_tokens": raw_response.usage.completion_tokens,
                        "total_tokens": raw_response.usage.total_tokens,
                    } if raw_response.usage else None,
                    cache_stats=self._active_cache.stats if self._active_cache else None,
                    reasoning_contents=reasoning_contents,
                )

            # Build assistant message with tool_calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": choice.message.content,
                "tool_calls": [
                    {
                        "id": tc.id, "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in tool_calls
                ],
            }
            if rc:
                assistant_msg["reasoning_content"] = rc
            working_messages.append(assistant_msg)

            # Execute all tools in parallel
            for tc in tool_calls:
                recorder.record("tool_call_start", {
                    "step": step, "tool_call_id": tc.id, "name": tc.name,
                })

            batch_results = executor.execute_batch(tool_calls)
            for i, tc in enumerate(tool_calls):
                exec_result = batch_results[i]
                tool_results.append(exec_result)
                result_content = (
                    json.dumps(exec_result.result, ensure_ascii=False)
                    if exec_result.ok else f"Error: {exec_result.error}"
                )
                working_messages.append({
                    "role": "tool", "tool_call_id": tc.id, "content": result_content,
                })
                recorder.record(
                    "tool_call_result" if exec_result.ok else "tool_call_error",
                    {"step": step, "tool_call_id": tc.id, "name": tc.name,
                     "ok": exec_result.ok, "elapsed_ms": exec_result.elapsed_ms,
                     "repaired": exec_result.repaired, "error": exec_result.error},
                )

        recorder.finish()
        self._last_messages = working_messages
        return ToolRuntimeResult(
            final="Max steps reached",
            messages=working_messages,
            tool_results=tool_results,
            trace=recorder,
            cache_stats=self._active_cache.stats if self._active_cache else None,
            reasoning_contents=reasoning_contents,
        )

    # ── Streaming chat ──────────────────────────────────────────────

    async def chat_stream_async(
        self,
        *,
        model: str,
        messages: list[dict],
        files: list[str] | None = None,
        thinking_mode: str | None = None,
        response_format: str | None = None,
        **kwargs,
    ) -> AsyncIterator[StreamEvent]:
        kwargs = _apply_thinking_mode(thinking_mode, kwargs, messages=messages)
        if response_format:
            kwargs["response_format"] = {"type": response_format}

        if files:
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user":
                    messages[i] = embed_files_into_message(messages[i], files)
                    break

        self._connect_mcp()

        client = AsyncOpenAI(
            api_key=self._api_key, base_url=self._base_url, timeout=self._timeout,
        )
        executor = ToolExecutor(
            self._registry, repair=self._repair,
            max_result_chars=self._max_result_chars,
            truncation_strategy=self._truncation_strategy,
        )

        tools_schema = self._registry.to_deepseek_tools(strict=self._strict)
        working_messages = list(messages)
        reasoning_contents: list[str] = []

        for _step in range(self._max_steps):
            working_messages = self._trim_messages(working_messages)

            params: dict = {
                "model": model, "messages": working_messages,
                "stream": True, **kwargs,
            }
            if tools_schema:
                params["tools"] = tools_schema

            # Accumulate tool call deltas
            tool_call_buf: dict[int, dict] = {}
            current_content: list[str] = []
            step_reasoning: list[str] = []
            stream_usage: dict | None = None

            stream = await client.chat.completions.create(**params)
            async for event in stream:
                if hasattr(event, "usage") and event.usage is not None:
                    stream_usage = {
                        "prompt_tokens": event.usage.prompt_tokens,
                        "completion_tokens": event.usage.completion_tokens,
                        "total_tokens": event.usage.total_tokens,
                    }
                    continue

                delta = event.choices[0].delta if event.choices else None
                if delta is None:
                    continue

                rc = getattr(delta, "reasoning_content", None)
                if isinstance(rc, str) and rc:
                    reasoning_contents.append(rc)
                    step_reasoning.append(rc)
                    yield StreamEvent(type="reasoning", content=rc)

                if delta.content:
                    current_content.append(delta.content)
                    yield StreamEvent(type="content", content=delta.content)

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
                            if tc_delta.function.arguments:
                                buf["arguments"] += tc_delta.function.arguments

                if event.choices[0].finish_reason:
                    for buf in tool_call_buf.values():
                        yield StreamEvent(
                            type="tool_call_start",
                            tool_name=buf["name"],
                        )
                        tc = ToolCall(
                            id=buf["id"], name=buf["name"],
                            arguments=buf["arguments"],
                        )
                        exec_result = executor.execute(tc)
                        buf["_exec_result"] = exec_result
                        yield StreamEvent(
                            type="tool_call_result",
                            tool_name=buf["name"],
                            tool_result=exec_result.result if exec_result.ok else None,
                        )

            if not tool_call_buf:
                assistant_msg = {
                    "role": "assistant",
                    "content": "".join(current_content),
                }
                if step_reasoning:
                    assistant_msg["reasoning_content"] = "".join(step_reasoning)
                working_messages.append(assistant_msg)
                self._last_messages = working_messages
                yield StreamEvent(
                    type="done",
                    content="".join(current_content),
                    reasoning_content="".join(reasoning_contents) if reasoning_contents else None,
                    finish_reason="stop",
                    usage=stream_usage,
                )
                return

            # Build assistant + tool messages
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": "".join(current_content) if current_content else None,
                "tool_calls": [
                    {
                        "id": b["id"], "type": "function",
                        "function": {"name": b["name"], "arguments": b["arguments"]},
                    }
                    for b in tool_call_buf.values()
                ],
            }
            if step_reasoning:
                assistant_msg["reasoning_content"] = "".join(step_reasoning)
            working_messages.append(assistant_msg)

            for b in tool_call_buf.values():
                exec_result = b.get("_exec_result")
                if exec_result is None:
                    tc = ToolCall(id=b["id"], name=b["name"], arguments=b["arguments"])
                    exec_result = executor.execute(tc)
                result_content = (
                    json.dumps(exec_result.result, ensure_ascii=False)
                    if exec_result.ok else f"Error: {exec_result.error}"
                )
                working_messages.append({
                    "role": "tool", "tool_call_id": b["id"],
                    "content": result_content,
                })

        self._last_messages = working_messages
        yield StreamEvent(
            type="done",
            content="Max steps reached",
            finish_reason="max_steps",
            reasoning_content="".join(reasoning_contents) if reasoning_contents else None,
            usage=stream_usage,
        )

    # ── Cleanup ─────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Close all MCP server connections."""
        if self._mcp_executor is not None:
            self._mcp_executor.disconnect()
            self._mcp_executor = None
