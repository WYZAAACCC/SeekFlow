"""Re-score saved benchmark outputs with strict judge rubric."""
import json, os, sys, time
from pathlib import Path

from judge import judge_output
from shared_tools import TASKS

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not API_KEY:
    print("ERROR: DEEPSEEK_API_KEY not set")
    sys.exit(1)

src = Path(__file__).parent / "output" / "_incremental_results.json"
with open(src, "r", encoding="utf-8") as f:
    data = json.load(f)

total = sum(1 for r in data if r.get("success"))
print(f"Re-scoring {total} outputs with STRICT judge...")
print()

updated = 0
for r in data:
    if not r.get("success"):
        continue

    scenario = r["scenario"]
    output = r.get("output", "")
    old_score = r["scores"].get("overall", 0)
    task = TASKS.get(scenario, "")

    fw_label = f"[{r['framework']} | {r['mode']}] R{r['round']} {scenario[:25]}"
    print(f"  {fw_label}: old={old_score:.1f} ", end="", flush=True)

    new_scores = judge_output(API_KEY, task, output)
    new_score = new_scores.get("overall", 0)
    print(f"new={new_score:.1f}")

    r["scores"] = new_scores
    updated += 1

# Save updated results
dst = Path(__file__).parent / "output" / "_incremental_results_strict.json"
with open(dst, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print(f"\nSaved {updated} re-scored results to {dst}")

# Print summary
from collections import defaultdict
groups = defaultdict(list)
for r in data:
    if r.get("success"):
        groups[(r["framework"], r["mode"])].append(r)

print(f"\n{'='*80}")
print("  STRICT JUDGE RESULTS")
print(f"{'='*80}")
print(f"{'Rank':<5} {'Framework':<14} {'Mode':<8} {'Score':>6} {'Range':>12}")
print("-" * 50)
rank = 0
for (fw, mode), runs in sorted(groups.items(), key=lambda x: sum(r['scores'].get('overall',0) for r in x[1])/len(x[1]), reverse=True):
    rank += 1
    n = len(runs)
    scr = [r['scores'].get('overall',0) for r in runs]
    mean = sum(scr)/n
    print(f"{rank:<5} {fw:<14} {mode:<8} {mean:>5.1f}  {min(scr):.1f}-{max(scr):.1f}")
