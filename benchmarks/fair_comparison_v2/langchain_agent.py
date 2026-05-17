"""LangChain agent — identical tools, prompts, task as SeekFlow.

Uses langchain-openai with ChatOpenAI + create_agent (LangGraph agent).
Model: deepseek-v4-flash (same as SeekFlow).
"""
from __future__ import annotations

import os
import time

from benchmarks.fair_comparison_v2.shared_tools import (
    SHARED_TOOLS, SYSTEM_PROMPTS, TASKS,
)
from benchmarks.fair_comparison_v2.seekflow_agents import AgentRunResult

MODEL = "deepseek-v4-pro"

# v4-pro pricing: (input, cached_input, output) per 1M tokens
COST_INPUT = 1.74 / 1_000_000
COST_CACHED = 0.028 / 1_000_000
COST_OUTPUT = 3.48 / 1_000_000


def _wrap_for_langchain(fn):
    """Wrap a function as a LangChain StructuredTool with proper schema."""
    from langchain_core.tools import StructuredTool
    import inspect

    sig = inspect.signature(fn)
    # Build a simple description from docstring
    desc = (fn.__doc__ or fn.__name__).split("\n")[0].strip()

    return StructuredTool.from_function(
        func=fn,
        name=fn.__name__,
        description=desc,
    )


def run_langchain(api_key: str, scenario: str) -> AgentRunResult:
    """LangChain agent with shared tools, prompts, and task."""
    from langchain_openai import ChatOpenAI
    from langchain.agents import create_agent as langgraph_create_agent

    lc_tools = [_wrap_for_langchain(t) for t in SHARED_TOOLS]

    llm = ChatOpenAI(
        model=MODEL,
        api_key=api_key,
        base_url="https://api.deepseek.com/v1",
        temperature=0.0,
        request_timeout=120,
        model_kwargs={"extra_body": {"thinking": {"type": "disabled"}}},
    )

    agent = langgraph_create_agent(
        model=llm,
        tools=lc_tools,
        system_prompt=SYSTEM_PROMPTS[scenario],
    )

    start = time.perf_counter()
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": TASKS[scenario]}]},
            config={"recursion_limit": 15},
        )
        elapsed = time.perf_counter() - start

        messages = result.get("messages", [])

        # Extract final output — last AI message with content, no tool_calls
        final_output = ""
        for m in reversed(messages):
            content = getattr(m, "content", None)
            if isinstance(content, str) and len(content) > 100:
                tc = getattr(m, "tool_calls", None)
                if not tc:
                    final_output = content
                    break

        # Accumulate token usage across ALL AI messages
        prompt_tokens = 0
        completion_tokens = 0
        cached_tokens = 0
        for m in messages:
            um = getattr(m, "usage_metadata", None)
            if um and isinstance(um, dict):
                prompt_tokens += um.get("input_tokens", 0)
                completion_tokens += um.get("output_tokens", 0)
                details = um.get("input_token_details", {}) or {}
                cached_tokens += details.get("cache_read", 0)
            elif hasattr(m, "response_metadata"):
                rm = m.response_metadata
                if isinstance(rm, dict):
                    um2 = rm.get("token_usage", rm.get("usage_metadata", {}))
                    if um2 and isinstance(um2, dict):
                        prompt_tokens += um2.get("prompt_tokens", um2.get("input_tokens", 0))
                        completion_tokens += um2.get("completion_tokens", um2.get("output_tokens", 0))
                        details2 = um2.get("prompt_tokens_details", {}) or {}
                        cached_tokens += details2.get("cached_tokens", 0)

        total_tokens = prompt_tokens + completion_tokens

        # Cost with cache-aware pricing
        uncached_prompt = max(prompt_tokens - cached_tokens, 0)
        cost_cny = (
            uncached_prompt * COST_INPUT
            + cached_tokens * COST_CACHED
            + completion_tokens * COST_OUTPUT
        )

        # Count tool calls
        tool_calls_count = sum(1 for m in messages if hasattr(m, "tool_calls") and m.tool_calls)

        cache_hit_rate = cached_tokens / prompt_tokens if prompt_tokens > 0 else 0.0

        return AgentRunResult(
            framework="LangChain", mode="default", scenario=scenario,
            final_output=final_output,
            latency_seconds=round(elapsed, 2),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cached_tokens=cached_tokens,
            cache_hit_rate=round(cache_hit_rate, 4),
            cost_cny=round(cost_cny, 6),
            tool_calls_count=tool_calls_count,
            model_used=MODEL,
            success=True,
        )
    except Exception as e:
        elapsed = time.perf_counter() - start
        return AgentRunResult(
            framework="LangChain", mode="default", scenario=scenario,
            final_output="", latency_seconds=round(elapsed, 2),
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
            cached_tokens=0, cache_hit_rate=0.0, cost_cny=0,
            tool_calls_count=0, model_used=MODEL,
            success=False, error=str(e),
        )
