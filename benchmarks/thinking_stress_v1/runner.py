"""Runner for Thinking Stress Benchmark v1.

Usage:
    python -m benchmarks.thinking_stress_v1.runner --rounds 3
    python -m benchmarks.thinking_stress_v1.runner --rounds 1 --frameworks seekflow_fast_no_thinking

Per-run flow:
    1. Agent runs with fresh workspace → modifies code, runs tests
    2. Scorer runs public tests, hidden tests, static scan on the workspace
    3. Results saved incrementally to JSON
    4. Final Markdown report generated
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Ensure project root on path
_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from benchmarks.thinking_stress_v1.contracts import RunResult, ScoredRun
from benchmarks.thinking_stress_v1.scorer import score_run
from benchmarks.thinking_stress_v1.tools import init_workspace, TOOLS

BENCH_ROOT = Path(__file__).parent
OUTPUT_DIR = BENCH_ROOT / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

ROUNDS = 3
AGENT_TIMEOUT = 900  # seconds per agent run
INTER_RUN_JITTER = (2.0, 5.0)  # random sleep between runs to avoid rate limits
RANDOM_SEED = 42


def _build_agent_registry():
    """Build mapping from framework key to runner function."""
    from benchmarks.thinking_stress_v1.agents import (
        run_seekflow_stable_thinking,
        run_seekflow_stable_no_thinking,
        run_seekflow_fast_no_thinking,
    )
    return {
        "seekflow_stable_thinking": run_seekflow_stable_thinking,
        "seekflow_stable_no_thinking": run_seekflow_stable_no_thinking,
        "seekflow_fast_no_thinking": run_seekflow_fast_no_thinking,
    }


def run_benchmark(
    api_key: str,
    rounds: int = ROUNDS,
    frameworks: list[str] | None = None,
    max_seconds: int = AGENT_TIMEOUT,
) -> list[dict]:
    """Run the full benchmark across specified frameworks and rounds."""
    registry = _build_agent_registry()
    if frameworks is None:
        framework_keys = list(registry.keys())
    else:
        framework_keys = [fk for fk in frameworks if fk in registry]

    if not framework_keys:
        print(f"ERROR: No valid frameworks. Available: {list(registry.keys())}")
        return []

    total_runs = rounds * len(framework_keys)
    run_idx = 0
    all_results: list[dict] = []
    rng = random.Random(RANDOM_SEED)

    print("=" * 80)
    print("  THINKING STRESS BENCHMARK v1")
    print(f"  Model: deepseek-v4-pro | Rounds: {rounds}")
    print(f"  Frameworks: {', '.join(framework_keys)}")
    print(f"  Max per-run: {max_seconds}s")
    print("=" * 80)

    for rnd in range(1, rounds + 1):
        print(f"\n{'#' * 80}")
        print(f"# ROUND {rnd} of {rounds}")
        print(f"{'#' * 80}")

        # Randomized order each round
        shuffled = list(framework_keys)
        rng.shuffle(shuffled)
        print(f"  Order: {shuffled}")

        for fk in shuffled:
            run_idx += 1
            runner_fn = registry[fk]
            progress = f"[{run_idx}/{total_runs}]"

            print(f"\n  {progress} {fk} ", end="", flush=True)

            start = time.perf_counter()
            try:
                result = runner_fn(api_key)
                elapsed = time.perf_counter() - start

                if elapsed > max_seconds:
                    print(f"TIMEOUT ({elapsed:.0f}s > {max_seconds}s)")
                elif not result.success:
                    print(f"FAILED: {result.raw_error[:120]}")
                else:
                    print(f"OK ({result.latency_s:.1f}s, {result.total_tokens}T, Y{result.cost_cny:.6f})")

                # Score the run — workspace path stored in diagnostics (cross-process safe)
                scored = None
                ws_path = result.diagnostics.get("workspace") if result.diagnostics else None
                if result.success and ws_path:
                    from pathlib import Path
                    ws = Path(ws_path)
                    if ws.exists():
                        try:
                            scored = score_run(result, ws)
                            print(f"         Score: total={scored.scores.total} "
                                  f"pub={scored.scores.public_tests} "
                                  f"hid={scored.scores.hidden_tests}")
                        except Exception as e:
                            print(f"         Scoring failed: {e}")
                    else:
                        print(f"         Workspace not found: {ws_path}")

                record = {
                    "round": rnd,
                    "framework": result.framework,
                    "mode": result.mode,
                    "thinking": result.thinking,
                    "success": result.success,
                    "latency_s": result.latency_s,
                    "tokens": {
                        "prompt": result.prompt_tokens,
                        "completion": result.completion_tokens,
                        "total": result.total_tokens,
                    },
                    "cost_cny": result.cost_cny,
                    "tool_calls_count": result.tool_calls_count,
                    "diagnostics": result.diagnostics,
                }

                if scored:
                    record["score"] = {
                        "total": scored.scores.total,
                        "public_tests": scored.scores.public_tests,
                        "hidden_tests": scored.scores.hidden_tests,
                        "static_scan": scored.scores.static_scan,
                        "tool_process": scored.scores.tool_process,
                        "patch_quality": scored.scores.patch_quality,
                        "final_report": scored.scores.final_report,
                    }
                    record["tests"] = {
                        "public": {"passed": scored.public_tests.passed, "total": scored.public_tests.total},
                        "hidden": {"passed": scored.hidden_tests.passed, "total": scored.hidden_tests.total},
                    }

                record["audit_log"] = result.audit_log
                record["diff"] = result.diff[:5000]
                record["final_output"] = result.final_output[:8000]
                record["raw_error"] = result.raw_error[:500]

                all_results.append(record)
                _save_incremental(all_results)

            except Exception as e:
                elapsed = time.perf_counter() - start
                print(f"CRASH: {e}")
                all_results.append({
                    "round": rnd,
                    "framework": "SeekFlow",
                    "mode": fk,
                    "thinking": "thinking" in fk,
                    "success": False,
                    "latency_s": round(elapsed, 2),
                    "tokens": {"prompt": 0, "completion": 0, "total": 0},
                    "cost_cny": 0.0,
                    "tool_calls_count": 0,
                    "diagnostics": {},
                    "score": {},
                    "tests": {},
                    "audit_log": [],
                    "diff": "",
                    "final_output": "",
                    "raw_error": str(e)[:500],
                })
                _save_incremental(all_results)

            # Random jitter between runs
            if run_idx < total_runs:
                jitter = rng.uniform(*INTER_RUN_JITTER)
                time.sleep(jitter)

    # Compute summary
    summary = _compute_summary(all_results)
    final_output = {
        "benchmark": "thinking_stress_v1",
        "scenario": "runtime_repair_lab",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rounds": rounds,
        "results": all_results,
        "summary": summary,
    }

    # Save final output
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_path = OUTPUT_DIR / f"thinking_stress_{timestamp}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved to: {output_path}")

    return [final_output]


def _compute_summary(results: list[dict]) -> dict:
    """Compute per-mode averages from all successful runs."""
    from collections import defaultdict

    by_mode = defaultdict(list)
    for r in results:
        if r.get("success") and r.get("score", {}).get("total"):
            by_mode[r["mode"]].append(r)

    summary = {}
    for mode, recs in sorted(by_mode.items()):
        n = len(recs)
        avg_total = sum(r["score"]["total"] for r in recs) / n
        avg_public = sum(r["tests"]["public"]["passed"] for r in recs) / sum(r["tests"]["public"]["total"] for r in recs) if n else 0
        avg_hidden = sum(r["tests"]["hidden"]["passed"] for r in recs) / sum(r["tests"]["hidden"]["total"] for r in recs) if n else 0
        avg_latency = sum(r["latency_s"] for r in recs) / n
        avg_tokens = sum(r["tokens"]["total"] for r in recs) / n
        avg_cost = sum(r["cost_cny"] for r in recs) / n
        summary[mode] = {
            "runs": n,
            "avg_total_score": round(avg_total, 1),
            "avg_public_pass_rate": round(avg_public * 100, 1),
            "avg_hidden_pass_rate": round(avg_hidden * 100, 1),
            "avg_latency_s": round(avg_latency, 1),
            "avg_tokens": round(avg_tokens, 0),
            "avg_cost_cny": round(avg_cost, 6),
        }

    # Compute thinking delta
    if "stable-thinking" in summary and "stable-no-thinking" in summary:
        delta = (
            summary["stable-thinking"]["avg_total_score"]
            - summary["stable-no-thinking"]["avg_total_score"]
        )
        summary["thinking_delta_vs_stable_no_thinking"] = round(delta, 1)
        summary["hidden_delta"] = round(
            summary["stable-thinking"]["avg_hidden_pass_rate"]
            - summary["stable-no-thinking"]["avg_hidden_pass_rate"],
            1,
        )

    return summary


def _save_incremental(results: list[dict]):
    """Atomic save to survive crashes."""
    path = OUTPUT_DIR / "_incremental_thinking_stress.json"
    tmp = OUTPUT_DIR / "_incremental_thinking_stress.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def _parse_args():
    args = {"rounds": ROUNDS, "frameworks": None, "max_seconds": AGENT_TIMEOUT, "output": None}
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--rounds" and i + 1 < len(argv):
            args["rounds"] = int(argv[i + 1])
            i += 2
        elif argv[i] == "--frameworks" and i + 1 < len(argv):
            args["frameworks"] = argv[i + 1].split(",")
            i += 2
        elif argv[i] == "--max-seconds" and i + 1 < len(argv):
            args["max_seconds"] = int(argv[i + 1])
            i += 2
        elif argv[i] == "--output" and i + 1 < len(argv):
            args["output"] = argv[i + 1]
            i += 2
        else:
            i += 1
    return args


if __name__ == "__main__":
    cli = _parse_args()
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY environment variable not set.")
        print("  export DEEPSEEK_API_KEY=sk-...")
        sys.exit(1)

    run_benchmark(
        api_key=api_key,
        rounds=cli["rounds"],
        frameworks=cli["frameworks"],
        max_seconds=cli["max_seconds"],
    )
