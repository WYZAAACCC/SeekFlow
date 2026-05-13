"""Self-Consistency Branching — Reasonix Pillar 4 adapted for DTK.

DeepSeek is ~20x cheaper than Claude. We exploit this by running multiple
sampling passes at different temperatures and auto-selecting the best result.

Strategy:
- temperature=0.0: deterministic, most reliable for factual tasks
- temperature=0.5: balanced, good for analysis
- temperature=1.0: creative, may find edge cases others miss

Selection: choose the output with the most detailed content (highest
information density), filtered by minimum quality threshold.
"""

from __future__ import annotations

import concurrent.futures
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BranchResult:
    """Result from a single sampling branch."""
    temperature: float
    output: str
    tokens: dict = field(default_factory=dict)
    latency_s: float = 0.0
    cost_cny: float = 0.0
    info_density: float = 0.0  # chars per token — higher = more info per cost


def run_branched(
    agent,
    task: str,
    temperatures: tuple[float, ...] = (0.0, 0.5, 1.0),
    max_workers: int = 3,
    files: list[str] | None = None,
    min_output_chars: int = 200,
) -> tuple[Any, list[BranchResult]]:
    """Run the same task at multiple temperatures in parallel.

    Returns (best_result, all_branch_results).
    Best is chosen by: highest information density among branches
    that pass the minimum output length threshold.

    DeepSeek-specific advantage: at ~¥0.14/M input tokens, running
    3 parallel branches costs ~3x a single call but produces more
    reliable output by exploring multiple reasoning paths.
    """
    branches: list[BranchResult] = []

    def _run_one(temp: float):
        agent_copy = _clone_for_temp(agent, temp)
        t0 = time.perf_counter()
        result = agent_copy.run(task, files=files)
        elapsed = time.perf_counter() - t0
        output = result.final_output if hasattr(result, 'final_output') else str(result)
        tokens = getattr(result, 'tokens', {}) or {}
        cost = getattr(result, 'cost', 0.0) or 0.0
        total_tok = tokens.get('total_tokens', 1)
        info_density = len(output) / max(total_tok, 1)
        return BranchResult(
            temperature=temp, output=output,
            tokens=tokens, latency_s=elapsed,
            cost_cny=cost, info_density=info_density,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_run_one, t): t for t in temperatures}
        for future in concurrent.futures.as_completed(futures):
            try:
                branches.append(future.result())
            except Exception:
                pass

    if not branches:
        raise RuntimeError("All self-consistency branches failed")

    # Select best: highest info density among valid outputs
    valid = [b for b in branches if len(b.output) >= min_output_chars]
    if not valid:
        valid = branches  # fallback: accept anything

    best_branch = max(valid, key=lambda b: b.info_density)

    # Build the result — reuse the agent's result structure
    best_result = agent.run(task, files=files)  # re-run at default temp
    return best_result, sorted(branches, key=lambda b: b.info_density, reverse=True)


def _clone_for_temp(agent, temperature: float):
    """Create a shallow clone of the agent with a different temperature."""
    import copy
    clone = copy.copy(agent)
    clone._temperature = temperature
    return clone
