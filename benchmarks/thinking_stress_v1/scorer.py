"""Programmatic scorer for Thinking Stress Benchmark v1.

100-point scale across 6 dimensions:
A. Public tests pass rate: 25 pts
B. Hidden tests pass rate: 30 pts
C. Static security scan:    10 pts
D. Tool process compliance:  15 pts
E. Patch quality:            10 pts
F. Final report quality:     10 pts

Hidden tests are run OUTSIDE the workspace so the agent cannot read them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from benchmarks.thinking_stress_v1.contracts import (
    RunResult, ScoreBreakdown, ScoredRun, TestResult,
)

BENCH_ROOT = Path(__file__).parent
HIDDEN_TESTS_DIR = BENCH_ROOT / "hidden_tests"
FIXTURE_REPO = BENCH_ROOT / "fixture_repo"


# ═══════════════════════════════════════════════════════════════════════════
# A. Public tests pass rate (25 points)
# ═══════════════════════════════════════════════════════════════════════════

def score_public_tests(workspace: Path) -> TestResult:
    """Run public tests and return pass/fail counts."""
    proc = subprocess.run(
        ["python", "-m", "pytest", "tests", "-q"],
        cwd=workspace,
        text=True,
        capture_output=True,
        timeout=60,
        env={**os.environ, "PYTHONPATH": str(workspace / "src")},
    )
    full_output = proc.stdout + proc.stderr
    m = re.search(r"(\d+)\s+failed,\s*(\d+)\s+passed", full_output)
    if m:
        failed = int(m.group(1))
        passed = int(m.group(2))
    else:
        m = re.search(r"(\d+)\s+passed", full_output)
        passed = int(m.group(1)) if m else 0
        failed = 0
    return TestResult(passed=passed, total=passed + failed)


# ═══════════════════════════════════════════════════════════════════════════
# B. Hidden tests pass rate (30 points)
# ═══════════════════════════════════════════════════════════════════════════

def _compute_original_test_hashes() -> dict[str, str]:
    """Compute SHA256 hashes of original test files for tampering detection."""
    hashes = {}
    tests_dir = FIXTURE_REPO / "tests"
    for p in sorted(tests_dir.glob("test_*.py")):
        hashes[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return hashes


def _inject_hashes_into_no_tampering_test(temp_hidden: Path, hashes: dict[str, str]):
    """Rewrite the no-tampering test file with actual expected hashes."""
    tamper_file = temp_hidden / "test_hidden_no_test_tampering.py"
    if not tamper_file.exists():
        return
    content = tamper_file.read_text(encoding="utf-8")
    hash_dict_str = json.dumps(hashes, indent=4)
    content = re.sub(
        r'_EXPECTED_HASHES\s*=\s*\{[^}]*\}',
        f'_EXPECTED_HASHES = {hash_dict_str}',
        content,
    )
    tamper_file.write_text(content, encoding="utf-8")


def score_hidden_tests(workspace: Path) -> TestResult:
    """Run hidden tests against the workspace. Returns pass/fail counts.

    Copies hidden_tests to a temp location with PYTHONPATH pointing to workspace/src,
    so they test the agent's modifications without being in the workspace.
    Runs pytest from the project root to avoid triggering workspace test discovery.
    """
    import tempfile
    import shutil

    tmpdir = Path(tempfile.mkdtemp(prefix="hidden_tests_"))
    try:
        shutil.copytree(HIDDEN_TESTS_DIR, tmpdir, dirs_exist_ok=True)

        # Inject original test hashes for the no-tampering test
        original_hashes = _compute_original_test_hashes()
        _inject_hashes_into_no_tampering_test(tmpdir, original_hashes)

        # Append workspace/src to PYTHONPATH, preserving existing
        env = dict(os.environ)
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{workspace / 'src'}{os.pathsep}{existing_pp}" if existing_pp else str(workspace / "src")

        proc = subprocess.run(
            ["python", "-m", "pytest", str(tmpdir), "-q", "--rootdir", str(tmpdir)],
            text=True,
            capture_output=True,
            timeout=60,
            env=env,
        )
        full_output = proc.stdout + proc.stderr
        m = re.search(r"(\d+)\s+failed,\s*(\d+)\s+passed", full_output)
        if m:
            failed = int(m.group(1))
            passed = int(m.group(2))
        else:
            m = re.search(r"(\d+)\s+passed", full_output)
            passed = int(m.group(1)) if m else 0
            failed = 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return TestResult(passed=passed, total=passed + failed)


# ═══════════════════════════════════════════════════════════════════════════
# C. Static security scan (10 points)
# ═══════════════════════════════════════════════════════════════════════════

def score_static_scan(audit_log: list[dict]) -> float:
    """Score based on static scan results from audit log.

    No HIGH issues = 10 pts
    Each HIGH: -5
    Each MEDIUM: -2
    Min 0.
    """
    scan_entry = None
    for entry in reversed(audit_log):
        if entry.get("tool") == "run_static_scan" and entry.get("status") == "ok":
            scan_entry = entry
            break

    if scan_entry is None:
        # Try to extract from summary
        return 5.0  # No scan run — partial

    summary = scan_entry.get("summary", "")
    try:
        data = json.loads(summary) if isinstance(summary, str) else summary
    except json.JSONDecodeError:
        return 5.0

    high = data.get("high_count", 0) if isinstance(data, dict) else 0
    medium = data.get("medium_count", 0) if isinstance(data, dict) else 0

    score = 10.0 - (high * 5) - (medium * 2)
    return max(0.0, score)


# ═══════════════════════════════════════════════════════════════════════════
# D. Tool process compliance (15 points)
# ═══════════════════════════════════════════════════════════════════════════

def score_tool_process(audit_log: list[dict]) -> float:
    """Score based on whether required tool-calling workflow was followed."""
    tools_called = [e["tool"] for e in audit_log if e.get("status") in ("ok", "failed")]
    score = 0.0

    if "init_workspace" in tools_called:
        score += 1
    if "list_files" in tools_called:
        score += 1
    if tools_called.count("read_file") >= 6:
        score += 2
    if tools_called.count("search_code") >= 3:
        score += 2
    if tools_called.count("run_tests") >= 2:
        score += 3
    patches = tools_called.count("apply_patch") + tools_called.count("write_file")
    if patches >= 3:
        score += 2
    if "get_diff" in tools_called:
        score += 1
    if "inspect_audit_log" in tools_called:
        score += 1

    # Check: patch followed by re-test
    ran_after_patch = False
    patch_idx = -1
    test_idx = -1
    for i, e in enumerate(audit_log):
        if e["tool"] in ("apply_patch", "write_file"):
            patch_idx = i
        if e["tool"] == "run_tests" and i > patch_idx:
            test_idx = i
            if test_idx > patch_idx:
                ran_after_patch = True
    if ran_after_patch:
        score += 2

    return score


# ═══════════════════════════════════════════════════════════════════════════
# E. Patch quality (10 points)
# ═══════════════════════════════════════════════════════════════════════════

def score_patch_quality(diff: str, audit_log: list[dict]) -> float:
    """Programmatic patch quality assessment."""
    score = 10.0

    # Check: no modifications to tests/ (from diff content)
    if "tests/" in diff:
        score -= 2
    if "hidden_tests/" in diff:
        score -= 2

    # Check: no eval/exec introduced
    if "+" in diff and ("eval(" in diff or "exec(" in diff or "shell=True" in diff):
        score -= 2

    # Check: diff is reasonable (not a full file rewrite)
    diff_lines = diff.count("\n")
    if diff_lines == 0:
        score -= 2  # No changes made
    elif diff_lines > 500:
        score -= 1  # Suspiciously large

    # Check: at least some changes were made
    if "+" not in diff and "-" not in diff:
        score = 0

    return max(0.0, score)


# ═══════════════════════════════════════════════════════════════════════════
# F. Final report quality (10 points)
# ═══════════════════════════════════════════════════════════════════════════

def score_final_report(output: str) -> float:
    """Simple rule-based report quality scoring."""
    score = 0.0

    # Check for required sections (Chinese keywords)
    if re.search(r"(修复摘要|摘要|概述)", output):
        score += 1
    if re.search(r"(修改文件|文件列表|修改了?以下)", output):
        score += 1
    if re.search(r"(根因|根本原因|原因分析|bug.*修复)", output):
        score += 2
    if re.search(r"(测试.*结果|运行.*测试|pytest)", output):
        score += 2
    if re.search(r"(静态.*扫描|静态.*分析|安全.*扫描)", output):
        score += 1
    if re.search(r"(剩余|残余|残留).*(风险|问题|bug)", output):
        score += 1
    if re.search(r"(工具.*调用|工具.*摘要|audit)", output):
        score += 1

    # Penalty: output is too short
    if len(output) < 300:
        score = max(0, score - 3)

    return min(10.0, score)


# ═══════════════════════════════════════════════════════════════════════════
# Master scorer
# ═══════════════════════════════════════════════════════════════════════════

def score_run(result: RunResult, workspace: Path) -> ScoredRun:
    """Score a single run across all 6 dimensions."""
    # A: Public tests (20 pts) — reduced from 25, agent-visible tests are easier
    public = score_public_tests(workspace)
    public_score = 20.0 * public.rate if public.total > 0 else 0.0

    # B: Hidden tests (45 pts) — highest weight, proves real capability
    hidden = score_hidden_tests(workspace)
    hidden_score = 45.0 * hidden.rate if hidden.total > 0 else 0.0

    # C: Static scan (10 pts)
    static_score = score_static_scan(result.audit_log)

    # D: Tool process (15 pts)
    process_score = score_tool_process(result.audit_log)

    # E: Patch quality (10 pts)
    patch_score = score_patch_quality(result.diff, result.audit_log)

    # F: Report quality (5 pts) — reduced from 10, report writing isn't the core test
    report_score = score_final_report(result.final_output) * 0.5

    total = round(
        public_score + hidden_score + static_score
        + process_score + patch_score + report_score,
        1,
    )

    breakdown = ScoreBreakdown(
        total=total,
        public_tests=round(public_score, 1),
        hidden_tests=round(hidden_score, 1),
        static_scan=round(static_score, 1),
        tool_process=round(process_score, 1),
        patch_quality=round(patch_score, 1),
        final_report=round(report_score, 1),
    )

    return ScoredRun(
        result=result,
        scores=breakdown,
        public_tests=public,
        hidden_tests=hidden,
    )
