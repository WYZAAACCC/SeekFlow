"""Shared utilities for demo scripts — judge, formatting, result tracking."""
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
MODEL = "deepseek-chat"
JUDGE_MODEL = "deepseek-v4-pro"

# deepseek-chat pricing (CNY per 1M)
PRICE_UNCACHED = 0.14 / 1_000_000
PRICE_CACHED = 0.014 / 1_000_000
PRICE_OUTPUT = 0.28 / 1_000_000

OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


@dataclass
class RunResult:
    framework: str
    scenario: str
    success: bool = True
    error: str = ""
    latency_s: float = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    api_calls: int = 0
    output: str = ""
    output_len: int = 0
    cost_uncached: float = 0.0
    cost_cached: float = 0.0
    cost_output: float = 0.0
    cost_total: float = 0.0
    scores: dict = field(default_factory=dict)

    def calc_cost(self):
        uncached_p = max(self.prompt_tokens - self.cached_tokens, 0)
        self.cost_uncached = uncached_p * PRICE_UNCACHED
        self.cost_cached = self.cached_tokens * PRICE_CACHED
        self.cost_output = self.completion_tokens * PRICE_OUTPUT
        self.cost_total = self.cost_uncached + self.cost_cached + self.cost_output


SCORING_RUBRIC = """You are a cold, objective judge. Score 1-10 on 6 dimensions:

1. Completeness: All task requirements met? (10=everything, 1=nothing)
2. Accuracy: Facts/numbers/calculations correct? (10=perfect, 1=wrong)
3. Depth: Genuine analysis vs surface summary? (10=deep insights, 1=shallow)
4. Structure: Well-organized? (10=professional hierarchy, 1=chaotic)
5. Actionability: Concrete recommendations? (10=specific steps, 1=vague)
6. Professionalism: Tone and presentation? (10=executive-ready, 1=unprofessional)

Return ONLY JSON: {"completeness":X,"accuracy":X,"depth":X,"structure":X,"actionability":X,"professionalism":X,"overall":X.X,"critique":"2-3 sentences"}"""


def judge_output(task: str, output: str) -> dict:
    if not output or len(output.strip()) < 50:
        return {"completeness": 0, "accuracy": 0, "depth": 0, "structure": 0,
                "actionability": 0, "professionalism": 0, "overall": 0.0,
                "critique": "Insufficient output"}

    from openai import OpenAI
    client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com", timeout=120)
    prompt = f"{SCORING_RUBRIC}\n\nTask:\n{task[:2000]}\n\nOutput:\n{output[:6000]}\n\nScores (JSON only):"

    for _ in range(3):
        try:
            r = client.chat.completions.create(
                model=JUDGE_MODEL, temperature=0.0, max_tokens=800,
                extra_body={"thinking": {"type": "disabled"}},
                messages=[{"role": "user", "content": prompt}],
            )
            text = r.choices[0].message.content.strip()
            if "{" in text: text = text[text.index("{"):text.rindex("}") + 1]
            scores = json.loads(text)
            req = ["completeness", "accuracy", "depth", "structure", "actionability", "professionalism"]
            if all(k in scores for k in req):
                scores["overall"] = round(sum(scores[k] for k in req) / 6, 1)
                return scores
        except Exception:
            time.sleep(1)
    return {"completeness": 5, "accuracy": 5, "depth": 5, "structure": 5,
            "actionability": 5, "professionalism": 5, "overall": 5.0,
            "critique": "Judge unavailable"}


def print_result(label: str, rr: RunResult):
    print(f"\n{'─'*60}")
    print(f"[{label}]")
    print(f"{'─'*60}")
    if not rr.success:
        print(f"  FAILED: {rr.error}"); return
    cache_pct = f"{rr.cached_tokens/max(rr.prompt_tokens,1)*100:.0f}%"
    print(f"  Time: {rr.latency_s:.1f}s | API calls: {rr.api_calls}")
    print(f"  Tokens: {rr.total_tokens} (P:{rr.prompt_tokens} C:{rr.completion_tokens})")
    print(f"  Cache: {rr.cached_tokens} ({cache_pct})")
    print(f"  Cost: CNY{rr.cost_total:.6f} (uncached CNY{rr.cost_uncached:.6f} + cached CNY{rr.cost_cached:.6f} + output CNY{rr.cost_output:.6f})")
    print(f"  Output: {rr.output_len} chars")
    if rr.scores:
        s = rr.scores
        print(f"  Quality: overall={s.get('overall')} C={s.get('completeness')} A={s.get('accuracy')} D={s.get('depth')} S={s.get('structure')} Ac={s.get('actionability')} P={s.get('professionalism')}")


def print_comparison(title: str, results: list[RunResult]):
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"  Model: {MODEL} | Judge: {JUDGE_MODEL} | Temp: 0.0")
    print(f"{'='*80}")
    print(f"{'Framework':<22} {'Time':>6} {'Tokens':>7} {'Cache':>6} {'Cost':>10} {'Score':>6} {'C':>3} {'A':>3} {'D':>3}")
    print("-" * 78)
    for r in sorted(results, key=lambda x: x.scores.get("overall", 0), reverse=True):
        if not r.success: continue
        s = r.scores
        cp = f"{r.cached_tokens/max(r.prompt_tokens,1)*100:.0f}%"
        print(f"{r.framework:<22} {r.latency_s:>5.1f}s {r.total_tokens:>7} {cp:>6} CNY{r.cost_total:>8.6f} {s.get('overall',0):>5.1f} {s.get('completeness',0):>3} {s.get('accuracy',0):>3} {s.get('depth',0):>3}")
    print()


def save_results(results: list[RunResult], name: str):
    path = OUTPUT_DIR / f"{name}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    data = [{"framework": r.framework, "scenario": r.scenario, "latency_s": r.latency_s,
             "tokens": r.total_tokens, "prompt": r.prompt_tokens, "completion": r.completion_tokens,
             "cached": r.cached_tokens, "cost": r.cost_total, "scores": r.scores,
             "output": r.output[:1000]} for r in results if r.success]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Results: {path}")
