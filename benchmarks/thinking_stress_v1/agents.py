"""Agent configuration layer for Thinking Stress Benchmark v1.

Provides three SeekFlow configurations that share identical tools and prompts,
differing only in thinking mode, agent mode, and max_steps.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

from benchmarks.thinking_stress_v1.scenario import SYSTEM_PROMPT, TASK
from benchmarks.thinking_stress_v1.tools import TOOLS, _STATE_DIR
from benchmarks.thinking_stress_v1.contracts import RunResult

MODEL = "deepseek-v4-pro"


def _unpack_tokens(tokens: dict | None) -> tuple[int, int, int]:
    if not tokens:
        return 0, 0, 0
    if hasattr(tokens, "prompt_tokens"):
        return (
            tokens.prompt_tokens,
            tokens.completion_tokens,
            tokens.total_tokens,
        )
    return (
        tokens.get("prompt_tokens", 0),
        tokens.get("completion_tokens", 0),
        tokens.get("total_tokens", 0),
    )


def _read_audit_log(run_id: str) -> list[dict]:
    """Read audit log from file (subprocess-safe)."""
    audit_path = _STATE_DIR / f"audit_{run_id}.jsonl"
    events = []
    try:
        if audit_path.exists():
            with open(audit_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
    except Exception:
        pass
    return events


def _run_seekflow_agent(
    thinking: bool,
    mode: str,
    max_steps: int,
    api_key: str,
) -> RunResult:
    """Run a SeekFlow DeepSeekAgent with the given configuration."""
    from seekflow.agent.agent import DeepSeekAgent

    # Generate unique run ID for file-based state (cross-process safe)
    run_id = uuid.uuid4().hex[:12]
    ws_state_path = _STATE_DIR / f"ws_{run_id}.json"
    audit_path = _STATE_DIR / f"audit_{run_id}.jsonl"

    # Set env vars so subprocess tools find the right state files
    os.environ["_SEEKFLOW_THINKING_WS_FILE"] = str(ws_state_path)
    os.environ["_SEEKFLOW_THINKING_AUDIT_FILE"] = str(audit_path)

    # Clear state files for fresh run
    try:
        ws_state_path.write_text("", encoding="utf-8")
        audit_path.write_text("", encoding="utf-8")
    except Exception:
        pass

    mode_label = f"{mode}-{'thinking' if thinking else 'no-thinking'}"

    agent = DeepSeekAgent(
        role="企业级 Agent Runtime 架构师与安全工程师",
        goal="修复 mini_agent_runtime 的所有 bug 并通过全部测试",
        backstory="安全、协议、测试驱动修复专家，精通 Python 和 DeepSeek API 协议",
        api_key=api_key,
        model=MODEL,
        thinking=thinking,
        mode=mode,
        max_steps=max_steps,
        dangerous_tools=True,
        temperature=0.0,
    )

    for t in TOOLS:
        agent.add_tool(t)

    start = time.perf_counter()
    try:
        full_prompt = SYSTEM_PROMPT + "\n\n" + TASK
        result = agent.run(full_prompt)
        elapsed = time.perf_counter() - start

        diag = result.diagnostics
        p_tok, c_tok, t_tok = _unpack_tokens(result.tokens)

        # Reasoning info — directly from AgentResult
        reasoning = result.reasoning_content or ""
        reasoning_bytes = diag.context_breakdown.get("reasoning", 0) if diag else 0

        # Read audit log from file (captures subprocess events too)
        audit_log = _read_audit_log(run_id)

        # Capture diff
        diff_text = ""
        try:
            from benchmarks.thinking_stress_v1.tools import get_diff
            diff_result = get_diff()
            diff_text = diff_result.get("diff", "")
        except Exception:
            pass

        # Read workspace path from file
        workspace = None
        try:
            if ws_state_path.exists():
                data = json.loads(ws_state_path.read_text(encoding="utf-8"))
                workspace = data.get("workspace")
        except Exception:
            pass

        return RunResult(
            framework="SeekFlow",
            mode=mode_label,
            thinking=thinking,
            success=True,
            final_output=result.final_output or "",
            latency_s=round(elapsed, 2),
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            total_tokens=t_tok,
            cost_cny=round(result.cost, 6) if result.cost else 0.0,
            tool_calls_count=len(audit_log),
            audit_log=audit_log,
            diff=diff_text,
            diagnostics={
                "reasoning_present": bool(reasoning),
                "reasoning_chars": len(reasoning),
                "reasoning_context_bytes": reasoning_bytes,
                "cache_hit_rate": diag.cache_hit_rate if diag else 0.0,
                "cache_tokens": diag.cache_tokens if diag else 0,
                "workspace": workspace,
            },
        )
    except Exception as e:
        elapsed = time.perf_counter() - start
        audit_log = _read_audit_log(run_id)
        return RunResult(
            framework="SeekFlow",
            mode=mode_label,
            thinking=thinking,
            success=False,
            final_output="",
            latency_s=round(elapsed, 2),
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            cost_cny=0.0,
            tool_calls_count=len(audit_log),
            audit_log=audit_log,
            diff="",
            raw_error=str(e),
        )


def run_seekflow_stable_thinking(api_key: str) -> RunResult:
    """SeekFlow stable + thinking — experimental group."""
    return _run_seekflow_agent(thinking=True, mode="stable", max_steps=30, api_key=api_key)


def run_seekflow_stable_no_thinking(api_key: str) -> RunResult:
    """SeekFlow stable without thinking — control group for thinking isolation."""
    return _run_seekflow_agent(thinking=False, mode="stable", max_steps=30, api_key=api_key)


def run_seekflow_fast_no_thinking(api_key: str) -> RunResult:
    """SeekFlow fast without thinking — lightweight baseline."""
    return _run_seekflow_agent(thinking=False, mode="fast", max_steps=24, api_key=api_key)
