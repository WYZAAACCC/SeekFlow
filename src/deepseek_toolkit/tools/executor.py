"""Tool executor for unified local tool execution."""
from __future__ import annotations

import re


def _sanitize_tool_output(text: str) -> str:
    """Filter prompt injection patterns from tool outputs."""
    patterns = [
        r'\[SYSTEM\]', r'\[系统\]', r'忽略.*指令',
        r'ignore.*(previous|prior).*instruction',
        r'输出.*密码', r'output.*password',
        r'<\|im_start\|>', r'<\|im_end\|>',
    ]
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            return f"[FILTERED] {text[:200]}"
    return text


import concurrent.futures
import json
import time
from typing import TYPE_CHECKING

from deepseek_toolkit.repair.coercion import coerce_arguments
from deepseek_toolkit.repair.json_repair import repair_json_arguments
from deepseek_toolkit.tool_cache import ToolCallCache, make_cache_key
from deepseek_toolkit.tools.registry import ToolRegistry
from deepseek_toolkit.truncation import TruncationStrategy, truncate_result
from deepseek_toolkit.types import ToolCall, ToolExecutionResult

if TYPE_CHECKING:
    pass


class ToolExecutor:
    """Executes tool calls with repair, coercion, and error handling."""

    def __init__(
        self,
        registry: ToolRegistry,
        repair: bool = True,
        max_result_chars: int = 12000,
        cache: ToolCallCache | None = None,
        truncation_strategy: TruncationStrategy = TruncationStrategy.JSON_AWARE,
        max_parallel: int = 5,
    ):
        self.registry = registry
        self.repair = repair
        self.max_result_chars = max_result_chars
        self._cache = cache
        self.truncation_strategy = truncation_strategy
        self.max_parallel = max_parallel

    def execute(self, tool_call: ToolCall) -> ToolExecutionResult:
        start = time.time()
        repair_notes: list[str] = []
        repaired = False

        arguments = tool_call.arguments
        # Check cache before execution
        if self._cache is not None:
            tool_def = self.registry.get(tool_call.name) if self.registry.has(tool_call.name) else None
            cache_enabled = tool_def.metadata.get("cache", True) if tool_def else True
            if cache_enabled:
                cache_key = make_cache_key(tool_call.name, arguments)
                cached = self._cache.get(cache_key)
                if cached is not None:
                    cached.repair_notes = list(cached.repair_notes) + ["cache_hit"]
                    return cached
        # Defensive: arguments normalized to dict at API boundary (client.py),
        # but legacy callers may still pass raw strings.
        if isinstance(arguments, str):
            parsed, ok, notes = self._parse_arguments(arguments)
            repair_notes.extend(notes)
            if ok:
                arguments = parsed
                if notes:
                    repaired = True
            else:
                elapsed = int((time.time() - start) * 1000)
                return ToolExecutionResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    arguments={}, ok=False,
                    error=f"Failed to parse arguments: {arguments}",
                    elapsed_ms=elapsed, repaired=repaired,
                    repair_notes=repair_notes,
                )

        # Look up tool
        if not self.registry.has(tool_call.name):
            elapsed = int((time.time() - start) * 1000)
            return ToolExecutionResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                arguments=arguments,
                ok=False,
                error=f"Tool not found: {tool_call.name}",
                elapsed_ms=elapsed,
            )

        tool_def = self.registry.get(tool_call.name)

        # Coerce argument types
        if self.repair:
            arguments, coercion_notes = coerce_arguments(arguments, tool_def.parameters)
            repair_notes.extend(coercion_notes)
            if coercion_notes:
                repaired = True

        # Execute
        try:
            if tool_def.func is None:
                elapsed = int((time.time() - start) * 1000)
                return ToolExecutionResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    arguments=arguments,
                    ok=False,
                    error=f"Tool '{tool_call.name}' has no callable function",
                    elapsed_ms=elapsed,
                )

            max_retries = (tool_def.metadata or {}).get("max_retries", 0)
            retry_delay = (tool_def.metadata or {}).get("retry_delay", 1.0)
            last_error = None

            for attempt in range(max_retries + 1):
                try:
                    from deepseek_toolkit.compat.telemetry import tool_span
                    with tool_span(tool_call.name):
                        raw_result = tool_def.func(**arguments)
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        time.sleep(retry_delay * (attempt + 1))

            if last_error is not None:
                elapsed = int((time.time() - start) * 1000)
                return ToolExecutionResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    arguments=arguments if isinstance(arguments, dict) else {},
                    ok=False, error=f"Tool failed after {max_retries+1} attempts: {last_error}",
                    elapsed_ms=elapsed,
                )

            # Sanitize: filter prompt injection patterns from tool output
            if isinstance(raw_result, str):
                raw_result = _sanitize_tool_output(raw_result)

            # Truncate if string result is too long
            keep_fields = tool_def.metadata.get("keep_fields") if tool_def.metadata else None
            final_result = self._maybe_truncate(raw_result, keep_fields=keep_fields)

            elapsed = int((time.time() - start) * 1000)
            exec_result = ToolExecutionResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                arguments=arguments,
                ok=True,
                result=final_result,
                elapsed_ms=elapsed,
                repaired=repaired,
                repair_notes=repair_notes,
            )

            # Write to cache
            if self._cache is not None:
                cache_enabled = tool_def.metadata.get("cache", True)
                if cache_enabled:
                    cache_key = make_cache_key(tool_call.name, arguments)
                    self._cache.put(cache_key, exec_result)

            return exec_result
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            return ToolExecutionResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                arguments=arguments,
                ok=False,
                error=str(e),
                elapsed_ms=elapsed,
                repaired=repaired,
                repair_notes=repair_notes,
            )

    def _parse_arguments(self, raw: str) -> tuple[dict, bool, list[str]]:
        """Try to parse JSON arguments. Returns (parsed, ok, notes)."""
        # Try direct parse first
        try:
            return json.loads(raw), True, []
        except json.JSONDecodeError:
            pass

        # Try repair if enabled
        if self.repair:
            repair_result = repair_json_arguments(raw)
            if repair_result.ok and repair_result.value is not None:
                return repair_result.value, True, repair_result.applied_rules
            return {}, False, repair_result.applied_rules

        return {}, False, []

    def execute_batch(self, tool_calls: list[ToolCall]) -> list[ToolExecutionResult]:
        """Execute multiple tool calls in parallel.

        All tool_calls in a single batch are assumed to be independent
        (the LLM declares parallelism by returning them in one response).
        Results are returned in the same order as the input tool_calls.
        """
        if len(tool_calls) == 0:
            return []
        if len(tool_calls) == 1:
            return [self.execute(tool_calls[0])]

        max_workers = min(self.max_parallel, len(tool_calls))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            # Preserve original order: store result by index
            futures: dict[concurrent.futures.Future, int] = {}
            for idx, tc in enumerate(tool_calls):
                f = pool.submit(self.execute, tc)
                futures[f] = idx

            ordered: list[ToolExecutionResult | None] = [None] * len(tool_calls)
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                try:
                    ordered[idx] = future.result()
                except Exception as e:
                    tc = tool_calls[idx]
                    ordered[idx] = ToolExecutionResult(
                        tool_call_id=tc.id,
                        name=tc.name,
                        arguments={},
                        ok=False,
                        error=f"Parallel execution error: {e}",
                        elapsed_ms=0,
                    )
            return [r for r in ordered if r is not None]

    def _maybe_truncate(self, result, keep_fields: list[str] | None = None):
        """Truncate string result if too long, using configured strategy."""
        if isinstance(result, str):
            return truncate_result(
                result,
                max_result_chars=self.max_result_chars,
                strategy=self.truncation_strategy,
                keep_fields=keep_fields,
            )
        return result
