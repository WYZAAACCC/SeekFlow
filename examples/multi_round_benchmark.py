"""Multi-Round Benchmark — statistically reliable framework comparison.

Runs each demo scenario N times across all 4 frameworks (SeekFlow Fast,
SeekFlow Stable, LangChain, CrewAI). Collects per-round data including
token counts, cache hits, costs, latency, and quality scores.

Outputs:
- Raw data: examples/output/multi_round_raw.json
- Analysis: printed comparison with mean/median/std/min/max

Usage: python examples/multi_round_benchmark.py [--rounds 3]
"""

import json, os, sys, time, argparse
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from examples._demo_utils import RunResult

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = "deepseek-chat"
ROUNDS = 3
SCENARIOS = ["financial", "supply_chain", "code_auditor", "research"]

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def run_demo(scenario: str) -> list[RunResult]:
    """Import and run a demo scenario, returning all RunResults."""
    import importlib
    mod = importlib.import_module(f"examples.demo_{scenario}")

    results = []
    configs = [
        ("SeekFlow Fast", lambda: mod.run_dtk("fast")),
        ("SeekFlow Stable", lambda: mod.run_dtk("stable")),
        ("LangChain", mod.run_langchain),
        ("CrewAI", mod.run_crewai),
    ]
    for name, fn in configs:
        r = fn()
        r.framework = name
        results.append(r)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    parser.add_argument("--scenarios", nargs="+", default=SCENARIOS)
    args = parser.parse_args()
    rounds = args.rounds

    all_data: dict[str, list] = defaultdict(list)

    print(f"{'='*80}")
    print(f"  MULTI-ROUND BENCHMARK — {rounds} rounds × {len(args.scenarios)} scenarios")
    print(f"  Model: {MODEL} | Judge: deepseek-v4-pro | Temp: 0.0")
    print(f"{'='*80}")

    for scenario in args.scenarios:
        for rnd in range(1, rounds + 1):
            print(f"\n{'─'*60}")
            print(f"  [{scenario}] Round {rnd}/{rounds}")
            print(f"{'─'*60}")
            results = run_demo(scenario)

            for rr in results:
                if not rr.success:
                    print(f"  {rr.framework}: FAILED — {rr.error}")
                    continue
                print(f"  {rr.framework}: score={rr.scores.get('overall','?')} "
                      f"tokens={rr.total_tokens} cache={rr.cached_tokens/max(rr.prompt_tokens,1)*100:.0f}% "
                      f"cost=CNY{rr.cost_total:.6f} time={rr.latency_s:.1f}s")

                all_data[f"{scenario}|{rr.framework}"].append({
                    "round": rnd,
                    "scenario": scenario,
                    "framework": rr.framework,
                    "latency_s": rr.latency_s,
                    "prompt_tokens": rr.prompt_tokens,
                    "completion_tokens": rr.completion_tokens,
                    "total_tokens": rr.total_tokens,
                    "cached_tokens": rr.cached_tokens,
                    "api_calls": rr.api_calls,
                    "cost_total": rr.cost_total,
                    "cost_uncached": rr.cost_uncached,
                    "cost_cached": rr.cost_cached,
                    "cost_output": rr.cost_output,
                    "output_len": rr.output_len,
                    "scores": rr.scores,
                })

    # Save raw data
    raw_path = OUTPUT_DIR / f"multi_round_raw_{time.strftime('%Y%m%d_%H%M%S')}.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(dict(all_data), f, ensure_ascii=False, indent=2)
    print(f"\nRaw data saved: {raw_path}")

    # ── Statistical Analysis ──────────────────────────────────────────
    print(f"\n{'='*90}")
    print(f"  MULTI-ROUND STATISTICAL ANALYSIS ({rounds} rounds)")
    print(f"{'='*90}")

    for scenario in args.scenarios:
        print(f"\n{'─'*90}")
        print(f"  SCENARIO: {scenario}")
        print(f"{'─'*90}")
        print(f"{'Framework':<20} {'Score':>6} {'±std':>6} {'Range':>10} {'AvgTok':>7} {'AvgCost':>10} {'AvgTime':>7}")
        print("-" * 72)

        scenario_data = []
        for fw in ["SeekFlow Fast", "SeekFlow Stable", "LangChain", "CrewAI"]:
            key = f"{scenario}|{fw}"
            records = all_data.get(key, [])
            if len(records) < 1:
                continue

            scores = [r["scores"]["overall"] for r in records if r["scores"].get("overall", 0) > 0]
            tokens = [r["total_tokens"] for r in records]
            costs = [r["cost_total"] for r in records]
            times = [r["latency_s"] for r in records]
            cache_rates = [r["cached_tokens"]/max(r["prompt_tokens"],1)*100 for r in records]

            def stats(vals):
                if not vals: return (0,0,0,0,0)
                vals = sorted(vals)
                n = len(vals)
                mean = sum(vals)/n
                median = vals[n//2]
                variance = sum((v-mean)**2 for v in vals)/n
                return mean, median, variance**0.5, vals[0], vals[-1]

            s_mean, s_med, s_std, s_min, s_max = stats(scores)
            t_mean, _, _, _, _ = stats(tokens)
            c_mean, _, _, _, _ = stats(costs)
            l_mean, _, _, _, _ = stats(times)
            cr_mean, _, _, _, _ = stats(cache_rates)

            print(f"{fw:<20} {s_mean:>5.1f} {s_std:>5.1f} {s_min:>4.1f}-{s_max:>4.1f} {t_mean:>7.0f} CNY{c_mean:>8.6f} {l_mean:>6.1f}s")

            scenario_data.append({
                "framework": fw,
                "score_mean": round(s_mean, 2),
                "score_std": round(s_std, 2),
                "score_min": round(s_min, 1),
                "score_max": round(s_max, 1),
                "score_median": round(s_med, 1),
                "token_mean": round(t_mean, 0),
                "cost_mean": round(c_mean, 6),
                "latency_mean": round(l_mean, 1),
                "cache_rate_mean": round(cr_mean, 0),
                "n_rounds": len(records),
            })

    # ── Cross-Scenario Averages ───────────────────────────────────────
    print(f"\n{'─'*90}")
    print(f"  CROSS-SCENARIO AGGREGATE (all {rounds} rounds)")
    print(f"{'─'*90}")

    # Aggregate by framework across all scenarios
    fw_agg = defaultdict(lambda: {"scores": [], "tokens": [], "costs": [], "times": [], "cache": []})
    for key, records in all_data.items():
        fw = key.split("|")[1]
        for r in records:
            if r["scores"].get("overall", 0) > 0:
                fw_agg[fw]["scores"].append(r["scores"]["overall"])
            fw_agg[fw]["tokens"].append(r["total_tokens"])
            fw_agg[fw]["costs"].append(r["cost_total"])
            fw_agg[fw]["times"].append(r["latency_s"])
            fw_agg[fw]["cache"].append(r["cached_tokens"]/max(r["prompt_tokens"],1)*100)

    print(f"{'Framework':<20} {'Score':>6} {'±std':>6} {'AvgTok':>7} {'AvgCost':>10} {'AvgTime':>7} {'Cache':>6} {'Rounds':>7}")
    print("-" * 75)
    for fw in ["SeekFlow Fast", "SeekFlow Stable", "LangChain", "CrewAI"]:
        agg = fw_agg[fw]
        s_mean = sum(agg["scores"])/len(agg["scores"]) if agg["scores"] else 0
        s_std = (sum((v-s_mean)**2 for v in agg["scores"])/len(agg["scores"]))**0.5 if agg["scores"] else 0
        t_mean = sum(agg["tokens"])/len(agg["tokens"]) if agg["tokens"] else 0
        c_mean = sum(agg["costs"])/len(agg["costs"]) if agg["costs"] else 0
        l_mean = sum(agg["times"])/len(agg["times"]) if agg["times"] else 0
        cr_mean = sum(agg["cache"])/len(agg["cache"]) if agg["cache"] else 0
        n = len(agg["scores"])
        print(f"{fw:<20} {s_mean:>5.1f} {s_std:>5.1f} {t_mean:>7.0f} CNY{c_mean:>8.6f} {l_mean:>6.1f}s {cr_mean:>5.0f}% {n:>7}")

    # ── Save analysis ─────────────────────────────────────────────────
    analysis_path = OUTPUT_DIR / f"multi_round_analysis_{time.strftime('%Y%m%d_%H%M%S')}.json"
    analysis = {
        "model": MODEL, "rounds": rounds, "scenarios": args.scenarios,
        "per_scenario": {},
        "aggregate": {},
    }
    for scenario in args.scenarios:
        analysis["per_scenario"][scenario] = []
        for fw in ["SeekFlow Fast", "SeekFlow Stable", "LangChain", "CrewAI"]:
            key = f"{scenario}|{fw}"
            records = all_data.get(key, [])
            if not records: continue
            scores = [r["scores"]["overall"] for r in records if r["scores"].get("overall",0)>0]
            tokens = [r["total_tokens"] for r in records]
            costs = [r["cost_total"] for r in records]
            times = [r["latency_s"] for r in records]
            analysis["per_scenario"][scenario].append({
                "framework": fw,
                "score_mean": round(sum(scores)/len(scores),2) if scores else 0,
                "score_std": round((sum((v-sum(scores)/len(scores))**2 for v in scores)/len(scores))**0.5,2) if scores else 0,
                "token_mean": round(sum(tokens)/len(tokens),0) if tokens else 0,
                "cost_mean": round(sum(costs)/len(costs),6) if costs else 0,
                "latency_mean": round(sum(times)/len(times),1) if times else 0,
                "n": len(records),
            })
    print(f"Analysis saved: {analysis_path}")


if __name__ == "__main__":
    main()
