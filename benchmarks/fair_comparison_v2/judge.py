"""Cold, objective LLM judge — scores outputs on 6 dimensions with strict rubrics.

Uses deepseek-v4-pro for high-quality evaluation. Judge is BLIND — it only sees
the output text, never which framework produced it. Framework names are stripped.
"""
from __future__ import annotations

import json
import re
import time


JUDGE_MODEL = "deepseek-v4-pro"
JUDGE_TEMPERATURE = 0.0
MAX_OUTPUT_CHARS = 6000   # max chars of agent output sent to judge
MAX_TASK_CHARS = 4000      # max chars of task description sent to judge


_SCORING_RUBRIC = """You are a cold, objective judge evaluating AI agent outputs. Score each output on these 6 dimensions using STRICT rubrics. Be harsh — a 7 means "good enough for production", a 9 means "exceptional".

## Scoring Dimensions

1. **Completeness** (1-10): Did the output address ALL parts of the task?
   - 10: Every single requirement met, nothing omitted
   - 7: Most requirements met, 1-2 minor omissions
   - 4: Half the requirements met
   - 1: Most requirements ignored

2. **Accuracy** (1-10): Are the facts, numbers, and calculations correct?
   - 10: All data points verified and correct
   - 7: Minor calculation errors or approximations
   - 4: Several significant errors
   - 1: Mostly incorrect or fabricated data

3. **Depth** (1-10): Does the output show genuine analysis, not just surface-level summary?
   - 10: Multi-layered analysis with cause-effect reasoning, trade-offs explored
   - 7: Good analysis with some depth, but misses deeper implications
   - 4: Superficial treatment, mostly restating facts
   - 1: No analysis, just raw data or tool output

4. **Structure** (1-10): Is the output well-organized and easy to follow?
   - 10: Clear hierarchy, logical flow, professional formatting
   - 7: Generally well-organized but some sections need improvement
   - 4: Disorganized, hard to follow
   - 1: Incoherent or random structure

5. **Actionability** (1-10): Can the reader take concrete action based on this output?
   - 10: Specific, concrete recommendations with clear rationale
   - 7: Good recommendations but some lack specificity
   - 4: Vague suggestions without clear action items
   - 1: No actionable content

6. **Professionalism** (1-10): Is the tone, language, and presentation professional?
   - 10: Polished, precise language suitable for executive presentation
   - 7: Professional but with some rough edges
   - 4: Casual or imprecise language
   - 1: Unprofessional, contains errors in language or tone

## Output Format

You MUST return ONLY a valid JSON object. No markdown fences, no explanation, just raw JSON:

{"completeness": X, "accuracy": X, "depth": X, "structure": X, "actionability": X, "professionalism": X, "critique": "Brief explanation of scores (2-3 sentences)"}"""


def _extract_json(text: str) -> str | None:
    """Robust JSON extraction: try markdown-fence, then brace-matching."""
    # Try ```json ... ``` first
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        return m.group(1)
    # Fall back to brace-matching
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _clamp_scores(scores: dict) -> dict:
    """Clamp all dimension scores to 1-10 range."""
    for k in ("completeness", "accuracy", "depth", "structure", "actionability", "professionalism"):
        if k in scores:
            scores[k] = max(1, min(10, int(round(scores[k]))))
    return scores


def judge_output(api_key: str, task: str, output: str, max_retries: int = 3) -> dict:
    """Score an agent output using the LLM judge. Framework-agnostic."""
    if not output or len(output.strip()) < 50:
        return {
            "completeness": 0, "accuracy": 0, "depth": 0,
            "structure": 0, "actionability": 0, "professionalism": 0,
            "overall": 0.0, "critique": "Empty or insufficient output",
        }

    prompt = (
        f"{_SCORING_RUBRIC}\n\n"
        f"## Task Given to Agent\n{task[:MAX_TASK_CHARS]}\n\n"
        f"## Agent Output to Evaluate\n{output[:MAX_OUTPUT_CHARS]}\n\n"
        f"## Your Scores (JSON only)"
    )

    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=120)

    last_error = ""
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=JUDGE_MODEL,
                temperature=JUDGE_TEMPERATURE,
                max_tokens=800,
                extra_body={"thinking": {"type": "disabled"}},
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.choices[0].message.content.strip()
            json_text = _extract_json(text)
            if json_text is None:
                raise ValueError(f"No JSON found in response: {text[:200]}")
            scores = json.loads(json_text)
            required = ["completeness", "accuracy", "depth", "structure", "actionability", "professionalism"]
            if all(k in scores for k in required):
                scores = _clamp_scores(scores)
                scores["overall"] = round(sum(scores[k] for k in required) / 6, 1)
                if "critique" not in scores:
                    scores["critique"] = ""
                return scores
        except Exception as e:
            last_error = str(e)[:200]
            if attempt < max_retries:
                # Exponential backoff: 1s, 2s, 4s
                time.sleep(2 ** attempt)

    return {
        "completeness": 5, "accuracy": 5, "depth": 5,
        "structure": 5, "actionability": 5, "professionalism": 5,
        "overall": 5.0,
        "critique": f"Judge failed after {max_retries + 1} attempts: {last_error}",
    }
