# Thinking Stress Benchmark v1

Code repair closed-loop benchmark that proves DeepSeek thinking mode value through engineering execution tasks.

## Paradigm

```
Old: give info → call tools → write report → LLM judge scores
New: give broken repo → read code → run tests → locate root cause →
     patch code → regress → hidden tests accept
```

## Quick Start

```bash
export DEEPSEEK_API_KEY="sk-..."

# Smoke test — single fast run
python -m benchmarks.thinking_stress_v1.runner --rounds 1 --frameworks seekflow_fast_no_thinking

# Full comparison — 3 rounds x 3 configurations
python -m benchmarks.thinking_stress_v1.runner --rounds 3 --frameworks seekflow_stable_thinking,seekflow_stable_no_thinking,seekflow_fast_no_thinking

# Generate report
python -m benchmarks.thinking_stress_v1.report output/thinking_stress_YYYYMMDD_HHMMSS.json
```

## Comparison Groups

| Group | thinking | mode | max_steps | Purpose |
|-------|----------|------|-----------|---------|
| stable-thinking | True | stable | 30 | Experimental |
| stable-no-thinking | False | stable | 30 | Isolate thinking variable |
| fast-no-thinking | False | fast | 16 | Lightweight baseline |

## Scoring (100 points)

| Dimension | Points | Method |
|-----------|--------|--------|
| A. Public tests | 25 | `pytest tests/` — agent visible |
| B. Hidden tests | 30 | `pytest hidden_tests/` — agent invisible |
| C. Static scan | 10 | Pattern-based security scan |
| D. Tool process | 15 | Audit log compliance check |
| E. Patch quality | 10 | No test tampering, no eval/shell injection |
| F. Final report | 10 | Section completeness check |

## Success Criteria

- stable-thinking avg total ≥ stable-no-thinking + 10 pts
- stable-thinking hidden pass rate ≥ stable-no-thinking + 15%

## Fixture Repo

7 deliberately buggy modules in `fixture_repo/src/mini_agent_runtime/`:

| Module | Bug |
|--------|-----|
| messages.py | Drops reasoning_content from assistant messages |
| tool_runtime.py | Returns parallel results in completion order |
| security.py | Path traversal + SSRF bypass (6 vectors) |
| redaction.py | Only redacts sk- keys, misses 4 credential types |
| cache_cost.py | Timestamp in cache prefix + wrong cost formula |
| policy.py | Missing policy defaults to allow |
| json_repair.py | Dangerous tool allows low-confidence repair |
