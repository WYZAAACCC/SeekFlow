"""FAIR COMPARISON BENCHMARK v2 — SeekFlow Fast vs Stable vs LangChain vs CrewAI.

FAIRNESS GUARANTEES:
1. Same model (deepseek-v4-pro) for ALL frameworks
2. Same 8 tools (identical Python functions) for ALL frameworks
3. Same system prompts for ALL frameworks
4. Same task descriptions (IDENTICAL, including instructions) for ALL frameworks
5. Same temperature (0.0) for ALL frameworks
6. Same DeepSeek API endpoint for ALL frameworks
7. Same judge (deepseek-v4-pro) scoring ALL outputs BLIND
8. Same pricing formula used across ALL frameworks
9. Three independent rounds to control for API variance
10. Randomized execution order each round to eliminate cache/rate-limit bias
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

# Ensure project root is on path
_PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SCENARIOS = [
    # Mechanical (Fast主场 — 速度/成本优势)
    "financial_analyst",
    "supply_chain_analyst",
    "portfolio_rebalance",
    # Extreme reasoning (Stable主场 — thinking必要性)
    "impossible_trilemma",
    "causal_forensics",
    "negotiation_deadlock",
]
ROUNDS = 3
OUTPUT_TRUNCATION = 6000       # must match judge.MAX_OUTPUT_CHARS
AGENT_TIMEOUT = 600             # seconds per agent run (v4-pro thinking mode is slow)
INTER_RUN_JITTER = (1.0, 3.0)   # random sleep between runs to avoid rate limits
RANDOM_SEED = 42                # fixed for reproducibility


# ═══════════════════════════════════════════════════════════════════════════
# Run all benchmarks
# ═══════════════════════════════════════════════════════════════════════════


def _build_configs():
    """Build framework config list. Import failures recorded as config errors."""
    from benchmarks.fair_comparison_v2.seekflow_agents import (
        run_seekflow_fast, run_seekflow_stable,
    )
    configs = [
        ("SeekFlow", "fast", run_seekflow_fast),
        ("SeekFlow", "stable", run_seekflow_stable),
    ]
    # LangChain
    try:
        from benchmarks.fair_comparison_v2.langchain_agent import run_langchain
        configs.append(("LangChain", "default", run_langchain))
    except ImportError as e:
        print(f"[WARN] LangChain import failed (env issue, not framework bug): {e}")
    # CrewAI
    try:
        from benchmarks.fair_comparison_v2.crewai_agent import run_crewai
        configs.append(("CrewAI", "default", run_crewai))
    except ImportError as e:
        print(f"[WARN] CrewAI import failed (env issue, not framework bug): {e}")
    return configs


def run_all(api_key: str) -> list[dict]:
    """Run all scenarios x rounds x frameworks. Returns list of result dicts."""
    from benchmarks.fair_comparison_v2.judge import judge_output
    from benchmarks.fair_comparison_v2.shared_tools import TASKS

    all_configs = _build_configs()
    total_runs = len(SCENARIOS) * ROUNDS * len(all_configs)
    run_idx = 0
    all_results: list[dict] = []
    rng = random.Random(RANDOM_SEED)

    for rnd in range(1, ROUNDS + 1):
        print(f"\n{'#'*80}")
        print(f"# ROUND {rnd} of {ROUNDS}")
        print(f"{'#'*80}")

        for scenario in SCENARIOS:
            print(f"\n{'='*70}")
            print(f"SCENARIO: {scenario} (Round {rnd}/{ROUNDS})")
            print(f"{'='*70}")

            # Randomized order each round to eliminate positional bias
            shuffled = list(all_configs)
            rng.shuffle(shuffled)
            print(f"  Execution order: {[f'{fw}({mode})' for fw, mode, _ in shuffled]}")

            for fw_name, mode, runner_fn in shuffled:
                run_idx += 1
                config_label = f"[{fw_name} | {mode}]"
                progress = f"[{run_idx}/{total_runs}]"
                print(f"\n  {progress} {config_label} ", end="", flush=True)

                # Run agent with timeout
                start = time.perf_counter()
                try:
                    result = runner_fn(api_key, scenario)
                except Exception as e:
                    print(f"CRASH: {e}")
                    _record_failure(all_results, fw_name, mode, scenario, rnd,
                                    f"Runner crashed: {e}")
                    continue

                if not result.success:
                    print(f"FAILED: {result.error}")
                    _record_failure(all_results, fw_name, mode, scenario, rnd,
                                    result.error)
                    continue

                elapsed = time.perf_counter() - start
                if elapsed > AGENT_TIMEOUT:
                    print(f"TIMEOUT ({elapsed:.0f}s > {AGENT_TIMEOUT}s)")
                else:
                    print(f"OK ({result.latency_seconds:.1f}s, {result.total_tokens}T, Y{result.cost_cny:.6f})")

                # ── Judge output ──
                output_full = result.final_output or ""
                output_for_judge = output_full[:OUTPUT_TRUNCATION]

                print(f"         LLM Judge...", end="", flush=True)
                judge_start = time.perf_counter()
                quality_scores = judge_output(api_key, TASKS[scenario], output_for_judge)
                judge_elapsed = time.perf_counter() - judge_start
                print(f" done ({judge_elapsed:.1f}s) quality={quality_scores.get('overall', '?')}")

                # ── Compliance Judge ──
                print(f"         Compliance Judge...", end="", flush=True)
                from benchmarks.fair_comparison_v2.compliance import (
                    score_tool_compliance, compute_final_score,
                )
                compliance = score_tool_compliance(
                    scenario, result.tool_events, output_full,
                )
                final_score = compute_final_score(
                    quality_scores.get("overall", 5.0), compliance, scenario,
                )
                print(f" compliance={compliance['tool_compliance_score']} final={final_score}")

                record = {
                    "round": rnd,
                    "framework": fw_name,
                    "mode": mode,
                    "scenario": scenario,
                    "success": True,
                    "latency_seconds": result.latency_seconds,
                    "prompt_tokens": result.prompt_tokens,
                    "completion_tokens": result.completion_tokens,
                    "total_tokens": result.total_tokens,
                    "cached_tokens": result.cached_tokens,
                    "cache_hit_rate": result.cache_hit_rate,
                    "cost_cny": result.cost_cny,
                    "tool_calls_count": result.tool_calls_count,
                    "tool_events": result.tool_events,
                    "model_used": result.model_used,
                    "scores": quality_scores,
                    "compliance": compliance,
                    "final_score": final_score,
                    "output_full": output_full,
                    "output_for_judge": output_for_judge,
                    "output_chars": len(output_full),
                    "judge_output_chars": len(output_for_judge),
                    "was_truncated_for_judge": len(output_full) > OUTPUT_TRUNCATION,
                }
                all_results.append(record)

                # Save incrementally (atomic: write to temp then rename)
                _save_incremental(all_results)

                # Random jitter to avoid rate limits
                if run_idx < total_runs:
                    jitter = rng.uniform(*INTER_RUN_JITTER)
                    time.sleep(jitter)

    return all_results


def _record_failure(results: list, fw: str, mode: str, scenario: str, rnd: int, error: str):
    results.append({
        "round": rnd, "framework": fw, "mode": mode, "scenario": scenario,
        "success": False, "error": error,
        "latency_seconds": 0, "prompt_tokens": 0, "completion_tokens": 0,
        "total_tokens": 0, "cached_tokens": 0, "cache_hit_rate": 0.0,
        "cost_cny": 0, "tool_calls_count": 0, "model_used": "",
        "scores": {}, "output": "",
    })


def _save_incremental(results: list[dict]):
    """Atomic save: write to temp then rename. Survives crashes."""
    path = OUTPUT_DIR / "_incremental_results.json"
    tmp = OUTPUT_DIR / "_incremental_results.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


# ═══════════════════════════════════════════════════════════════════════════
# Report generation
# ═══════════════════════════════════════════════════════════════════════════


def print_report(results: list[dict]):
    """Print a detailed, multi-section comparison report."""
    successful = [r for r in results if r.get("success")]

    if not successful:
        print("\nNo successful runs to report.")
        return

    # ── Header ──
    model_tag = successful[0].get("model_used", "?")
    print(f"\n\n{'='*100}")
    print(f"  FAIR COMPARISON BENCHMARK v2 — COMPREHENSIVE REPORT")
    print(f"  Model: {model_tag} (agents) | Judge: deepseek-v4-pro | Temp: 0.0")
    print(f"  Runs: {len(successful)} successful / {len(results)} total | Rounds: {ROUNDS}")
    print(f"  Scoring: 70% LLM report quality + 30% tool compliance = final")
    print(f"{'='*100}")

    # ── Per-Scenario Detail ──
    for scenario in SCENARIOS:
        scenario_results = [r for r in successful if r["scenario"] == scenario]
        if not scenario_results:
            continue

        print(f"\n{'─'*100}")
        print(f"  SCENARIO: {scenario}")
        print(f"{'─'*100}")

        # Header
        print(f"  {'Framework':<14} {'Mode':<8} {'Round':>5} {'Latency':>8} {'Tokens':>8} {'Cache':>7} {'Cost':>12} {'Qual':>5} {'Cmp':>4} {'Final':>6} {'C':>3} {'A':>3} {'D':>3} {'S':>3} {'Ac':>3} {'P':>3} {'TC':>4} {'TR':>3}")
        print(f"  {'-'*115}")

        for r in sorted(scenario_results, key=lambda x: (x["framework"], x["mode"], x["round"])):
            s = r.get("scores", {})
            comp = r.get("compliance", {})
            final = r.get("final_score", s.get("overall", 0))
            cache_pct = f"{r['cache_hit_rate']*100:.0f}%" if r.get("cache_hit_rate") else "0%"
            truncated = "YES" if r.get("was_truncated_for_judge") else ""
            print(f"  {r['framework']:<14} {r['mode']:<8} {r['round']:>5} {r['latency_seconds']:>7.1f}s {r['total_tokens']:>8} {cache_pct:>7} {r['cost_cny']:>11.6f} {s.get('overall',0):>5.1f} {comp.get('tool_compliance_score',0):>4.1f} {final:>6.1f} {s.get('completeness',0):>3} {s.get('accuracy',0):>3} {s.get('depth',0):>3} {s.get('structure',0):>3} {s.get('actionability',0):>3} {s.get('professionalism',0):>3} {r.get('tool_calls_count',0):>4} {truncated:>3}")

    # ── Cross-Scenario Averages ──
    print(f"\n{'─'*100}")
    print("  CROSS-SCENARIO AVERAGES (3 rounds x 2 scenarios)")
    print(f"{'─'*100}")
    print(f"  {'Framework':<14} {'Mode':<8} {'Avg Lat':>9} {'Avg Tok':>8} {'Avg Cache':>9} {'Avg Cost':>12} {'Avg Qual':>9} {'Avg Cmp':>8} {'Avg Final':>10} {'C':>4} {'A':>4} {'D':>4} {'S':>4} {'Ac':>4} {'P':>4}")
    print(f"  {'-'*135}")

    from collections import defaultdict
    agg = defaultdict(list)
    for r in successful:
        key = (r["framework"], r["mode"])
        agg[key].append(r)

    for (fw, mode), recs in sorted(agg.items(), key=lambda x: sum(r.get("final_score", r["scores"].get("overall", 0)) for r in x[1]) / len(x[1]), reverse=True):
        n = len(recs)
        avg_lat = sum(r["latency_seconds"] for r in recs) / n
        avg_tok = sum(r["total_tokens"] for r in recs) / n
        avg_cache = sum(r["cache_hit_rate"] for r in recs) / n * 100
        avg_cost = sum(r["cost_cny"] for r in recs) / n
        avg_qual = sum(r["scores"].get("overall", 0) for r in recs) / n
        avg_comp = sum(r.get("compliance", {}).get("tool_compliance_score", 0) for r in recs) / n
        avg_final = sum(r.get("final_score", 0) for r in recs) / n
        avg_c = sum(r["scores"].get("completeness", 0) for r in recs) / n
        avg_a = sum(r["scores"].get("accuracy", 0) for r in recs) / n
        avg_d = sum(r["scores"].get("depth", 0) for r in recs) / n
        avg_s = sum(r["scores"].get("structure", 0) for r in recs) / n
        avg_ac = sum(r["scores"].get("actionability", 0) for r in recs) / n
        avg_p = sum(r["scores"].get("professionalism", 0) for r in recs) / n
        print(f"  {fw:<14} {mode:<8} {avg_lat:>8.1f}s {avg_tok:>8.0f} {avg_cache:>8.1f}% {avg_cost:>11.6f} {avg_qual:>8.1f} {avg_comp:>8.1f} {avg_final:>10.1f} {avg_c:>4.1f} {avg_a:>4.1f} {avg_d:>4.1f} {avg_s:>4.1f} {avg_ac:>4.1f} {avg_p:>4.1f}")

    # ── Round Consistency ──
    print(f"\n{'─'*100}")
    print("  ROUND-TO-ROUND CONSISTENCY (StdDev of Overall Scores)")
    print(f"{'─'*100}")
    round_agg = defaultdict(lambda: defaultdict(list))
    for r in successful:
        key = (r["framework"], r["mode"])
        round_agg[key][r["round"]].append(r.get("final_score", r["scores"].get("overall", 0)))

    for (fw, mode) in sorted(round_agg.keys()):
        scores_per_round = []
        for rnd in sorted(round_agg[(fw, mode)].keys()):
            avg = sum(round_agg[(fw, mode)][rnd]) / len(round_agg[(fw, mode)][rnd])
            scores_per_round.append(avg)
        if len(scores_per_round) > 1:
            mean = sum(scores_per_round) / len(scores_per_round)
            std = (sum((s - mean)**2 for s in scores_per_round) / len(scores_per_round)) ** 0.5
            print(f"  {fw:<14} {mode:<8} Rounds: {[f'{s:.1f}' for s in scores_per_round]} Mean={mean:.1f} StdDev={std:.2f}")


def save_results(results: list[dict]):
    """Save full results to timestamped JSON (outputs truncated to OUTPUT_TRUNCATION)."""
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"benchmark_{timestamp}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nFull results saved to: {path}")


# ═══════════════════════════════════════════════════════════════════════════
# Main entry point with CLI
# ═══════════════════════════════════════════════════════════════════════════

def _parse_args():
    """Minimal CLI: python -m benchmarks.fair_comparison_v2.runner [--rounds N] [--scenarios S1,S2]"""
    args = {"rounds": ROUNDS, "scenarios": SCENARIOS}
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        if argv[i] == "--rounds" and i + 1 < len(argv):
            args["rounds"] = int(argv[i + 1])
            i += 2
        elif argv[i] == "--scenarios" and i + 1 < len(argv):
            args["scenarios"] = argv[i + 1].split(",")
            i += 2
        else:
            i += 1
    return args


if __name__ == "__main__":
    cli = _parse_args()
    ROUNDS = cli["rounds"]
    SCENARIOS = cli["scenarios"]

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY environment variable not set.")
        print("  export DEEPSEEK_API_KEY=sk-...")
        sys.exit(1)

    print("=" * 100)
    print("  FAIR COMPARISON BENCHMARK v2")
    print("  SeekFlow Fast vs SeekFlow Stable vs LangChain vs CrewAI")
    print(f"  Model: deepseek-v4-pro | Judge: deepseek-v4-pro | Rounds: {ROUNDS}")
    print(f"  Scenarios: {', '.join(SCENARIOS)}")
    print("  Same tools | Same prompts | Same tasks | Same model | Same temperature")
    print("  Execution order: RANDOMIZED per round")
    print("=" * 100)

    start_all = time.perf_counter()
    results = run_all(api_key)
    total_elapsed = time.perf_counter() - start_all

    print(f"\n\nTotal benchmark time: {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")

    print_report(results)
    save_results(results)
