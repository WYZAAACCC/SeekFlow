"""CrewAI agent — identical tools, prompts, task as SeekFlow.

Uses crewai with deepseek-v4-pro via crewai.LLM.
Model: deepseek-v4-pro (same as all other frameworks).

v2.1: tool_events from shared_tools instrumentation, thinking control.
"""
from __future__ import annotations

import time

from benchmarks.fair_comparison_v2.shared_tools import (
    SHARED_TOOLS, SYSTEM_PROMPTS, TASKS,
    parse_system_prompt, reset_tool_events, get_tool_events,
)
from benchmarks.fair_comparison_v2.seekflow_agents import AgentRunResult

MODEL = "deepseek-v4-pro"

# v4-pro pricing: (input, cached_input, output) per 1M tokens
COST_INPUT = 1.74 / 1_000_000
COST_CACHED = 0.028 / 1_000_000
COST_OUTPUT = 3.48 / 1_000_000


def _wrap_for_crewai(fn):
    """Wrap a function as a CrewAI tool with proper metadata."""
    from crewai.tools import tool as ca_tool

    def _wrapped(**kwargs):
        return fn(**kwargs)

    _wrapped.__name__ = fn.__name__
    _wrapped.__qualname__ = fn.__name__
    _wrapped.__doc__ = fn.__doc__ or fn.__name__
    _wrapped.__module__ = "__crewai_tools__"

    wrapped = ca_tool(_wrapped)
    wrapped.name = fn.__name__
    wrapped.description = (fn.__doc__ or fn.__name__).split("\n")[0].strip()
    return wrapped


def run_crewai(api_key: str, scenario: str) -> AgentRunResult:
    """CrewAI agent with shared tools, prompts, and task."""
    from crewai import Agent as CrewAIAgent, Task as CrewAITask, Crew, Process
    from crewai import LLM

    reset_tool_events()

    ca_tools = [_wrap_for_crewai(t) for t in SHARED_TOOLS]

    llm = LLM(
        model=f"deepseek/{MODEL}",
        api_key=api_key,
        temperature=0.0,
        extra_body={"thinking": {"type": "disabled"}},
    )

    role, goal, backstory = parse_system_prompt(SYSTEM_PROMPTS[scenario])
    agent = CrewAIAgent(
        role=role,
        goal=goal,
        backstory=backstory,
        tools=ca_tools,
        llm=llm,
        verbose=False,
        allow_delegation=False,
        max_iter=15,
    )

    task = CrewAITask(
        description=TASKS[scenario],
        expected_output="一份结构化的完整报告，包含所有要求的分析和数据",
        agent=agent,
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
    )

    start = time.perf_counter()
    try:
        result = crew.kickoff()
        elapsed = time.perf_counter() - start
        final_output = str(result) if result else ""

        # Extract token usage
        raw_usage = getattr(result, "token_usage", None)
        prompt_tokens = 0
        completion_tokens = 0
        cached_tokens = 0
        if raw_usage is not None:
            prompt_tokens = getattr(raw_usage, "prompt_tokens", 0) or 0
            completion_tokens = getattr(raw_usage, "completion_tokens", 0) or 0
            cached_tokens = getattr(raw_usage, "cached_prompt_tokens", 0) or 0
        total_tokens = prompt_tokens + completion_tokens

        # Cost with cache-aware pricing
        uncached_prompt = max(prompt_tokens - cached_tokens, 0)
        cost_cny = (
            uncached_prompt * COST_INPUT
            + cached_tokens * COST_CACHED
            + completion_tokens * COST_OUTPUT
        )

        tool_events = get_tool_events()

        cache_hit_rate = cached_tokens / prompt_tokens if prompt_tokens > 0 else 0.0

        return AgentRunResult(
            framework="CrewAI", mode="default", scenario=scenario,
            final_output=final_output,
            latency_seconds=round(elapsed, 2),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cached_tokens=cached_tokens,
            cache_hit_rate=round(cache_hit_rate, 4),
            cost_cny=round(cost_cny, 6),
            tool_calls_count=len(tool_events),
            tool_events=tool_events,
            model_used=MODEL,
            success=True,
        )
    except Exception as e:
        elapsed = time.perf_counter() - start
        return AgentRunResult(
            framework="CrewAI", mode="default", scenario=scenario,
            final_output="", latency_seconds=round(elapsed, 2),
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
            cached_tokens=0, cache_hit_rate=0.0, cost_cny=0,
            tool_calls_count=0, tool_events=[],
            model_used=MODEL,
            success=False, error=str(e),
        )
