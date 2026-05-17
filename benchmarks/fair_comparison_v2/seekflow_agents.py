"""SeekFlow agent implementations — Fast mode and Stable mode.

Uses the current seekflow (v0.3.7) API with deepseek-v4-flash model.
Fast: thinking disabled, mode="fast", minimal overhead
Stable: thinking enabled, mode="stable", cache optimization + context compression
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

from benchmarks.fair_comparison_v2.shared_tools import SHARED_TOOLS, SYSTEM_PROMPTS, TASKS

MODEL = "deepseek-v4-pro"


@dataclass
class AgentRunResult:
    """Standardized result from any agent run — framework-agnostic."""
    framework: str
    mode: str
    scenario: str
    final_output: str
    latency_seconds: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int
    cache_hit_rate: float
    cost_cny: float
    tool_calls_count: int
    model_used: str
    success: bool
    error: str = ""


def _extract_usage(result) -> tuple[dict, float, int, float]:
    """Extract standardized usage from AgentResult."""
    tokens = result.tokens or {}
    prompt = tokens.get("prompt_tokens", 0)
    completion = tokens.get("completion_tokens", 0)
    total = tokens.get("total_tokens", prompt + completion)
    diag = result.diagnostics
    cached = diag.cache_tokens
    hit_rate = diag.cache_hit_rate
    return tokens, total, cached, hit_rate


def run_seekflow_fast(api_key: str, scenario: str) -> AgentRunResult:
    """SeekFlow Fast mode: thinking=OFF, mode='fast'.

    Fast mode prioritizes speed and cost over analytical depth.
    No thinking tokens, no context compression, minimal framework overhead.
    """
    from seekflow.agent.agent import DeepSeekAgent

    sys_prompt = SYSTEM_PROMPTS[scenario]
    agent = DeepSeekAgent(
        role=sys_prompt.split("\n")[0].strip("你是一名"),
        goal=sys_prompt.split("\n")[1].strip("1. "),
        backstory=sys_prompt.split("\n")[0],
        api_key=api_key,
        model=MODEL,
        thinking=False,
        temperature=0.0,
        max_steps=12,
        mode="fast",
    )
    for t in SHARED_TOOLS:
        agent.add_tool(t)

    start = time.perf_counter()
    try:
        result = agent.run(TASKS[scenario])
        elapsed = time.perf_counter() - start
        tokens, total, cached, hit_rate = _extract_usage(result)

        return AgentRunResult(
            framework="SeekFlow", mode="fast", scenario=scenario,
            final_output=result.final_output,
            latency_seconds=round(elapsed, 2),
            prompt_tokens=tokens.get("prompt_tokens", 0),
            completion_tokens=tokens.get("completion_tokens", 0),
            total_tokens=total,
            cached_tokens=cached,
            cache_hit_rate=round(hit_rate, 4),
            cost_cny=round(result.cost, 6),
            tool_calls_count=len(result.tool_calls),
            model_used=result.model or MODEL,
            success=True,
        )
    except Exception as e:
        elapsed = time.perf_counter() - start
        return AgentRunResult(
            framework="SeekFlow", mode="fast", scenario=scenario,
            final_output="", latency_seconds=round(elapsed, 2),
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
            cached_tokens=0, cache_hit_rate=0.0, cost_cny=0,
            tool_calls_count=0, model_used=MODEL,
            success=False, error=str(e),
        )


def run_seekflow_stable(api_key: str, scenario: str) -> AgentRunResult:
    """SeekFlow Stable mode: thinking=ON, mode='stable'.

    Stable mode enables DeepSeek thinking (chain-of-thought), context compression,
    memory, event bus, and cache stabilization. Prioritizes quality over speed.
    """
    from seekflow.agent.agent import DeepSeekAgent

    sys_prompt = SYSTEM_PROMPTS[scenario]
    agent = DeepSeekAgent(
        role=sys_prompt.split("\n")[0].strip("你是一名"),
        goal=sys_prompt.split("\n")[1].strip("1. "),
        backstory=sys_prompt.split("\n")[0],
        api_key=api_key,
        model=MODEL,
        thinking=True,
        temperature=0.0,
        max_steps=12,
        mode="stable",
        dangerous_tools=True,
    )
    for t in SHARED_TOOLS:
        agent.add_tool(t)

    start = time.perf_counter()
    try:
        result = agent.run(TASKS[scenario])
        elapsed = time.perf_counter() - start
        tokens, total, cached, hit_rate = _extract_usage(result)

        return AgentRunResult(
            framework="SeekFlow", mode="stable", scenario=scenario,
            final_output=result.final_output,
            latency_seconds=round(elapsed, 2),
            prompt_tokens=tokens.get("prompt_tokens", 0),
            completion_tokens=tokens.get("completion_tokens", 0),
            total_tokens=total,
            cached_tokens=cached,
            cache_hit_rate=round(hit_rate, 4),
            cost_cny=round(result.cost, 6),
            tool_calls_count=len(result.tool_calls),
            model_used=result.model or MODEL,
            success=True,
        )
    except Exception as e:
        elapsed = time.perf_counter() - start
        return AgentRunResult(
            framework="SeekFlow", mode="stable", scenario=scenario,
            final_output="", latency_seconds=round(elapsed, 2),
            prompt_tokens=0, completion_tokens=0, total_tokens=0,
            cached_tokens=0, cache_hit_rate=0.0, cost_cny=0,
            tool_calls_count=0, model_used=MODEL,
            success=False, error=str(e),
        )
