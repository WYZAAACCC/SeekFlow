"""Programmatic Compliance Judge — scores tool execution fidelity.

Evaluates what the LLM Judge cannot see: did the agent *actually* call the
required tools?  Did it call them with correct parameters?  Did the output
faithfully reference tool return values?

This is layer 2 of the dual-judge system.  Layer 1 (LLM Judge) scores report
quality; Layer 2 (Compliance Judge) scores tool execution truthfulness.
"""
from __future__ import annotations

import re
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════
# Required tool contracts per scenario
# ═══════════════════════════════════════════════════════════════════════════

REQUIRED_TOOLS: dict[str, dict[str, int]] = {
    "financial_analyst": {
        "web_search": 3, "calculate_roi": 3, "compound_growth": 3,
        "risk_score": 3, "statistical_summary": 1, "convert_currency": 6,
    },
    "supply_chain_analyst": {
        "web_search": 3, "statistical_summary": 1, "compound_growth": 1,
        "convert_currency": 1, "extract_keywords": 1, "supply_risk_score": 3,
    },
    "portfolio_rebalance": {
        "convert_currency": 24, "compound_growth": 4,
        "risk_score": 4, "statistical_summary": 1,
    },
    "strategic_conflict": {
        "web_search": 2, "calculate_roi": 2, "risk_score": 2, "compound_growth": 2,
    },
    "intelligence_synthesis": {
        "web_search": 3, "extract_keywords": 1,
    },
    "compliance_gray_zone": {
        "web_search": 3,
    },
    "impossible_trilemma": {
        "convert_currency": 1, "calculate_roi": 3, "web_search": 2,
    },
    "causal_forensics": {
        "web_search": 2, "statistical_summary": 1, "calculate_roi": 1,
    },
    "negotiation_deadlock": {
        "calculate_roi": 3, "compound_growth": 1, "convert_currency": 1, "web_search": 2,
    },
}

# Expected risk_score arguments per scenario
_EXPECTED_RISK_ARGS: dict[str, list[dict[str, float]]] = {
    "financial_analyst": [
        {"volatility_percent": 32, "debt_ratio": 0.15, "market_cap_billions": 85.0},
        {"volatility_percent": 18, "debt_ratio": 0.42, "market_cap_billions": 12.0},
        {"volatility_percent": 45, "debt_ratio": 0.28, "market_cap_billions": 3.5},
    ],
    "portfolio_rebalance": [
        {"volatility_percent": 18, "debt_ratio": 0.05, "market_cap_billions": 120.0},
        {"volatility_percent": 8, "debt_ratio": 0.85, "market_cap_billions": 45.0},
        {"volatility_percent": 22, "debt_ratio": 0.45, "market_cap_billions": 35.0},
        {"volatility_percent": 28, "debt_ratio": 0.30, "market_cap_billions": 15.0},
    ],
    "strategic_conflict": [
        {"volatility_percent": 35, "debt_ratio": 0.20, "market_cap_billions": 8.0},
        {"volatility_percent": 55, "debt_ratio": 0.55, "market_cap_billions": 8.0},
    ],
}

_EXPECTED_SUPPLY_RISK_ARGS: list[dict[str, float]] = [
    {"probability_percent": 35, "impact_score": 9, "exposure_percent": 45},
    {"probability_percent": 30, "impact_score": 8, "exposure_percent": 60},
    {"probability_percent": 70, "impact_score": 6, "exposure_percent": 35},
]

# Known-good statistical_summary result for supply-chain freight data
_EXPECTED_STATS = {
    "mean": 3675.0,
    "median": 3600.0,
    "std_dev": 414.5781,
    "min": 3100.0,
    "max": 4500.0,
    "range": 1400.0,
}


def _close_enough(a: float, b: float, rel_tol: float = 0.02) -> bool:
    return abs(a - b) <= rel_tol * max(abs(a), abs(b), 1.0)


def _args_match(actual_args: tuple, actual_kwargs: dict, expected: dict[str, float]) -> bool:
    """Check if actual tool args match expected parameter values."""
    # positional args: the tool functions take positional args
    # Try matching by position (assumes args are passed positionally)
    expected_keys = list(expected.keys())
    if len(actual_args) >= len(expected_keys):
        for i, key in enumerate(expected_keys):
            if not _close_enough(float(actual_args[i]), expected[key]):
                return False
        return True
    # Fallback: try kwargs
    for key, val in expected.items():
        if key in actual_kwargs:
            if not _close_enough(float(actual_kwargs[key]), val):
                return False
        elif key in {f"arg{i}" for i in range(len(actual_args))}:
            continue  # handled by positional check
        else:
            return False
    return True


def score_tool_compliance(
    scenario: str,
    tool_events: list[dict[str, Any]],
    output: str,
) -> dict[str, Any]:
    """Compute tool compliance scores from instrumented tool events.

    Returns:
        tool_coverage_score: 0-10, how many required tools were called
        tool_compliance_score: 0-10, coverage minus fabrication penalty
        param_correctness_score: 0-10, parameter accuracy for risk tools
        honesty_score: 0-10, did output correctly report search failures
        unit_consistency_score: 0-10, market_cap_billions unit check
        tool_counts: dict of tool_name → successful call count
        details: list of human-readable issue descriptions
    """
    # ── Count successful tool calls ──
    counts: dict[str, int] = {}
    for e in tool_events:
        if e.get("success"):
            counts[e["tool"]] = counts.get(e["tool"], 0) + 1

    required = REQUIRED_TOOLS.get(scenario, {})
    missing: dict[str, dict[str, int]] = {}
    coverage_points = 0
    coverage_total = 0

    for tool, min_count in required.items():
        actual = counts.get(tool, 0)
        coverage_total += min_count
        coverage_points += min(actual, min_count)
        if actual < min_count:
            missing[tool] = {"expected": min_count, "actual": actual}

    coverage_score = round(10 * coverage_points / coverage_total, 1) if coverage_total else 10.0

    # ── Parameter correctness ──
    param_correct = 0
    param_total = 0
    param_details: list[str] = []

    if scenario in ("financial_analyst", "portfolio_rebalance", "strategic_conflict"):
        risk_events = [e for e in tool_events if e["tool"] == "risk_score" and e["success"]]
        expected_args = _EXPECTED_RISK_ARGS.get(scenario, [])
        param_total = len(expected_args)
        for expected in expected_args:
            for e in risk_events:
                if _args_match(e.get("args", ()), e.get("kwargs", {}), expected):
                    param_correct += 1
                    break
        for e in risk_events:
            args = e.get("args", ())
            if len(args) >= 3 and args[2] > 250:
                param_details.append(
                    f"risk_score called with market_cap_billions={args[2]} — "
                    "likely unit error (850亿美元 should be 85.0, not 850.0)"
                )

    elif scenario == "supply_chain_analyst":
        sr_events = [e for e in tool_events if e["tool"] == "supply_risk_score" and e["success"]]
        param_total = len(_EXPECTED_SUPPLY_RISK_ARGS)
        for expected in _EXPECTED_SUPPLY_RISK_ARGS:
            for e in sr_events:
                if _args_match(e.get("args", ()), e.get("kwargs", {}), expected):
                    param_correct += 1
                    break

    param_score = round(10 * param_correct / param_total, 1) if param_total else 10.0

    # ── Honesty: fabrication check ──
    fabrication_penalty = 0
    honesty_details: list[str] = []

    # Check: output CLAIMS tool execution but tool_events show no successful call.
    # We look for explicit claim patterns (>> tool_name, 工具：tool_name, tool_name 返回)
    # rather than mere name mentions which could be from the task description.
    for tool_name in required:
        tool_called = counts.get(tool_name, 0) > 0
        if tool_called:
            continue
        _claim_patterns = [
            rf">>\s*{re.escape(tool_name)}",
            rf"工具[：:]\s*{re.escape(tool_name)}",
            rf"{re.escape(tool_name)}\s*[=＝]\s*",
            rf"{re.escape(tool_name)}\s*返回",
        ]
        claimed = any(re.search(p, output) for p in _claim_patterns)
        if claimed:
            fabrication_penalty += 1
            honesty_details.append(
                f"Output claims '{tool_name}' was executed but no successful call recorded"
            )

    # Check: search unavailable → output should declare it
    search_events = [e for e in tool_events if e["tool"] == "web_search" and e["success"]]
    search_all_empty = search_events and all(
        "unavailable" in e.get("result_preview", "") or
        '"results":[]' in e.get("result_preview", "") or
        '"results": []' in e.get("result_preview", "")
        for e in search_events
    )
    if search_all_empty:
        if "未获得可验证搜索结果" not in output and "搜索.*不可用" not in output:
            fabrication_penalty += 1
            honesty_details.append(
                "All web_search calls returned empty/unavailable but "
                "output does not declare search unavailability"
            )

    honesty_score = max(0, 10 - fabrication_penalty * 3)

    # ── Unit consistency ──
    unit_issues: list[str] = []
    for e in tool_events:
        if e["tool"] == "risk_score" and e["success"]:
            rp = e.get("result_preview", "")
            if "warnings" in rp and "unusually large" in rp:
                unit_issues.append("risk_score market_cap_billions triggered unit warning")

    unit_score = max(0, 10 - len(unit_issues) * 5)

    # ── Composite ──
    tool_compliance_score = round(
        0.40 * coverage_score
        + 0.25 * param_score
        + 0.20 * honesty_score
        + 0.15 * unit_score,
        1,
    )

    return {
        "tool_coverage_score": coverage_score,
        "param_correctness_score": param_score,
        "honesty_score": honesty_score,
        "unit_consistency_score": unit_score,
        "tool_compliance_score": tool_compliance_score,
        "tool_counts": counts,
        "missing_required_tools": missing,
        "fabrication_penalty": fabrication_penalty,
        "unit_issues": unit_issues,
        "details": param_details + honesty_details + unit_issues,
    }


def compute_final_score(llm_overall: float, compliance: dict[str, Any],
                        scenario: str = "") -> float:
    """Blend LLM report-quality score with programmatic compliance score.

    Uses scenario-specific weight from SCENARIO_META:
      - mechanical scenarios (financial/supply/portfolio): 30% compliance
      - reasoning scenarios (conflict/intelligence/compliance): 10-15% compliance
    """
    from benchmarks.fair_comparison_v2.shared_tools import SCENARIO_META
    meta = SCENARIO_META.get(scenario, {})
    cmp_weight = meta.get("compliance_weight", 0.30)
    qual_weight = 1.0 - cmp_weight
    return round(qual_weight * llm_overall + cmp_weight * compliance["tool_compliance_score"], 1)
