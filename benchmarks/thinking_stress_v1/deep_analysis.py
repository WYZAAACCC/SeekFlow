"""Comprehensive cross-experiment analysis of all benchmark data."""
import json
from collections import defaultdict
from dataclasses import dataclass

@dataclass
class RunData:
    run_id: str
    mode: str
    round_num: int
    scoring: str
    total: float
    pub_passed: int
    pub_total: int
    hid_passed: int
    hid_total: int
    static_scan: float
    tool_process: float
    patch_quality: float
    report: float
    latency: float
    tokens: int
    cost: float
    tool_calls: int = 0

original_runs = [
    RunData('R1','fast-no-thinking',1,'original',63.2,27,36,16,26,5.0,11.0,10.0,0,211,37780,0.008,28),
    RunData('R2','fast-no-thinking',1,'original',70.6,36,36,17,26,5.0,11.0,10.0,0,320,319876,0.059,35),
    RunData('R3','stable-no-thinking',1,'original',69.9,35,36,17,26,5.0,11.0,10.0,0,398,431204,0.074,40),
    RunData('R4','stable-thinking',1,'original',74.5,32,36,15,26,5.0,11.0,10.0,9.0,1163,725992,0.129,44),
    RunData('R5','stable-no-thinking',2,'original',69.9,35,36,17,26,5.0,11.0,10.0,0,401,428567,0.073,40),
    RunData('R6','stable-thinking',2,'original',81.1,35,36,18,26,5.0,12.0,10.0,9.0,755,598542,0.113,47),
    RunData('R7','fast-no-thinking',2,'original',70.6,36,36,17,26,5.0,11.0,10.0,0,395,327835,0.070,41),
    RunData('R8','fast-no-thinking',3,'original',70.6,36,36,17,26,5.0,11.0,10.0,0,373,380486,0.067,39),
    RunData('R9','stable-thinking',3,'original',81.6,36,36,17,26,5.0,13.0,10.0,9.0,1032,693569,0.135,52),
]

improved_runs = [
    RunData('I1','stable-no-thinking',1,'improved',78.7,36,36,24,33,5.0,11.0,10.0,0,391,434438,0.074,40),
    RunData('I2','stable-thinking',1,'improved',85.2,36,36,24,33,5.0,13.0,10.0,4.5,708,715661,0.133,44),
    RunData('I3','fast-no-thinking',1,'improved',80.1,36,36,25,33,5.0,11.0,10.0,0,326,324218,0.059,35),
    RunData('I4','stable-no-thinking',2,'improved',80.1,36,36,25,33,5.0,11.0,10.0,0,403,439294,0.075,40),
    RunData('I5','stable-thinking',2,'improved',88.3,36,36,27,33,5.0,12.0,10.0,4.5,699,667656,0.118,47),
    RunData('I6','fast-no-thinking',2,'improved',78.7,36,36,24,33,5.0,11.0,10.0,0,319,269964,0.061,35),
]

orig_by_mode = defaultdict(list)
for r in original_runs: orig_by_mode[r.mode].append(r)
imp_by_mode = defaultdict(list)
for r in improved_runs: imp_by_mode[r.mode].append(r)

print("=" * 90)
print("  THINKING STRESS BENCHMARK — COMPREHENSIVE CROSS-EXPERIMENT ANALYSIS")
print("=" * 90)

# 1. Hidden test rate evolution
print("\n## 1. Hidden Test Pass Rate: From Unfixed to Improved")
print(f"  Unfixed baseline:         8/26 = 30.8%")
print(f"  Early smoke (fast, 16step): 16/26 = 61.5%")
print()
print(f"  {'Mode':25s} {'Original (26 tests)':>30} {'Improved (33 tests)':>30}")
print(f"  {'':25s} {'R1':>6} {'R2':>6} {'R3':>6} {'Avg':>8}   {'R1':>6} {'R2':>6} {'Avg':>8}")
for mode in ['stable-thinking', 'stable-no-thinking', 'fast-no-thinking']:
    o = orig_by_mode[mode]
    i = imp_by_mode[mode]
    o_vals = [f"{r.hid_passed}/{r.hid_total}" for r in sorted(o, key=lambda x: x.round_num)]
    i_vals = [f"{r.hid_passed}/{r.hid_total}" for r in sorted(i, key=lambda x: x.round_num)]
    o_avg = sum(r.hid_passed for r in o) / sum(r.hid_total for r in o) * 100
    i_avg = sum(r.hid_passed for r in i) / sum(r.hid_total for r in i) * 100
    o_str = " ".join(f"{v:>6}" for v in o_vals) + f"  {o_avg:>6.1f}%"
    i_str = " ".join(f"{v:>6}" for v in i_vals) + f"  {i_avg:>6.1f}%"
    print(f"  {mode:25s} {o_str}   {i_str}")

# 2. Score breakdown
print("\n## 2. Score Component Analysis")
for label, runs_list in [("ORIGINAL (pub=25, hid=30, report=10)", original_runs),
                           ("IMPROVED (pub=20, hid=45, report=5)", improved_runs)]:
    print(f"\n  --- {label} ---")
    by_mode = defaultdict(list)
    for r in runs_list: by_mode[r.mode].append(r)
    print(f"  {'Mode':25s} {'Total':>6} {'Pub':>6} {'Hid':>6} {'Static':>7} {'Process':>8} {'Patch':>6} {'Report':>7}")
    for mode in ['stable-thinking', 'stable-no-thinking', 'fast-no-thinking']:
        runs = by_mode[mode]
        n = len(runs)
        print(f"  {mode:25s} {sum(r.total for r in runs)/n:>6.1f} "
              f"{sum(r.total*0/(r.pub_total) or 0 for r in runs):>6}"
              f"  {sum(r.hid_passed for r in runs)/sum(r.hid_total for r in runs)*100:>5.1f}% "
              f"{sum(r.static_scan for r in runs)/n:>7.1f} "
              f"{sum(r.tool_process for r in runs)/n:>8.1f} "
              f"{sum(r.patch_quality for r in runs)/n:>6.1f} "
              f"{sum(r.report for r in runs)/n:>7.1f}")

# 3. Thinking delta
print("\n## 3. Thinking Delta: Does Thinking Help Code Repair?")
print(f"  {'Metric':35s} {'Original':>12} {'Improved':>12} {'Delta':>12}")
o_st = orig_by_mode['stable-thinking']
o_sn = orig_by_mode['stable-no-thinking']
o_st_hid = sum(r.hid_passed for r in o_st) / sum(r.hid_total for r in o_st) * 100
o_sn_hid = sum(r.hid_passed for r in o_sn) / sum(r.hid_total for r in o_sn) * 100
o_st_tot = sum(r.total for r in o_st) / len(o_st)
o_sn_tot = sum(r.total for r in o_sn) / len(o_sn)

i_st = imp_by_mode['stable-thinking']
i_sn = imp_by_mode['stable-no-thinking']
i_st_hid = sum(r.hid_passed for r in i_st) / sum(r.hid_total for r in i_st) * 100
i_sn_hid = sum(r.hid_passed for r in i_sn) / sum(r.hid_total for r in i_sn) * 100
i_st_tot = sum(r.total for r in i_st) / len(i_st)
i_sn_tot = sum(r.total for r in i_sn) / len(i_sn)

print(f"  {'Hidden test pass rate delta':35s} {o_st_hid-o_sn_hid:>+11.1f}% {i_st_hid-i_sn_hid:>+11.1f}% {(i_st_hid-i_sn_hid)-(o_st_hid-o_sn_hid):>+11.1f}%")
print(f"  {'Total score delta':35s} {o_st_tot-o_sn_tot:>+11.1f}  {i_st_tot-i_sn_tot:>+11.1f}  {(i_st_tot-i_sn_tot)-(o_st_tot-o_sn_tot):>+11.1f}")
print(f"  {'Hidden tests passed (avg) delta':35s} {'N/A':>12} {sum(r.hid_passed for r in i_st)/len(i_st) - sum(r.hid_passed for r in i_sn)/len(i_sn):>+11.1f} {'N/A':>12}")
print()
print(f"  CRITICAL: Original hidden delta was NEGATIVE ({o_st_hid-o_sn_hid:+.1f}%) — thinking was WORSE")
print(f"  Improved hidden delta is positive ({i_st_hid-i_sn_hid:+.1f}%) — thinking is slightly BETTER")
print(f"  But the magnitude is tiny: only ~1 extra hidden test passed on average")

# 4. Where thinking actually wins
print("\n## 4. Decomposing Thinking's Advantage")
print(f"  {'Component':30s} {'Original Δ':>12} {'Improved Δ':>12}")
o_report_delta = (sum(r.report for r in o_st)/len(o_st)) - (sum(r.report for r in o_sn)/len(o_sn))
i_report_delta = (sum(r.report for r in i_st)/len(i_st)) - (sum(r.report for r in i_sn)/len(i_sn))
o_process_delta = (sum(r.tool_process for r in o_st)/len(o_st)) - (sum(r.tool_process for r in o_sn)/len(o_sn))
i_process_delta = (sum(r.tool_process for r in i_st)/len(i_st)) - (sum(r.tool_process for r in i_sn)/len(i_sn))
print(f"  {'Report quality':30s} {o_report_delta:>+11.1f}  {i_report_delta:>+11.1f}")
print(f"  {'Tool process':30s} {o_process_delta:>+11.1f}  {i_process_delta:>+11.1f}")
print(f"  {'Hidden tests (actual repair)':30s} {o_st_hid-o_sn_hid:>+11.1f}% {i_st_hid-i_sn_hid:>+11.1f}%")
print()
print(f"  In original scoring, {o_report_delta:.0f}/{o_st_tot-o_sn_tot:.1f} = {o_report_delta/(o_st_tot-o_sn_tot)*100:.0f}% of delta was from report")
print(f"  In improved scoring, {i_report_delta:.0f}/{i_st_tot-i_sn_tot:.1f} = {i_report_delta/(i_st_tot-i_sn_tot)*100:.0f}% of delta was from report")

# 5. Fast vs Stable (both no-thinking)
print("\n## 5. Fast vs Stable (Both No-Thinking) — Does Stable Mode Help?")
for label, runs_list in [("original", original_runs), ("improved", improved_runs)]:
    by_mode = defaultdict(list)
    for r in runs_list: by_mode[r.mode].append(r)
    fast = by_mode['fast-no-thinking']
    stable = by_mode['stable-no-thinking']
    if fast and stable:
        f_tot = sum(r.total for r in fast) / len(fast)
        s_tot = sum(r.total for r in stable) / len(stable)
        f_hid = sum(r.hid_passed for r in fast) / sum(r.hid_total for r in fast) * 100
        s_hid = sum(r.hid_passed for r in stable) / sum(r.hid_total for r in stable) * 100
        f_lat = sum(r.latency for r in fast) / len(fast)
        s_lat = sum(r.latency for r in stable) / len(stable)
        f_cost = sum(r.cost for r in fast) / len(fast)
        s_cost = sum(r.cost for r in stable) / len(stable)
        print(f"  {label:10s}: fast={f_tot:.1f} (hid={f_hid:.1f}%) vs stable={s_tot:.1f} (hid={s_hid:.1f}%) "
              f"| fast is {f_lat:.0f}s vs stable {s_lat:.0f}s | cost: Y{f_cost:.6f} vs Y{s_cost:.6f}")
print()
print(f"  Stable mode provides NO measurable advantage in code repair quality")
print(f"  Both modes achieve identical hidden test pass rates")
print(f"  Fast is 20% faster and 20% cheaper with same quality")

# 6. Consistency
print("\n## 6. Round Consistency (key for benchmark reliability)")
for mode in ['stable-thinking', 'stable-no-thinking', 'fast-no-thinking']:
    for label, runs in [('  original', orig_by_mode[mode]), ('  improved', imp_by_mode[mode])]:
        totals = [r.total for r in runs]
        hids = [r.hid_passed for r in runs]
        if len(totals) > 1:
            mean = sum(totals) / len(totals)
            std = (sum((t-mean)**2 for t in totals) / len(totals)) ** 0.5
            print(f"  {mode:25s} {label}: total={mean:.1f}+-{std:.1f}  hid_passed={hids}  latency_range={min(r.latency for r in runs):.0f}-{max(r.latency for r in runs):.0f}s")

# 7. Cost efficiency
print("\n## 7. Cost Efficiency (improved benchmark)")
print(f"  {'Mode':25s} {'Cost/run':>10} {'Score':>7} {'Y/point':>10} {'Y/hidden':>10} {'Score/Y':>10}")
for mode in ['stable-thinking', 'stable-no-thinking', 'fast-no-thinking']:
    runs = imp_by_mode[mode]
    avg_cost = sum(r.cost for r in runs) / len(runs)
    avg_score = sum(r.total for r in runs) / len(runs)
    avg_hid = sum(r.hid_passed for r in runs) / len(runs)
    cost_per_point = avg_cost / avg_score
    cost_per_hid = avg_cost / avg_hid
    score_per_cost = avg_score / avg_cost
    print(f"  {mode:25s} Y{avg_cost:>8.6f} {avg_score:>6.1f} Y{cost_per_point:>8.6f} Y{cost_per_hid:>8.6f} {score_per_cost:>9.0f}")

# 8. Key insights
print("\n" + "=" * 90)
print("  KEY INSIGHTS & RECOMMENDATIONS")
print("=" * 90)
print()
print("  1. THE CEILING EFFECT:")
print("     All three modes hit the same ~75% hidden test ceiling.")
print("     This is the v4-pro model's code repair capability limit, NOT a framework limit.")
print("     Thinking adds +1 hidden test (statistically marginal).")
print()
print("  2. WHERE THINKING ACTUALLY WINS:")
print("     - Report writing: 100% of non-thinking runs hit max_steps with no report")
print("     - Tool workflow: thinking uses search_code and get_diff (exploratory tools)")
print("     - Non-thinking skips these to save steps, identical code fix results")
print()
print("  3. THE 'STABLE MODE MYTH':")
print("     stable-no-thinking and fast-no-thinking have IDENTICAL hidden test pass rates.")
print("     Stable mode's engineering advantages (cache, policy, JSON repair) don't translate")
print("     to better code repair in this task. Fast mode is strictly more efficient.")
print()
print("  4. THE REPORT TAX:")
print("     In original scoring, report quality was 9/10 for thinking vs 0 for non-thinking.")
print("     This single dimension accounted for 90% of thinking's score advantage.")
print("     After rebalancing (10->5 pts), the gap narrowed but thinking still wins here.")
print()
print("  5. WHAT WOULD PROVE THINKING:")
print("     - Bugs requiring MULTI-STEP causal chains (A fixes B, B reveals C, C needs D)")
print("     - Bugs where the WRONG fix is tempting but breaks something else")
print("     - Bugs requiring understanding of PROTOCOL STATE MACHINES (not domain knowledge)")
print("     - Current bugs are mostly 'find pattern → apply fix' (single-step)")
print()
print("  6. NEXT BENCHMARK DESIGN:")
print("     - Add a 'trap' bug: fix appears correct for public tests but breaks hidden tests")
print("     - Add a 'regression chain': fix bug A → discover bug B via new test failure")
print("     - Limit max_steps for ALL modes to 20 (currently thinking has 30, others 24-30)")
print("     - Add a 'correct fix verification' hidden test (check the approach, not just outcome)")
