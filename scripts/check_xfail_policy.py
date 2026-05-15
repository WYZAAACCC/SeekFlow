#!/usr/bin/env python3
"""Check xfail policy compliance — enforce strict=True and issue ID references.

Usage: python scripts/check_xfail_policy.py

Exit 0 if all xfail markers comply. Exit 1 with details otherwise.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parents[1] / "tests"

# Core paths where xfail requires extra justification (logged as WARNING, not error).
# These tests cover the primary execution and security paths.
CORE_PATHS: list[str] = [
    "tests/test_runtime.py",
    "tests/test_tool_executor.py",
    "tests/test_policy.py",
    "tests/test_thinking.py",
    "tests/tools/",
    "tests/security/",
    "tests/deepseek/",
    "tests/test_version_consistency.py",
]


def _is_core(file_path: str) -> bool:
    return any(file_path == p or file_path.startswith(p) for p in CORE_PATHS)


def _extract_xfails(file_path: Path) -> list[dict]:
    """Parse a test file and return a list of xfail decorator info."""
    try:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
    except SyntaxError as e:
        return [{"line": 0, "reason": f"SyntaxError: {e}", "strict": False}]

    results: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            call = dec
            if isinstance(call, ast.Attribute):
                continue
            if isinstance(call, ast.Call):
                func = call.func
                is_xfail = False
                if isinstance(func, ast.Attribute):
                    if isinstance(func.value, ast.Attribute):
                        if (
                            func.value.attr == "mark"
                            and func.attr == "xfail"
                        ):
                            is_xfail = True
                if not is_xfail:
                    continue

                info: dict = {
                    "line": node.lineno,
                    "name": node.name,
                    "reason": "",
                    "strict": False,
                }
                for kw in call.keywords:
                    if kw.arg == "reason":
                        if isinstance(kw.value, ast.Constant):
                            info["reason"] = str(kw.value.value)
                    if kw.arg == "strict":
                        if isinstance(kw.value, ast.Constant):
                            info["strict"] = bool(kw.value.value)
                results.append(info)
    return results


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    for py_file in sorted(TESTS_DIR.rglob("test_*.py")):
        rel = "tests/" + str(py_file.relative_to(TESTS_DIR).as_posix())

        xfails = _extract_xfails(py_file)
        if not xfails:
            continue

        for xf in xfails:
            test_id = f"{rel}::{xf['name']} (line {xf['line']})"

            # Rule 1: strict=True required (exception: flaky tests with issue ref)
            if not xf["strict"]:
                if "flaky" not in xf["reason"].lower() or "issue" not in xf["reason"].lower():
                    errors.append(
                        f"{test_id}: xfail must use strict=True (or be a flaky test with issue ref)"
                    )

            # Rule 2: reason must reference an issue
            if "issue" not in xf["reason"].lower() and "#" not in xf["reason"]:
                errors.append(
                    f"{test_id}: xfail reason must include issue reference "
                    f'(got: "{xf["reason"]}")'
                )

            # Rule 3: core path xfail is a warning (not error)
            if _is_core(rel):
                warnings.append(
                    f"{test_id}: xfail in core path — review and fix or link to "
                    f"a specific issue tracking the root cause"
                )

    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"  {w}")
        print()

    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  {e}")
        print(f"\n{len(errors)} xfail policy violation(s) found.")
        return 1

    print("All xfail markers comply with policy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
