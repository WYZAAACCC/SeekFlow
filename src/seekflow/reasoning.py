"""Reasoning content inspector and harvester for DeepSeek R1/V3/V4 models.

DeepSeek's reasoning models produce verbose thinking chains (reasoning_content).
This module provides two levels of analysis:

1. Consistency check — detect when reasoning mentions tools that weren't called
2. Thought harvesting — extract structured insights: subgoals, hypotheses,
   uncertainties, rejected paths, and tool plans (Reasonix Pillar 2 inspired)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════════════════
# Thought Harvesting (Reasonix Pillar 2)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class HarvestedThoughts:
    """Structured insights extracted from reasoning_content.

    These can be injected into subsequent prompts to give the model
    a "memory" of its own reasoning without passing back the full
    verbose thinking chain (which costs 400-800 tokens per turn).
    """
    subgoals: list[str] = field(default_factory=list)
    hypotheses: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    rejected_paths: list[str] = field(default_factory=list)
    tool_plan: list[str] = field(default_factory=list)
    key_findings: list[str] = field(default_factory=list)
    error_notes: list[str] = field(default_factory=list)
    summary: str = ""

    def format_for_prompt(self) -> str:
        """Format harvested thoughts as a compact prompt prefix."""
        parts: list[str] = []
        if self.key_findings:
            parts.append(f"Findings: {'; '.join(self.key_findings[:5])}")
        if self.subgoals:
            parts.append(f"Next: {'; '.join(self.subgoals[:3])}")
        if self.uncertainties:
            parts.append(f"Uncertain: {'; '.join(self.uncertainties[:3])}")
        if self.rejected_paths:
            parts.append(f"Avoided: {'; '.join(self.rejected_paths[:2])}")
        if self.error_notes:
            parts.append(f"Errors: {'; '.join(self.error_notes[:2])}")
        return " | ".join(parts) if parts else ""

    @property
    def is_empty(self) -> bool:
        return not any([
            self.subgoals, self.hypotheses,
            self.key_findings, self.error_notes,
        ])


def harvest_thoughts(reasoning: str) -> HarvestedThoughts:
    """Extract structured decision points from verbose reasoning content.

    Uses lightweight regex heuristics — no LLM call needed.
    Returns a HarvestedThoughts object that can be formatted into
    a compact summary for subsequent prompt injection.
    """
    if not reasoning or len(reasoning) < 50:
        return HarvestedThoughts()

    ht = HarvestedThoughts()

    # 1. Extract subgoals / action plans
    # Patterns: "I need to...", "I should...", "Next, I will...", "需要...", "接下来..."
    subgoal_patterns = [
        r'(?:I need to|I should|I will|Next,? I|需要|接下来|下一步|首先|然后)\s+([^。.!！?\n]{10,120})',
        r'(?:plan|goal|目标|计划).{0,10}?(?:is|:)\s+([^。.!！?\n]{10,120})',
    ]
    for pat in subgoal_patterns:
        for m in re.finditer(pat, reasoning[:2000], re.IGNORECASE):
            text = m.group(1).strip()
            if len(text) > 10 and text not in ht.subgoals:
                ht.subgoals.append(text[:120])

    # 2. Extract hypotheses / assumptions
    # Patterns: "I think...", "maybe...", "perhaps...", "假设...", "可能..."
    hypo_patterns = [
        r'(?:I think|maybe|perhaps|possibly|假设|可能|或许|大概)\s+([^。.!！?\n]{10,120})',
        r'(?:assumption|hypothesis|前提).{0,10}?(?:is|:)\s+([^。.!！?\n]{10,120})',
    ]
    for pat in hypo_patterns:
        for m in re.finditer(pat, reasoning[:2000], re.IGNORECASE):
            text = m.group(1).strip()
            if len(text) > 10 and text not in ht.hypotheses:
                ht.hypotheses.append(text[:120])

    # 3. Extract uncertainties
    # Patterns: "I'm not sure...", "unclear...", "不确定...", "不清楚..."
    uncertainty_patterns = [
        r"(?:I'm not sure|not certain|unclear|不确定|不清楚|还不确定|有待确认)\s+([^。.!！?\n]{10,120})",
        r"(?:need more (?:info|data|context)|需要更多(?:信息|数据))\s+([^。.!！?\n]{10,120})",
    ]
    for pat in uncertainty_patterns:
        for m in re.finditer(pat, reasoning[:2000], re.IGNORECASE):
            text = m.group(1).strip()
            if len(text) > 10 and text not in ht.uncertainties:
                ht.uncertainties.append(text[:120])

    # 4. Extract rejected paths
    # Patterns: "Instead of...", "rather than...", "不...而是..."
    rejected_patterns = [
        r'(?:instead of|rather than|不要|不采用|放弃)\s+([^。.!！?\n]{10,120})',
        r'(?:not going to|won\'t|不打算|不会)\s+([^。.!！?\n]{10,120})',
    ]
    for pat in rejected_patterns:
        for m in re.finditer(pat, reasoning[:2000], re.IGNORECASE):
            text = m.group(1).strip()
            if len(text) > 10 and text not in ht.rejected_paths:
                ht.rejected_paths.append(text[:120])

    # 5. Extract tool plan — tools the model intends to call
    # Look for function names followed by argument hints
    for m in re.finditer(r'\b(\w+)\s*\(\s*(\w+\s*[=:])', reasoning[:1500]):
        tool_name = m.group(1)
        if tool_name.isidentifier() and len(tool_name) > 2:
            if tool_name not in ht.tool_plan:
                ht.tool_plan.append(tool_name)

    # 6. Extract key numeric findings
    for m in re.finditer(
        r'(\d+\.?\d*%?)\s*(?:is|was|shows|indicates|为|是|显示|表明)\s*([^。.!！?\n]{10,80})',
        reasoning[:2000],
    ):
        finding = f"{m.group(1)} {m.group(2).strip()[:80]}"
        if finding not in ht.key_findings:
            ht.key_findings.append(finding)

    # 7. Extract error handling
    if re.search(r'(?:error|fail|错误|失败|empty|空|timeout|超时)', reasoning, re.IGNORECASE):
        ht.error_notes.append("Encountered errors during reasoning — approach was adjusted")

    # Build summary
    parts = []
    if ht.subgoals:
        parts.append(f"Plan: {' → '.join(ht.subgoals[:3])}")
    if ht.tool_plan:
        parts.append(f"Tools planned: {', '.join(ht.tool_plan[:5])}")
    if ht.key_findings:
        parts.append(f"Key data: {'; '.join(ht.key_findings[:3])}")
    ht.summary = " | ".join(parts)

    return ht


# ═══════════════════════════════════════════════════════════════════════════
# Consistency Check (existing functionality, kept for backward compat)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class ConsistencyResult:
    """Result of checking reasoning consistency with actual tool calls."""

    status: str  # "CONSISTENT" | "MISMATCH" | "NO_REASONING"
    reasoning_mentions: list[str] = field(default_factory=list)
    actual_calls: list[str] = field(default_factory=list)


def extract_tool_names(reasoning: str, registered_names: list[str]) -> set[str]:
    """Extract tool names mentioned in reasoning text using word-boundary regex."""
    if not reasoning or not registered_names:
        return set()

    found: set[str] = set()
    for name in registered_names:
        pattern = rf"\b{re.escape(name)}\b"
        if re.search(pattern, reasoning):
            found.add(name)
    return found


def check_consistency(
    reasoning: str | None,
    actual_tool_names: list[str],
    registered_names: list[str],
) -> ConsistencyResult:
    """Check whether reasoning mentions match the tools actually called."""
    if not reasoning:
        return ConsistencyResult(status="NO_REASONING")

    mentions = extract_tool_names(reasoning, registered_names)

    if not mentions:
        return ConsistencyResult(
            status="CONSISTENT",
            actual_calls=list(actual_tool_names),
        )

    if set(mentions) == set(actual_tool_names):
        return ConsistencyResult(
            status="CONSISTENT",
            reasoning_mentions=sorted(mentions),
            actual_calls=list(actual_tool_names),
        )

    return ConsistencyResult(
        status="MISMATCH",
        reasoning_mentions=sorted(mentions),
        actual_calls=list(actual_tool_names),
    )


# ═══════════════════════════════════════════════════════════════════════════
# Thinking Budget Router — task-aware thinking mode selection
# ═══════════════════════════════════════════════════════════════════════════

from dataclasses import dataclass as _dataclass


@_dataclass
class ThinkingDecision:
    enable_thinking: bool = True
    budget_tokens: int = 2048
    self_consistency: int = 1
    compress_reasoning: bool = False
    inject_reasoning: bool = True


class ThinkingRouter:
    """Route thinking mode based on task characteristics."""

    def route(
        self,
        task: str = "",
        tools_count: int = 0,
        model: str = "",
        max_risk: str = "read",
        sla_max_latency_s: float = 30.0,
        response_format: str | None = None,
    ) -> ThinkingDecision:
        """Decide whether to enable thinking and budget allocation."""
        # Structured output → enable thinking for schema adherence
        if response_format == "json_object":
            return ThinkingDecision(enable_thinking=True, budget_tokens=1024)

        # Tight SLA → disable thinking to save latency
        if sla_max_latency_s < 5.0:
            return ThinkingDecision(enable_thinking=False, budget_tokens=0)

        # Destructive tools → enable thinking for safety reasoning
        if max_risk in ("destructive", "code_exec"):
            return ThinkingDecision(enable_thinking=True, budget_tokens=4096)

        # Complex task (long prompt, many tools) → enable with higher budget
        if len(task) > 500 or tools_count > 3:
            return ThinkingDecision(enable_thinking=True, budget_tokens=2048)

        # Simple task → disable to save cost
        if len(task) < 200 and tools_count == 0:
            return ThinkingDecision(enable_thinking=False, budget_tokens=0,
                                    compress_reasoning=False, inject_reasoning=False)

        # Default: enable with moderate budget
        return ThinkingDecision(enable_thinking=True, budget_tokens=1024)
