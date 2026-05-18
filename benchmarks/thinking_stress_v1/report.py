"""Markdown report generator for Thinking Stress Benchmark v1.

Usage:
    python -m benchmarks.thinking_stress_v1.report output/thinking_stress_YYYYMMDD_HHMMSS.json
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path


def generate_report(results_json: dict) -> str:
    """Generate a Markdown report from benchmark results dict."""
    benchmark = results_json.get("benchmark", "?")
    scenario = results_json.get("scenario", "?")
    created = results_json.get("created_at", "?")
    rounds = results_json.get("rounds", 0)
    results = results_json.get("results", [])
    summary = results_json.get("summary", {})

    lines = []

    def w(text: str = ""):
        lines.append(text)

    # ── Title ──
    w(f"# {benchmark} — 报告")
    w()
    w(f"**场景**: {scenario} | **生成时间**: {created} | **轮次**: {rounds}")
    w()

    # ── Summary table ──
    w("## 一、总体结果")
    w()
    successful = [r for r in results if r.get("success") and r.get("score", {}).get("total")]
    failed = [r for r in results if not r.get("success")]

    w(f"- 成功运行: {len(successful)} / {len(results)}")
    w(f"- 失败运行: {len(failed)}")
    w()

    w("| 模式 | 轮次 | 总分 | 公开测试 | 隐藏测试 | 静态扫描 | 工具流程 | Patch | 报告 | 延迟(s) | Token | 成本(Y) |")
    w("|------|------|------|----------|----------|----------|----------|-------|------|---------|-------|---------|")

    for r in sorted(successful, key=lambda x: (x.get("mode", ""), x.get("round", 0))):
        s = r.get("score", {})
        t = r.get("tokens", {})
        tests = r.get("tests", {})
        pub = tests.get("public", {})
        hid = tests.get("hidden", {})
        pub_str = f"{pub.get('passed', 0)}/{pub.get('total', 0)}" if pub else "-"
        hid_str = f"{hid.get('passed', 0)}/{hid.get('total', 0)}" if hid else "-"

        w(f"| {r['mode']} | R{r['round']} | "
          f"**{s.get('total', '-')}** | "
          f"{s.get('public_tests', '-')} ({pub_str}) | "
          f"{s.get('hidden_tests', '-')} ({hid_str}) | "
          f"{s.get('static_scan', '-')} | "
          f"{s.get('tool_process', '-')} | "
          f"{s.get('patch_quality', '-')} | "
          f"{s.get('final_report', '-')} | "
          f"{r['latency_s']:.0f} | "
          f"{t.get('total', 0)} | "
          f"{r['cost_cny']:.6f} |")

    w()

    # ── Mode averages ──
    w("## 二、模式平均")
    w()
    w("| 模式 | 运行数 | 平均总分 | 公开通过率 | 隐藏通过率 | 平均延迟 | 平均Token | 平均成本 |")
    w("|------|--------|----------|------------|------------|----------|-----------|----------|")

    for mode, stats in sorted(summary.items()):
        if not isinstance(stats, dict):
            continue
        w(f"| {mode} | {stats.get('runs', 0)} | "
          f"**{stats.get('avg_total_score', '-')}** | "
          f"{stats.get('avg_public_pass_rate', '-')}% | "
          f"{stats.get('avg_hidden_pass_rate', '-')}% | "
          f"{stats.get('avg_latency_s', '-')}s | "
          f"{stats.get('avg_tokens', '-')} | "
          f"Y{stats.get('avg_cost_cny', 0):.6f} |")

    w()

    # ── Thinking delta ──
    thinking_delta = summary.get("thinking_delta_vs_stable_no_thinking")
    hidden_delta = summary.get("hidden_delta")
    if thinking_delta is not None:
        w("## 三、Thinking 增益分析")
        w()
        w(f"- **总分 delta (stable-thinking vs stable-no-thinking)**: {thinking_delta:+.1f} 分")
        if hidden_delta is not None:
            w(f"- **隐藏测试通过率 delta**: {hidden_delta:+.1f}%")
        w()

        if thinking_delta >= 10:
            w("结论: thinking 在复杂工程闭环任务中表现出**显著优势**。")
        elif thinking_delta >= 5:
            w("结论: thinking 表现出**中等优势**，但差距不够强。")
        else:
            w("结论: thinking **未显示出显著优势**，v4-pro 裸推理已足够处理此任务。")
        w()

    # ── Round consistency ──
    w("## 四、轮次一致性")
    w()
    by_mode_round = defaultdict(lambda: defaultdict(list))
    for r in successful:
        by_mode_round[r["mode"]][r["round"]].append(r["score"]["total"])

    w("| 模式 | 各轮分数 | 均值 | 标准差 |")
    w("|------|----------|------|--------|")
    for mode in sorted(by_mode_round.keys()):
        scores_per_round = []
        for rnd in sorted(by_mode_round[mode].keys()):
            avg = sum(by_mode_round[mode][rnd]) / len(by_mode_round[mode][rnd])
            scores_per_round.append(avg)
        mean = sum(scores_per_round) / len(scores_per_round) if scores_per_round else 0
        std = (sum((s - mean) ** 2 for s in scores_per_round) / len(scores_per_round)) ** 0.5 if len(scores_per_round) > 1 else 0
        w(f"| {mode} | {[f'{s:.1f}' for s in scores_per_round]} | {mean:.1f} | {std:.2f} |")
    w()

    # ── Failure details ──
    if failed:
        w("## 五、失败运行")
        w()
        for r in failed:
            w(f"- **R{r.get('round', '?')} {r.get('mode', '?')}**: {r.get('raw_error', 'unknown')[:200]}")
        w()

    # ── Cost efficiency ──
    w("## 六、成本效率")
    w()
    w("| 模式 | 每分成本(Y) | 每隐藏测试成本(Y) |")
    w("|------|-------------|-------------------|")
    for mode, stats in sorted(summary.items()):
        if not isinstance(stats, dict):
            continue
        total = stats.get("avg_total_score", 0)
        cost = stats.get("avg_cost_cny", 0)
        hidden_rate = stats.get("avg_hidden_pass_rate", 0)
        per_point = cost / total if total > 0 else 0
        per_hidden = cost / (hidden_rate / 100 * 30) if hidden_rate > 0 else 0
        w(f"| {mode} | Y{per_point:.6f} | Y{per_hidden:.6f} |")
    w()

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        # Try to find latest output
        output_dir = Path(__file__).parent / "output"
        json_files = sorted(output_dir.glob("thinking_stress_*.json"))
        # Exclude incremental files
        json_files = [f for f in json_files if "incremental" not in f.name]
        if json_files:
            input_path = json_files[-1]
        else:
            print("Usage: python -m benchmarks.thinking_stress_v1.report <results.json>")
            sys.exit(1)
    else:
        input_path = Path(sys.argv[1])

    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    report = generate_report(data)

    # Save report next to the JSON
    report_path = input_path.with_suffix(".md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"Report saved to: {report_path}")
    print()
    print(report)


if __name__ == "__main__":
    main()
