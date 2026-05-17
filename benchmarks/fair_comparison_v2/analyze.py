"""Extract and analyze benchmark data."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

results_path = Path(__file__).parent / "output" / "_incremental_results.json"
with open(results_path, "r", encoding="utf-8") as f:
    data = json.load(f)

print("=" * 80)
print("BENCHMARK DATA ANALYSIS")
print("=" * 80)

groups = defaultdict(list)
for r in data:
    if r.get("success"):
        groups[(r["framework"], r["mode"])].append(r)

for (fw, mode), runs in sorted(groups.items()):
    n = len(runs)
    print(f"\n{'='*80}")
    print(f"{fw} | {mode}  ({n} successful runs)")
    print(f"{'='*80}")
    for r in sorted(runs, key=lambda x: (x["scenario"], x["round"])):
        s = r["scores"]
        sc = r["scenario"][:22]
        print(f"  R{r['round']} {sc:<22} {r['latency_seconds']:>6.1f}s {r['total_tokens']:>7}T cache={r['cache_hit_rate']*100:>5.1f}% cost=Y{r['cost_cny']:.6f} score={s.get('overall',0):>4.1f} TC={r['tool_calls_count']:>3}")

    lat = [r["latency_seconds"] for r in runs]
    tok = [r["total_tokens"] for r in runs]
    cst = [r["cost_cny"] for r in runs]
    scr = [r["scores"].get("overall", 0) for r in runs]
    cac = [r["cache_hit_rate"] for r in runs]
    print(f"  {'─'*70}")
    print(f"  AVERAGES:")
    print(f"  Latency: {sum(lat)/n:.1f}s (min={min(lat):.1f} max={max(lat):.1f})")
    print(f"  Tokens:  {sum(tok)/n:.0f} (min={min(tok)} max={max(tok)})")
    print(f"  Cost:    Y{sum(cst)/n:.6f} (min=Y{min(cst):.6f} max=Y{max(cst):.6f})")
    print(f"  Score:   {sum(scr)/n:.1f} (min={min(scr):.1f} max={max(scr):.1f})")
    print(f"  Cache:   {sum(cac)/n*100:.1f}%")

    dims = ["completeness", "accuracy", "depth", "structure", "actionability", "professionalism"]
    for d in dims:
        vals = [r["scores"].get(d, 0) for r in runs]
        print(f"  {d}: avg={sum(vals)/n:.1f} (range: {min(vals)}-{max(vals)})")

print(f"\n{'='*80}")
print("FAILURES")
print(f"{'='*80}")
for r in data:
    if not r.get("success"):
        err = r.get("error", "unknown")[:200]
        print(f"  R{r['round']} {r['scenario']} | {r['framework']} {r['mode']}: {err}")
