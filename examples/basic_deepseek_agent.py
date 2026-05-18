"""Basic DeepSeek Agent — 3 lines to a running agent.

Prerequisites:
    pip install seekflow
    export DEEPSEEK_API_KEY="sk-..."

Run:
    python examples/basic_deepseek_agent.py
"""

import os
from seekflow import DeepSeekAgent

api_key = os.environ.get("DEEPSEEK_API_KEY", "sk-xxx")

# ── 3 lines to a running agent ──
agent = DeepSeekAgent(
    role="analyst",
    goal="analyze data and give advice",
    backstory="experienced data analyst",
    api_key=api_key,
    model="deepseek-v4-pro",
)
agent.with_default_tools()  # loads calculate, parse_csv, extract_entities, classify_text

# ── Run ──
result = agent.run("Calculate the ROI: investment $500k, revenue $870k")

print(f"Final output:\n{result.final_output}")
print(f"\nTokens: {result.tokens.get('total_tokens', 0)}")
print(f"Cost: Y{result.cost:.6f}")
print(f"Latency: {result.diagnostics.cache_hit_rate:.1%} cache hit rate")


# ── Add more tools ──
# agent2 = DeepSeekAgent(
#     role="researcher", goal="search and analyze", backstory="senior researcher",
#     api_key=api_key, model="deepseek-v4-pro",
#     dangerous_tools=True,  # enable file/network/code tools
# )
# agent2.with_default_tools()
# agent2.allow_filesystem(root="/workspace")
# agent2.allow_network(domains={"api.example.com"})
# agent2.allow_python(sandbox=ProcessSandbox())
