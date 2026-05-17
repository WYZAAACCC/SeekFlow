"""Compare outputs across frameworks to understand quality differences. Writes to file."""
import json, sys, io
from pathlib import Path

src = Path(__file__).parent / "output" / "_incremental_results.json"
outpath = Path(__file__).parent / "output" / "comparison.txt"
with open(src, "r", encoding="utf-8") as f:
    data = json.load(f)

buf = io.StringIO()

def w(s=""):
    buf.write(s + "\n")

def compare_scenario(scenario, round_num):
    w("=" * 100)
    w(f"{scenario.upper()} ROUND {round_num} - Output Comparison")
    w("=" * 100)

    for r in data:
        if not r.get("success"):
            continue
        if r["round"] == round_num and r["scenario"] == scenario:
            fw = f"{r['framework']}/{r['mode']}"
            sc = r["scores"]
            w(f"\n{'─'*100}")
            w(f"{fw}")
            w(f"Score: {sc.get('overall',0)} | C={sc.get('completeness')} A={sc.get('accuracy')} D={sc.get('depth')} S={sc.get('structure')} Ac={sc.get('actionability')} P={sc.get('professionalism')}")
            w(f"Tokens: {r['total_tokens']} (P={r['prompt_tokens']} C={r['completion_tokens']}) | Cost: Y{r['cost_cny']:.6f}")
            w(f"Tool Calls: {r['tool_calls_count']} | Cache: {r['cache_hit_rate']*100:.1f}% | Latency: {r['latency_seconds']}s")
            w(f"Judge: {sc.get('critique', 'N/A')[:400]}")
            out = str(r.get("output", ""))
            w(f"Output Length: {len(out)} chars")
            w(f"\n--- OUTPUT (first 1500 chars) ---")
            w(out[:1500])
            w("--- END ---")

compare_scenario("financial_analyst", 1)
compare_scenario("supply_chain_analyst", 3)

# Summary table
w("\n\n" + "=" * 100)
w("SUMMARY: Why does LangChain achieve parity with fewer tokens?")
w("=" * 100)

for scenario in ["financial_analyst", "supply_chain_analyst"]:
    w(f"\n{scenario}:")
    w(f"{'Framework':<20} {'Score':>6} {'Tokens':>8} {'TC':>4} {'Cost':>10} {'P_tok':>10} {'C_tok':>10} {'Cache%':>8}")
    w("-" * 80)
    for r in data:
        if not r.get("success"):
            continue
        if r["scenario"] == scenario:
            fw = f"{r['framework']}/{r['mode']}"
            sc = r["scores"].get("overall", 0)
            tok = r["total_tokens"]
            tc = r["tool_calls_count"]
            cost = r["cost_cny"]
            ptok = r["prompt_tokens"]
            ctok = r["completion_tokens"]
            cache = r["cache_hit_rate"] * 100
            w(f"{fw:<20} {sc:>5.1f}  {tok:>8} {tc:>4} {cost:>9.6f} {ptok:>10} {ctok:>10} {cache:>7.1f}%")

with open(outpath, "w", encoding="utf-8") as f:
    f.write(buf.getvalue())
print(f"Written to {outpath}")
