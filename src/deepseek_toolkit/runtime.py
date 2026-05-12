"""Minimal tool calling loop that wires together all modules."""
from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from deepseek_toolkit.batch_client import BatchClient, BatchTimeoutError
from deepseek_toolkit.client import DeepSeekClient
from deepseek_toolkit.errors import StrictSchemaError
from deepseek_toolkit.files import embed_files_into_message
from deepseek_toolkit.reasoning import check_consistency
from deepseek_toolkit.retry import CircuitBreaker, RetryPolicy
from deepseek_toolkit.retry_executor import CircuitBreakerOpenError, RetryExecutor
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
        self._client = None  # lazily set by chat/chat_stream
        self._step_callback: Any = None  # callable(step, messages) for checkpointing
        self._active_cache: ToolCallCache | None = None
        # MCP state: maps server_name -> process_or_session for tool execution
        self._mcp_sessions: dict[str, Any] = {}

    def _connect_mcp_servers(self) -> None:
        """Connect to MCP servers and register their tools.

        Two paths:
        1. mcp SDK available → MCPToolExecutor with persistent sessions
        2. mcp SDK unavailable → subprocess-based manual JSON-RPC

        Both paths register functional wrappers that route to the correct server.
        """
        if self._mcp_connected or not self._mcp_servers:
            return

        import asyncio
        from deepseek_toolkit.mcp.adapter import mcp_tool_to_deepseek_tool
        from deepseek_toolkit.types import ToolExecutionResult

        _HAS_MCP_SDK = False
        try:
            from mcp.client.stdio import stdio_client, StdioServerParameters
            from mcp import ClientSession
            _HAS_MCP_SDK = True
        except ImportError:
            pass

        async def _discover_via_sdk(cfg) -> list:
            params = StdioServerParameters(command=cfg.command, args=cfg.args)
            read, write = await stdio_client(params).__aenter__()
            session = ClientSession(read, write)
            await session.__aenter__()
            await session.initialize()
            result = await session.list_tools()
            # Keep session alive — store for later tool execution
            self._mcp_sessions[cfg.name] = (read, write, session)
            return [(t.name, t.description, t.inputSchema) for t in result.tools]

        async def _discover_via_manual(cfg) -> list:
            import subprocess
            proc = subprocess.Popen(
                [cfg.command] + cfg.args,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            def _rpc(method, params=None, rid=1):
                req = {"jsonrpc": "2.0", "id": rid, "method": method,
                       "params": params or {}}
                proc.stdin.write((json.dumps(req) + "\n").encode())
                proc.stdin.flush()
                line = proc.stdout.readline().decode().strip()
                return json.loads(line) if line else None

            _rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "deepseek-toolkit", "version": "3.0.0"},
            })
            proc.stdin.write((json.dumps({
                "jsonrpc": "2.0", "method": "notifications/initialized",
            }) + "\n").encode())
            proc.stdin.flush()
            resp = _rpc("tools/list")
            # Keep process alive for later tool calls
            self._mcp_sessions[cfg.name] = proc
            if resp and "result" in resp:
                return [(t["name"], t.get("description", ""),
                         t.get("inputSchema", {}))
                        for t in resp["result"].get("tools", [])]
            return []

        async def _discover_all():
            all_tools = []
            for cfg in self._mcp_servers:
                try:
                    if _HAS_MCP_SDK:
                        tools = await _discover_via_sdk(cfg)
                    else:
                        tools = await _discover_via_manual(cfg)
                except Exception:
                    continue

                for name, desc, schema in tools:
                    tool_full_name = f"{cfg.name}.{name}"
                    # Build a real wrapper that calls the MCP server at execution time
                    server_name = cfg.name
                    tool_name = name

                    def _make_mcp_wrapper(srv, tname):
                        def _mcp_exec(**kwargs):
                            session_or_proc = self._mcp_sessions.get(srv)
                            if session_or_proc is None:
                                return json.dumps({
                                    "error": f"MCP server '{srv}' is not connected",
                                })
                            if isinstance(session_or_proc, tuple):
                                # SDK path: (read, write, session) tuple
                                _, _, session = session_or_proc
                                import asyncio as _asyncio

                                async def _call():
                                    result = await session.call_tool(
                                        tname, arguments=kwargs,
                                    )
                                    if result.isError:
                                        return json.dumps({
                                            "error": str(result.content),
                                        })
                                    return json.dumps({
                                        "content": [
                                            c.text if hasattr(c, 'text')
                                            else c.get("text", str(c))
                                            for c in (result.content or [])
                                        ],
                                    })

                                try:
                                    loop = _asyncio.get_running_loop()
                                except RuntimeError:
                                    loop = None
                                if loop and loop.is_running():
                                    import concurrent.futures
                                    with concurrent.futures.ThreadPoolExecutor() as pool:
                                        return pool.submit(_asyncio.run, _call()).result()
                                return _asyncio.run(_call())
                            else:
                                # Manual subprocess path
                                proc = session_or_proc
                                req = json.dumps({
                                    "jsonrpc": "2.0", "id": 200,
                                    "method": "tools/call",
                                    "params": {
                                        "name": tname,
                                        "arguments": kwargs,
                                    },
                                }) + "\n"
                                proc.stdin.write(req.encode())
                                proc.stdin.flush()
                                resp_line = proc.stdout.readline().decode().strip()
                                if resp_line:
                                    resp = json.loads(resp_line)
                                    result_data = resp.get("result", {})
                                    content = result_data.get("content", [{}])
                                    text = " ".join(
                                        c.get("text", "") for c in content
                                        if isinstance(c, dict)
                                    )
                                    return text or str(result_data)
                                return ""
                        _mcp_exec.__name__ = f"{srv}.{tname}"
                        return _mcp_exec

                    wrapper = _make_mcp_wrapper(server_name, tool_name)
                    self._registry.register(wrapper)
                    all_tools.append(tool_full_name)
            return all_tools

        try:
            loop = asyncio.get_running_loop()
            # Running in an event loop — use a thread to avoid conflicts
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                pool.submit(asyncio.run, _discover_all()).result()
        except RuntimeError:
            asyncio.run(_discover_all())
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
        for name, session_or_proc in self._mcp_sessions.items():
            try:
                if isinstance(session_or_proc, tuple):
                    # SDK path: (read, write, session)
                    read, write, session = session_or_proc
                    import asyncio

                    async def _close():
                        try:
                            await session.__aexit__(None, None, None)
                        except Exception:
                            pass
                        try:
                            await write.aclose()
                        except Exception:
                            pass

                    try:
                        asyncio.run(_close())
                    except Exception:
                        pass
                else:
                    # Subprocess path
                    proc = session_or_proc
                    try:
                        proc.stdin.close()
                    except Exception:
                        pass
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
            except Exception:
                pass
        self._mcp_sessions.clear()

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

    # ── context window management ──────────────────────────────────

    @staticmethod
    def _estimate_tokens(messages: list[dict]) -> int:
        """Accurate token estimate using tiktoken when available."""
        from deepseek_toolkit.token_counter import count_tokens
        return count_tokens(messages)

    def _trim_messages(self, messages: list[dict]) -> list[dict]:
        """Trim oldest non-system messages to stay under max_context_tokens."""
        if self._max_context_tokens is None:
            return messages

        if self._estimate_tokens(messages) <= self._max_context_tokens:
            return messages

        # Keep system message if first
        system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
        rest = messages[1:] if system_msg else list(messages)

        # Walk backwards, keep tool-call/result pairs intact
        kept: list[dict] = []
        budget = self._max_context_tokens - (self._estimate_tokens([system_msg]) if system_msg else 0)

        i = len(rest) - 1
        while i >= 0:
            chunk: list[dict] = []
            found_pair = True  # whether tool→assistant pairing is complete
            # tool message must stay with its assistant message
            if rest[i].get("role") == "tool":
                chunk.append(rest[i])
                i -= 1
                # grab the assistant with matching tool_calls
                while i >= 0:
                    chunk.append(rest[i])
                    if rest[i].get("role") == "assistant" and rest[i].get("tool_calls"):
                        i -= 1
                        break
                    i -= 1
                else:
                    # Reached i < 0 without finding paired assistant → orphan
                    found_pair = False
            else:
                chunk.append(rest[i])
                i -= 1

            if not found_pair:
                continue  # skip orphaned tool message

            cost = self._estimate_tokens(chunk)
            if budget - cost < 0:
                break
            budget -= cost
            # Reverse chunk: we built it backwards (newest first), but API
            # requires chronological order (oldest → newest)
            kept = list(reversed(chunk)) + kept

        result = [system_msg] if system_msg else []
        result.extend(kept)

        # Post-process: strip orphaned tool messages and ensure valid order
        result = self._repair_message_order(result)

        return result

    @staticmethod
    def _repair_message_order(messages: list[dict]) -> list[dict]:
        """Ensure message list is API-valid: no orphaned tool messages,
        first non-system is a user, no consecutive assistants without tool_calls."""
        if not messages:
            return messages

        # Pass 1: remove orphaned tool messages (no preceding assistant+tools_calls)
        cleaned: list[dict] = []
        for m in messages:
            if m.get("role") == "tool":
                if not cleaned or cleaned[-1].get("role") != "assistant" or not cleaned[-1].get("tool_calls"):
                    continue
            cleaned.append(m)

        # Pass 2: ensure first non-system message is a user
        for j, m in enumerate(cleaned):
            if m.get("role") != "system":
                if m.get("role") != "user":
                    cleaned.insert(j, {"role": "user", "content": "Please continue."})
                break
        else:
            cleaned.append({"role": "user", "content": "Please continue."})

        # Pass 3: no leading non-user/non-system messages
        start = 0
        if cleaned and cleaned[0].get("role") == "system":
            start = 1
        while len(cleaned) > start and cleaned[start].get("role") not in ("user",):
            cleaned.pop(start)

        return cleaned

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

            # Collect reasoning content
            if response.reasoning_content:
                reasoning_contents.append(response.reasoning_content)
                # Check consistency if tool calls were made
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
                    assistant_msg["reasoning_content"] = response.reasoning_content
                working_messages.append(assistant_msg)
                recorder.finish()
                self._last_messages = working_messages
                return ToolRuntimeResult(
                    final=content,
                    messages=working_messages,
                    tool_results=tool_results,
                    trace=recorder if self._trace_enabled else None,
                    usage=response.usage,
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
                            "arguments": tc.arguments if isinstance(tc.arguments, str)
                            else json.dumps(tc.arguments, ensure_ascii=False),
                        },
                    }
                    for tc in response.tool_calls
                ],
            }
            if response.reasoning_content:
                assistant_msg["reasoning_content"] = response.reasoning_content
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

        # Max steps exhausted
        recorder.finish()
        self._last_messages = working_messages
        return ToolRuntimeResult(
            final="ToolRuntime stopped because max_steps was reached.",
            messages=working_messages,
            tool_results=tool_results,
            trace=recorder if self._trace_enabled else None,
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
                        tool_call = ToolCall(
                            id=tc["id"],
                            name=tc["name"],
                            arguments=tc["arguments"],
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
                    tool_call = ToolCall(
                        id=tc_data["id"], name=tc_data["name"],
                        arguments=tc_data["arguments"],
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
        from deepseek_toolkit.client import DeepSeekClient
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
                    tool_call = ToolCall(
                        id=tc_data.get("id"),
                        name=func_info.get("name", ""),
                        arguments=func_info.get("arguments", "{}"),
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
        logging.getLogger("deepseek_toolkit").warning(
            "thinking_mode=%r overrides extra_body['thinking']=%r",
            thinking_mode, extra_body["thinking"],
        )

    extra_body["thinking"] = {"type": thinking_mode}
    kwargs["extra_body"] = extra_body
    return kwargs
