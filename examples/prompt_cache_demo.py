"""Prompt Cache Demo — 90%+ cache hit rate with CacheCompiler.

DeepSeek charges 0.028 CNY/M tokens for cached input vs 1.74 CNY/M for uncached.
SeekFlow's CacheCompiler keeps the prefix stable so cache hits stay high.

Run:
    python examples/prompt_cache_demo.py
"""

import os
from seekflow import DeepSeekAgent
from seekflow.cache import CacheCompiler

api_key = os.environ.get("DEEPSEEK_API_KEY", "sk-xxx")

# ── Build a stable cache prefix ──
compiler = CacheCompiler()

agent = DeepSeekAgent(
    role="document analyst",
    goal="quickly and accurately extract key information from documents",
    backstory="expert analyst proficient in multiple document formats",
    api_key=api_key,
    model="deepseek-v4-pro",
)
agent.with_default_tools()

# ── First call: populates cache ──
print("First call (cold cache)...")
r1 = agent.run("Summarize three key points: SeekFlow is a DeepSeek-native zero-trust tool gateway.")
print(f"  Cost: Y{r1.cost:.6f}")

# ── Second call: hits cache ──
print("Second call (warm cache)...")
r2 = agent.run("Summarize: SeekFlow provides production-grade reliability for DeepSeek agents.")
print(f"  Cost: Y{r2.cost:.6f}")

if hasattr(r2.diagnostics, 'cache_hit_rate'):
    hit_rate = r2.diagnostics.cache_hit_rate
    print(f"\nCache hit rate: {hit_rate:.1%}")
    if hit_rate > 0.8:
        print("Cache is working! Significant cost savings on repeated calls.")
    else:
        print("Cache not yet warm. Try running more calls with the same system prompt.")
