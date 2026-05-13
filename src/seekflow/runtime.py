"""Minimal tool calling loop that wires together all modules."""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from seekflow.mcp.executor import MCPToolExecutor

from seekflow.batch_client import BatchClient, BatchTimeoutError
from seekflow.client import DeepSeekClient
from seekflow.errors import StrictSchemaError
from seekflow.files import embed_files_into_message
from seekflow.reasoning import check_consistency
from seekflow.retry import CircuitBreaker, RetryPolicy
from seekflow.retry_executor import CircuitBreakerOpenError, RetryExecutor
from seekflow.tool_cache import ToolCallCache
from seekflow.tools.executor import ToolExecutor
from seekflow.tools.registry import ToolRegistry
from seekflow.tools.strict import check_strict_compatibility
from seekflow.trace.recorder import TraceRecorder
from seekflow.truncation import TruncationStrategy
from seekflow.types import (
    ChatResponse,
    StreamEvent,
    ToolCall,
    ToolRuntimeResult,
)


class ToolRuntime:
    """Minimal tool calling loop — not a full agent framework."""

    def __init__(
        self,
        *,
        tools: list[Any] | None = None,
        mcp_servers: list[Any] | None = None,
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
        strict: bool = False,
        strict_fallback: bool = True,
        repair: bool = True,
        trace: bool = True,
        max_steps: int = 6,
        max_context_tokens: int | None = 64000,
        max_result_chars: int = 12000,
        timeout: float = 60.0,
        retry_policy: RetryPolicy | None = None,
        cache_size: int = 128,
        cache_ttl: float | None = None,
        truncation_strategy: TruncationStrategy = TruncationStrategy.JSON_AWARE,
    ):
        self._api_key = api_key
        self._base_url = base_url
        self._strict = strict
        self._strict_fallback = strict_fallback
        self._repair = repair
        self._trace_enabled = trace
        self._max_steps = max_steps
        self._max_context_tokens = max_context_tokens
        self._max_result_chars = max_result_chars
        self._timeout = timeout
        self._retry_policy = retry_policy if retry_policy is not None else RetryPolicy.default()
        self._circuit_breaker = CircuitBreaker(
            threshold=self._retry_policy.circuit_breaker_threshold,
            cooldown=self._retry_policy.cooldown,
        )
        self._cache_size = cache_size
        self._cache_ttl = cache_ttl
        self._truncation_strategy = truncation_strategy
        self._last_messages: list[dict[str, Any]] = []

        # Build tool registry
        self._registry = ToolRegistry()
        for t in (tools or []):
            self._registry.register(t)

        # MCP servers — connect on first use
        self._mcp_servers = mcp_servers or []
        self._mcp_connected = False
        self._mcp_executor: MCPToolExecutor | None = None
        self._client: RetryExecutor | None = None
        self._step_callback: Any = None
        self._active_cache: ToolCallCache | None = None

    def _connect_mcp_servers(self) -> None:
        """Connect to MCP servers and register their tools.

        Delegates to MCPToolExecutor for connection, discovery, and
        wrapper registration. Supports both mcp SDK and manual subprocess paths.
        """
        if self._mcp_connected or not self._mcp_servers:
            return
        from seekflow.mcp.executor import MCPToolExecutor
        self._mcp_executor = MCPToolExecutor(list(self._mcp_servers))
        self._mcp_executor.connect_and_register(self._registry)
        self._mcp_connected = True

    @property
    def circuit_breaker_state(self) -> str:
        return self._circuit_breaker.state.value

    @property
    def cache_stats(self) -> dict:
        if self._active_cache is None:
            return {"hits": 0, "misses": 0, "ratio": 0.0}
        return self._active_cache.stats

    def cleanup(self) -> None:
        """Close all MCP server connections and subprocesses."""
        if self._mcp_executor is not None:
            self._mcp_executor.disconnect()
            self._mcp_executor = None

    def _make_client(self, recorder: TraceRecorder) -> RetryExecutor:
        """Create a RetryExecutor wrapping DeepSeekClient with trace callback."""
        raw_client = DeepSeekClient(
            api_key=self._api_key, base_url=self._base_url, timeout=self._timeout
        )

        def on_retry_event(data: dict) -> None:
            recorder.record(data["type"], data)

        return RetryExecutor(
            raw_client,
            policy=self._retry_policy,
            circuit_breaker=self._circuit_breaker,
            on_retry=on_retry_event,
        )

    # ── context window management (delegates to _runtime_base) ──────

    def _trim_messages(self, messages: list[dict]) -> list[dict]:
        from seekflow._runtime_base import trim_messages
        return trim_messages(messages, self._max_context_tokens)

    def chat(
        self,
        *,
        model: str,
        messages: list[dict],
        files: list[str] | None = None,
        thinking_mode: str | None = None,
        response_format: str | None = None,
        **kwargs,
    ) -> ToolRuntimeResult:
        """Run the tool calling loop.

        Args:
            model: Model name.
            messages: List of message dicts with role/content.
            files: Optional list of file paths to attach. Content is embedded
                   into the last user message using DeepSeek's file template.
            thinking_mode: "disabled", "enabled", or "max". Maps to
                   extra_body={"thinking": {"type": ...}} automatically.
            response_format: "text" or "json_object". Passed directly to API.
            **kwargs: Passed to the underlying API call (e.g. temperature,
                      extra_body for additional options).
        """
        kwargs = _apply_thinking_mode(thinking_mode, kwargs, messages=messages)
        if response_format:
            kwargs["response_format"] = {"type": response_format}
        # Embed file content into messages
        if files:
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user":
                    messages[i] = embed_files_into_message(messages[i], files)
                    break

        self._connect_mcp_servers()

        recorder = TraceRecorder(enabled=self._trace_enabled)
        if self._trace_enabled:
            recorder._record.model = model

        client = self._client if self._client else self._make_client(recorder)
        self._active_cache = ToolCallCache(max_size=self._cache_size, ttl=self._cache_ttl) if self._cache_size > 0 else None
        executor = ToolExecutor(
            self._registry,
            repair=self._repair,
            max_result_chars=self._max_result_chars,
            cache=self._active_cache,
            truncation_strategy=self._truncation_strategy,
        )

        # Generate tools schema
        tools_schema = self._registry.to_deepseek_tools(strict=self._strict)

        # Strict compatibility check
        if self._strict and tools_schema:
            check_result = check_strict_compatibility(tools_schema)
            if not check_result.ok:
                if self._strict_fallback:
                    recorder.record("strict_fallback", {
                        "issues": [i.model_dump(mode="json") for i in check_result.issues],
                    })
                else:
                    recorder.finish()
                    raise StrictSchemaError(
                        f"Schema incompatible with strict mode: "
                        f"{check_result.issues[0].message}"
                    )

        working_messages = list(messages)
        tool_results: list = []
        reasoning_contents: list[str] = []
        cumulative_usage: dict[str, Any] = {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
            "prompt_tokens_details": {"cached_tokens": 0},
        }

        # Hybrid thinking mode: Step 1 uses thinking for planning,
        # subsequent steps disable thinking to avoid token bloat.
        # DeepSeek V3.1+ supports per-request thinking toggle via extra_body.
        # Track whether thinking was EVER used in this conversation.
        # Required for API contract: if any assistant message has reasoning_content,
        # ALL subsequent assistant messages must have it too.
        _thinking_was_used = (
            kwargs.get("extra_body", {}).get("thinking", {}).get("type") == "enabled"
        )
        _hybrid_thinking = _thinking_was_used
        _tool_call_rounds = 0
        _compressed_placeholder = "→thinking"

        for step in range(self._max_steps):
            # Trim context window before each API call
            working_messages = self._trim_messages(working_messages)

            # Call model
            recorder.record("model_request", {
                "step": step,
                "model": model,
                "message_count": len(working_messages),
                "tool_count": len(tools_schema),
            })

            try:
                response: ChatResponse = client.chat(
                    model=model,
                    messages=working_messages,
                    tools=tools_schema if tools_schema else None,
                    **kwargs,
                )
            except CircuitBreakerOpenError:
                recorder.finish()
                self._last_messages = working_messages
                return ToolRuntimeResult(
                    final="Circuit breaker is open — requests are temporarily blocked. "
                          "Please wait for the cooldown period to expire.",
                    messages=working_messages,
                    circuit_breaker_open=True,
                    cache_stats=self._active_cache.stats if self._active_cache else None,
                    reasoning_contents=reasoning_contents,
                )

            recorder.record("model_response", {
                "step": step,
                "finish_reason": response.finish_reason,
                "has_content": response.content is not None,
                "tool_call_count": len(response.tool_calls),
            })

            # Accumulate token usage across ALL steps (including cache)
            if response.usage:
                cumulative_usage["prompt_tokens"] += response.usage.get("prompt_tokens", 0)
                cumulative_usage["completion_tokens"] += response.usage.get("completion_tokens", 0)
                cumulative_usage["total_tokens"] += response.usage.get("total_tokens", 0)
                details = response.usage.get("prompt_tokens_details", {}) or {}
                cumulative_usage["prompt_tokens_details"]["cached_tokens"] += details.get("cached_tokens", 0)

            # Collect reasoning content + harvest structured insights
            if response.reasoning_content:
                reasoning_contents.append(response.reasoning_content)
                if response.tool_calls:
                    registered_names = [td.name for td in self._registry.list()]
                    actual_names = [tc.name for tc in response.tool_calls]
                    result = check_consistency(
                        response.reasoning_content, actual_names, registered_names
                    )
                    if result.status == "MISMATCH":
                        recorder.record("reasoning_mismatch", {
                            "step": step,
                            "reasoning_mentions": result.reasoning_mentions,
                            "actual_calls": result.actual_calls,
                            "reasoning_snippet": response.reasoning_content[:200],
                        })
                    # Save compressed reasoning as placeholder for subsequent steps
                    # where thinking is disabled but API requires reasoning_content.
                    _compressed_placeholder = _compress_reasoning(response.reasoning_content)
                    # Harvest structured thoughts for injection into next prompt.
                    # Only active when reasoning_content is present (thinking mode).
                    # Appended at END of message list — does not break cache prefix.
                    # Token cost: ~30-50 tokens per step, offset by better model guidance.
                    from seekflow.reasoning import harvest_thoughts
                    harvested = harvest_thoughts(response.reasoning_content)
                    if (not harvested.is_empty and step < self._max_steps - 1
                            and len(harvested.format_for_prompt()) > 20):
                        insight = harvested.format_for_prompt()
                        if insight:
                            working_messages.append({
                                "role": "user",
                                "content": f"[Reasoning Insights]\n{insight}",
                            })

            # No tool calls → done (with empty-content recovery)
            if not response.tool_calls:
                content = response.content or ""
                if not content.strip() and step < self._max_steps - 1:
                    # DeepSeek quirk: empty content. Retry once.
                    working_messages.append({
                        "role": "user",
                        "content": "Your last response was empty. Please provide an answer."
                    })
                    continue

                assistant_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": content,
                }
                if response.reasoning_content:
                    assistant_msg["reasoning_content"] = _compress_reasoning(
                        response.reasoning_content
                    )
                elif _thinking_was_used:
                    # API contract: if thinking was used earlier, every assistant
                    # message must have reasoning_content. DeepSeek strict check.
                    assistant_msg["reasoning_content"] = _compressed_placeholder
                working_messages.append(assistant_msg)
                recorder.finish()
                self._last_messages = working_messages
                return ToolRuntimeResult(
                    final=content,
                    messages=working_messages,
                    tool_results=tool_results,
                    trace=recorder if self._trace_enabled else None,
                    usage=dict(cumulative_usage),
                    cache_stats=self._active_cache.stats if self._active_cache else None,
                    reasoning_contents=reasoning_contents,
                    empty_content_retries=1 if not content.strip() else 0,
                )

            # Build assistant message with tool_calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": response.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in response.tool_calls
                ],
            }
            if response.reasoning_content:
                assistant_msg["reasoning_content"] = _compress_reasoning(
                    response.reasoning_content
                )
            elif _thinking_was_used:
                # API contract: if thinking was ever used, every assistant
                # message must have reasoning_content for DeepSeek compliance.
                assistant_msg["reasoning_content"] = _compressed_placeholder
            working_messages.append(assistant_msg)

            # Execute ALL tools in batch (MCP wrappers are now functional)
            for tc in response.tool_calls:
                recorder.record("tool_call_start", {
                    "step": step, "tool_call_id": tc.id, "name": tc.name,
                })

            if response.tool_calls:
                batch_results = executor.execute_batch(response.tool_calls)
                for i, tc in enumerate(response.tool_calls):
                    exec_result = batch_results[i]
                    tool_results.append(exec_result)
                    result_content = (
                        json.dumps(exec_result.result, ensure_ascii=False, separators=(",", ":"))
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

            # Hybrid thinking: after first tool-call round, switch thinking OFF.
            # DeepSeek V3.1+ V3.2 keeps reasoning context across tool calls,
            # so the model retains its plan without re-thinking every step.
            if _hybrid_thinking and _tool_call_rounds >= 1:
                extra = dict(kwargs.get("extra_body", {}))
                extra["thinking"] = {"type": "disabled"}
                kwargs["extra_body"] = extra
                _hybrid_thinking = False  # Only toggle once

            # Early-stop signal: inject reminder when approaching max_steps.
            steps_remaining = self._max_steps - step - 1
            if steps_remaining == 1 and response.tool_calls:
                working_messages.append({
                    "role": "user",
                    "content": (
                        "你只剩最后一轮回复机会了。请在下一轮中直接给出最终答案，"
                        "不要再调用新工具。基于已有数据进行最佳判断。"
                    ),
                })
            elif steps_remaining == 2 and len(response.tool_calls) > 0 and step >= 3:
                working_messages.append({
                    "role": "user",
                    "content": (
                        f"你还有 {steps_remaining} 轮回复机会。请评估已有数据是否足够，"
                        "如果基本够用，请在下一轮开始合成最终答案。"
                    ),
                })

        # Max steps exhausted
        recorder.finish()
        self._last_messages = working_messages
        return ToolRuntimeResult(
            final="ToolRuntime stopped because max_steps was reached.",
            messages=working_messages,
            tool_results=tool_results,
            trace=recorder if self._trace_enabled else None,
            usage=dict(cumulative_usage),
            cache_stats=self._active_cache.stats if self._active_cache else None,
            reasoning_contents=reasoning_contents,
        )

    def chat_stream(
        self,
        *,
        model: str,
        messages: list[dict],
        files: list[str] | None = None,
        thinking_mode: str | None = None,
        response_format: str | None = None,
        **kwargs,
    ) -> Iterator[StreamEvent]:
        """Run the tool calling loop in streaming mode.

        Yields StreamEvent objects as the model generates tokens.
        When tools are called, executes them and yields results,
        then continues streaming the follow-up response.

        Args:
            model: Model name.
            messages: List of message dicts with role/content.
            files: Optional list of file paths to attach.
            thinking_mode: "disabled", "enabled", or "max".
            response_format: "text" or "json_object".
            **kwargs: Passed to the underlying API call.
        """
        kwargs = _apply_thinking_mode(thinking_mode, kwargs, messages=messages)
        if response_format:
            kwargs["response_format"] = {"type": response_format}
        if files:
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].get("role") == "user":
                    messages[i] = embed_files_into_message(messages[i], files)
                    break

        self._connect_mcp_servers()

        executor = ToolExecutor(
            self._registry,
            repair=self._repair,
            max_result_chars=self._max_result_chars,
            truncation_strategy=self._truncation_strategy,
        )

        # Create a fresh recorder for retry trace events
        recorder = TraceRecorder(enabled=self._trace_enabled)
        client = self._client if self._client else self._make_client(recorder)

        tools_schema = self._registry.to_deepseek_tools(strict=self._strict)

        working_messages = list(messages)
        reasoning_contents: list[str] = []
        for _step in range(self._max_steps):
            # Trim context window before each API call
            working_messages = self._trim_messages(working_messages)

            # Accumulate tool calls from streaming
            pending_tool_calls: dict[str, dict] = {}
            current_content: list[str] = []
            step_reasoning: list[str] = []
            stream_usage: dict | None = None

            # Stream the model response
            try:
                stream_iter = client.chat_stream(
                    model=model,
                    messages=working_messages,
                    tools=tools_schema if tools_schema else None,
                    **kwargs,
                )
            except CircuitBreakerOpenError:
                self._last_messages = working_messages
                yield StreamEvent(
                    type="done",
                    content="Circuit breaker is open — requests are temporarily blocked.",
                    finish_reason="circuit_breaker_open",
                )
                return

            for chunk in stream_iter:
                if chunk.type == "usage" and chunk.usage:
                    stream_usage = chunk.usage
                    continue

                if chunk.type == "reasoning" and chunk.content:
                    reasoning_contents.append(chunk.content)
                    step_reasoning.append(chunk.content)
                    yield StreamEvent(type="reasoning", content=chunk.content)

                elif chunk.type == "content" and chunk.content:
                    current_content.append(chunk.content)
                    yield StreamEvent(type="content", content=chunk.content)

                elif chunk.type == "tool_call_start" and chunk.tool_call_id:
                    pending_tool_calls[chunk.tool_call_id] = {
                        "id": chunk.tool_call_id,
                        "name": chunk.tool_name or "",
                        "arguments": "",
                    }

                elif chunk.type == "tool_call_delta" and chunk.tool_call_id:
                    if chunk.tool_call_id in pending_tool_calls:
                        pending_tool_calls[chunk.tool_call_id]["arguments"] += (
                            chunk.arguments_delta or ""
                        )

                elif chunk.type == "tool_call_end" and chunk.tool_call_id:
                    if chunk.tool_call_id in pending_tool_calls:
                        tc = pending_tool_calls[chunk.tool_call_id]
                        yield StreamEvent(
                            type="tool_call_start",
                            tool_name=tc["name"],
                        )

                        # Execute the tool ONCE, store result for reuse
                        raw_args = tc["arguments"]
                        try:
                            parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                        except json.JSONDecodeError:
                            parsed_args = {}
                        tool_call = ToolCall(
                            id=tc["id"],
                            name=tc["name"],
                            arguments=parsed_args,
                        )
                        exec_result = executor.execute(tool_call)
                        tc["_exec_result"] = exec_result  # cache for post-loop

                        yield StreamEvent(
                            type="tool_call_result",
                            tool_name=tc["name"],
                            tool_result=exec_result.result if exec_result.ok else None,
                        )

            # If no tool calls were made, we're done
            if not pending_tool_calls:
                final_content = "".join(current_content)
                assistant_msg = {"role": "assistant", "content": final_content}
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

            # Build assistant message with tool calls
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": "".join(current_content) if current_content else None,
                "tool_calls": [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"],
                        },
                    }
                    for tc in pending_tool_calls.values()
                ],
            }
            if step_reasoning:
                assistant_msg["reasoning_content"] = "".join(step_reasoning)
            working_messages.append(assistant_msg)

            # Build tool result messages from cached execution results
            for tc_data in pending_tool_calls.values():
                exec_result = tc_data.get("_exec_result")
                if exec_result is None:
                    # Fallback: execute if not cached (shouldn't happen)
                    raw_args = tc_data["arguments"]
                    try:
                        parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        parsed_args = {}
                    tool_call = ToolCall(
                        id=tc_data["id"], name=tc_data["name"],
                        arguments=parsed_args,
                    )
                    exec_result = executor.execute(tool_call)

                if exec_result.ok:
                    result_content = json.dumps(exec_result.result, ensure_ascii=False)
                else:
                    result_content = f"Error: {exec_result.error}"

                working_messages.append({
                    "role": "tool",
                    "tool_call_id": tc_data["id"],
                    "content": result_content,
                })

            # Clear for next iteration
            pending_tool_calls.clear()

        self._last_messages = working_messages
        yield StreamEvent(
            type="done",
            content="ToolRuntime stopped: max_steps reached.",
            finish_reason="max_steps",
            reasoning_content="".join(reasoning_contents) if reasoning_contents else None,
            usage=stream_usage,
        )

    # ------------------------------------------------------------------
    # Batch API
    # ------------------------------------------------------------------

    def chat_batch(
        self,
        *,
        model: str,
        requests: list[dict],
        poll_interval: float = 30.0,
        max_wait: float = 3600.0,
    ) -> list[ToolRuntimeResult]:
        """Submit multiple chat requests via Batch API and collect results.

        Each request dict should have ``messages`` and optionally ``tools``.
        Results include local tool execution for any tool calls returned.
        Only single-step: tool results are NOT sent back to the model.

        Args:
            model: Model name to use for all requests.
            requests: List of dicts, each with ``messages`` and optional ``tools``.
            poll_interval: Seconds between batch status checks.
            max_wait: Maximum seconds to wait for batch completion.

        Returns:
            List of ToolRuntimeResult, one per request, in the same order.
        """
        tools_schema = self._registry.to_deepseek_tools(strict=self._strict)

        # Build batch requests with tools
        batch_requests = []
        for i, req in enumerate(requests):
            body = {
                "model": model,
                "messages": req["messages"],
            }
            if "tools" in req and req["tools"]:
                body["tools"] = req["tools"]
            elif tools_schema:
                body["tools"] = tools_schema
            batch_requests.append({
                "custom_id": f"req-{i}",
                "body": body,
            })

        # Submit, poll, download
        from seekflow.client import DeepSeekClient
        if self._client is not None:
            if isinstance(self._client, DeepSeekClient):
                raw_client = self._client
            elif hasattr(self._client, '_client'):
                raw_client = self._client._client
            else:
                raw_client = self._client
        else:
            raw_client = DeepSeekClient(
                api_key=self._api_key, base_url=self._base_url, timeout=self._timeout
            )
        batch_client = BatchClient(raw_client, poll_interval=poll_interval)

        try:
            batch_id = batch_client.submit_batch(batch_requests)
            status, _ = batch_client.poll_batch(
                batch_id, poll_interval=poll_interval, max_wait=max_wait
            )
        except BatchTimeoutError:
            raise

        if status != "completed":
            return [ToolRuntimeResult(
                final=f"Batch {batch_id} ended with status: {status}",
                messages=req.get("messages", []),
            ) for req in requests]

        batch_results = batch_client.download_results(batch_id)

        # Map results by custom_id -> request index
        by_custom_id = {}
        for br in batch_results:
            by_custom_id[br["custom_id"]] = br

        # Assemble ToolRuntimeResult for each request
        results: list[ToolRuntimeResult] = []
        for i, req in enumerate(requests):
            br = by_custom_id.get(f"req-{i}")
            if br is None:
                results.append(ToolRuntimeResult(
                    final=f"Batch result missing for request {i}",
                    messages=req.get("messages", []),
                ))
                continue

            if br["error"]:
                error_msg = str(br["error"])
                results.append(ToolRuntimeResult(
                    final=f"Batch API error: {error_msg}",
                    messages=req.get("messages", []),
                ))
                continue

            response_body = br["response"]
            if response_body is None:
                results.append(ToolRuntimeResult(
                    final="",
                    messages=req.get("messages", []),
                ))
                continue

            choice = response_body.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = message.get("content")
            tool_calls_data = message.get("tool_calls")
            finish_reason = choice.get("finish_reason")

            # Execute tool calls locally if present
            tool_results = []
            if tool_calls_data:
                executor = ToolExecutor(
                    self._registry,
                    repair=self._repair,
                    max_result_chars=self._max_result_chars,
                    truncation_strategy=self._truncation_strategy,
                )
                for tc_data in tool_calls_data:
                    func_info = tc_data.get("function", {})
                    raw_args = func_info.get("arguments", "{}")
                    try:
                        parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    except json.JSONDecodeError:
                        parsed_args = {}
                    tool_call = ToolCall(
                        id=tc_data.get("id"),
                        name=func_info.get("name", ""),
                        arguments=parsed_args,
                    )
                    exec_result = executor.execute(tool_call)
                    tool_results.append(exec_result)
                    if exec_result.ok:
                        content = str(exec_result.result)

            results.append(ToolRuntimeResult(
                final=content or "",
                messages=req.get("messages", []),
                tool_results=tool_results,
            ))

        return results


def _apply_thinking_mode(
    thinking_mode: str | None,
    kwargs: dict,
    messages: list[dict] | None = None,
) -> dict:
    """Convert thinking_mode parameter to extra_body format.

    When thinking_mode is not set (None), the default depends on the conversation:
    - Single-turn (no tool messages): "enabled"
    - Multi-turn (has tool messages): "disabled" (with UserWarning)

    When thinking_mode is explicitly set, the user's choice is always respected.
    """
    import copy
    import warnings

    kwargs = copy.copy(kwargs)
    extra_body = dict(kwargs.get("extra_body", {}) or {})

    if thinking_mode is None:
        is_multi_turn = bool(messages) and any(
            m.get("role") == "tool" for m in messages
        )
        if is_multi_turn:
            thinking_mode = "disabled"
            warnings.warn(
                "thinking_mode automatically set to 'disabled' for multi-turn "
                "conversation. DeepSeek requires reasoning_content to be passed "
                "back in every assistant message during multi-turn — set "
                "thinking_mode='enabled' explicitly if you handle this yourself.",
                UserWarning,
                stacklevel=3,
            )
        else:
            thinking_mode = "enabled"

    if "thinking" in extra_body:
        import logging
        logging.getLogger("seekflow").warning(
            "thinking_mode=%r overrides extra_body['thinking']=%r",
            thinking_mode, extra_body["thinking"],
        )

    think_config: dict[str, Any] = {"type": thinking_mode}
    # Cap reasoning budget: 512 tokens is enough for planning, keeps cost minimal.
    # At ¥0.28/1M output, 512 reasoning tokens cost ~¥0.00014 per step.
    if thinking_mode == "enabled":
        think_config["budget_tokens"] = 512
    extra_body["thinking"] = think_config
    kwargs["extra_body"] = extra_body
    return kwargs


def _compress_reasoning(reasoning: str, max_chars: int = 80) -> str:
    """Ultra-compact reasoning summary — target ~20-40 tokens.

    DeepSeek requires reasoning_content in every assistant message during
    multi-turn conversations. But passing back the full 400-800 token
    reasoning chain inflates prompt tokens and hurts cache hit rate
    (non-deterministic content breaks byte-prefix matching).

    This compressor extracts only the essential decision skeleton:
    planned tools + 1 key insight. Output is ~20-40 tokens — small enough
    to minimize prompt inflation and deterministic enough to preserve
    cache stability across calls.
    """
    if not reasoning:
        return ""
    if len(reasoning) <= max_chars:
        return reasoning

    import re

    # Extract tool names — match both English function calls and Chinese mentions
    tool_words = re.findall(
        r'\b([a-z_]{3,30})\b',
        reasoning[:800], re.IGNORECASE,
    )
    # Common English words to exclude
    stop = {'the', 'and', 'for', 'that', 'this', 'with', 'from', 'have', 'will',
            'need', 'should', 'would', 'could', 'about', 'what', 'when', 'where',
            'which', 'their', 'them', 'then', 'than', 'also', 'just', 'like',
            'some', 'more', 'most', 'only', 'over', 'into', 'been', 'being'}
    unique_tools = list(dict.fromkeys(
        t for t in tool_words if t not in stop and len(t) > 3
    ))[:5]

    # Extract ONE key numeric — deterministic signal
    key_num = re.search(r'(\d+\.?\d*%?)\s*(?:is|was|shows|indicates|为|是|显示|得到|计算)', reasoning[:600])
    key_finding = f" {key_num.group(1)}" if key_num else ""

    if unique_tools:
        plan = ",".join(unique_tools[:4])
        return f"→{plan}{key_finding}"
    # Fallback: ultra-short
    return f"→analyze{key_finding}" if key_finding else "→thinking"
