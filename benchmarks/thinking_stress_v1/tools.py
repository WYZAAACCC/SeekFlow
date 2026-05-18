"""Controlled tools for Thinking Stress Benchmark v1.

All tools return dicts for consistent interface. No arbitrary shell access.
Workspace isolation enforced via _safe_path. Audit log tracks every call.

CRITICAL: SeekFlow may run tools in subprocesses (ProcessRunner). Therefore
workspace state and audit log must be persisted to files, NOT module globals.
The pattern mirrors fair_comparison_v2's _SEEKFLOW_BENCH_EVENTS_FILE mechanism.

Agent can only modify src/mini_agent_runtime — cannot touch tests or hidden_tests.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

BENCH_ROOT = Path(__file__).parent
FIXTURE_REPO = BENCH_ROOT / "fixture_repo"
HIDDEN_TESTS_DIR = BENCH_ROOT / "hidden_tests"

# File-based state for cross-process safety
_STATE_DIR = Path(tempfile.gettempdir()) / "seekflow_thinking_stress"
_STATE_DIR.mkdir(parents=True, exist_ok=True)

# Module-level cache (only for current process optimization)
_CURRENT_WORKSPACE: Path | None = None
_AUDIT_LOG: list[dict[str, Any]] = []


def _get_ws_state_path() -> Path:
    """Get workspace state file path from env or default."""
    env_path = os.environ.get("_SEEKFLOW_THINKING_WS_FILE")
    if env_path:
        return Path(env_path)
    return _STATE_DIR / f"ws_{os.getpid()}.json"


def _get_audit_path() -> Path:
    """Get audit log file path from env or default."""
    env_path = os.environ.get("_SEEKFLOW_THINKING_AUDIT_FILE")
    if env_path:
        return Path(env_path)
    return _STATE_DIR / f"audit_{os.getpid()}.jsonl"


def _audit(tool: str, args: dict[str, Any], result: dict[str, Any]) -> None:
    """Record a tool call event. Writes to both in-memory list and file."""
    ev = {
        "ts": time.time(),
        "tool": tool,
        "args": args,
        "status": result.get("status"),
        "duration_s": result.get("duration_s"),
        "summary": str(result)[:500],
    }
    _AUDIT_LOG.append(ev)
    # Also write to file for cross-process access
    try:
        with open(_get_audit_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _require_ws() -> Path:
    """Get current workspace. Checks in-process cache first, then file."""
    global _CURRENT_WORKSPACE
    if _CURRENT_WORKSPACE is not None:
        return _CURRENT_WORKSPACE

    # Try file-based state (for subprocess access)
    state_path = _get_ws_state_path()
    try:
        if state_path.exists():
            data = json.loads(state_path.read_text(encoding="utf-8"))
            ws = Path(data["workspace"])
            if ws.exists():
                _CURRENT_WORKSPACE = ws
                return ws
    except Exception:
        pass

    raise RuntimeError("Workspace not initialized. Call init_workspace first.")


def _save_ws_state(workspace: Path) -> None:
    """Persist workspace path to file for cross-process access."""
    global _CURRENT_WORKSPACE
    _CURRENT_WORKSPACE = workspace
    state_path = _get_ws_state_path()
    try:
        state_path.write_text(
            json.dumps({"workspace": str(workspace), "pid": os.getpid()}),
            encoding="utf-8",
        )
        # Also set env var for child processes
        os.environ["_SEEKFLOW_THINKING_WS_FILE"] = str(state_path)
        os.environ["_SEEKFLOW_THINKING_AUDIT_FILE"] = str(_get_audit_path())
    except Exception:
        pass


def _safe_path(path: str, allow_tests: bool = False) -> Path:
    """Resolve a path within workspace. Blocks hidden_tests access and restricts writes."""
    ws = _require_ws().resolve()
    p = (ws / path).resolve()

    if not p.is_relative_to(ws):
        raise ValueError(
            f"Path escapes workspace: {path}\n"
            f"Resolved: {p}\n"
            f"Workspace: {ws}"
        )

    if "hidden_tests" in p.parts:
        raise ValueError("hidden_tests are not accessible to agents")

    if not allow_tests:
        src_root = (ws / "src" / "mini_agent_runtime").resolve()
        if not p.is_relative_to(src_root):
            raise ValueError(
                f"Only src/mini_agent_runtime files may be modified.\n"
                f"Requested: {path}\n"
                f"Resolved: {p}"
            )

    return p


# ═══════════════════════════════════════════════════════════════════════════
# Tool implementations
# ═══════════════════════════════════════════════════════════════════════════


def init_workspace(case_id: str = "runtime_repair_lab") -> dict:
    """Initialize a fresh workspace copied from the fixture repository.

    Must be called first before any other tool.
    """
    global _AUDIT_LOG
    _AUDIT_LOG = []

    started = time.perf_counter()
    tmp = Path(tempfile.mkdtemp(prefix=f"seekflow_thinking_{case_id}_"))
    shutil.copytree(
        FIXTURE_REPO, tmp, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", ".git"),
    )

    # Ensure hidden_tests are NOT copied into workspace
    hidden_in_ws = tmp / "hidden_tests"
    if hidden_in_ws.exists():
        shutil.rmtree(hidden_in_ws)

    resolved = tmp.resolve()
    _save_ws_state(resolved)
    _AUDIT_LOG = []

    # Clear audit file
    audit_path = _get_audit_path()
    try:
        audit_path.write_text("", encoding="utf-8")
    except Exception:
        pass

    result = {
        "status": "ok",
        "workspace": str(resolved),
        "instruction": (
            "Workspace initialized. Use list_files to explore the repository, "
            "read_file to read source code and tests, run_tests to see current "
            "test failures, then apply_patch or write_file to fix bugs in "
            "src/mini_agent_runtime."
        ),
        "duration_s": round(time.perf_counter() - started, 3),
    }
    _audit("init_workspace", {"case_id": case_id}, result)
    return result


def list_files() -> dict:
    """List all files in the workspace (excluding hidden_tests)."""
    started = time.perf_counter()
    ws = _require_ws()
    files = []
    for p in ws.rglob("*"):
        if p.is_file():
            rel = p.relative_to(ws).as_posix()
            if rel.startswith("hidden_tests/"):
                continue
            # Also exclude cache directories
            if "__pycache__" in p.parts or ".pytest_cache" in p.parts:
                continue
            files.append(rel)

    result = {
        "status": "ok",
        "files": sorted(files),
        "duration_s": round(time.perf_counter() - started, 3),
    }
    _audit("list_files", {}, result)
    return result


def read_file(path: str, max_chars: int = 12000) -> dict:
    """Read content from a file in the workspace. Returns first max_chars characters.

    Returns dict with status, path, content, chars, truncated fields.
    """
    started = time.perf_counter()
    ws = _require_ws().resolve()
    p = (ws / path).resolve()

    if not p.is_relative_to(ws):
        result = {
            "status": "error",
            "error": f"Path escapes workspace: {path}",
            "duration_s": round(time.perf_counter() - started, 3),
        }
        _audit("read_file", {"path": path}, result)
        return result

    if "hidden_tests" in p.parts:
        result = {
            "status": "error",
            "error": "hidden_tests are not accessible to agents",
            "duration_s": round(time.perf_counter() - started, 3),
        }
        _audit("read_file", {"path": path}, result)
        return result

    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        result = {
            "status": "error",
            "error": f"Cannot read {path}: {e}",
            "duration_s": round(time.perf_counter() - started, 3),
        }
        _audit("read_file", {"path": path}, result)
        return result

    original_len = len(content)
    if len(content) > max_chars:
        content = content[:max_chars] + f"\n...[truncated {original_len} chars total]"

    result = {
        "status": "ok",
        "path": path,
        "content": content,
        "chars": len(content),
        "original_chars": original_len,
        "truncated": original_len > max_chars,
        "duration_s": round(time.perf_counter() - started, 3),
    }
    _audit("read_file", {"path": path, "max_chars": max_chars}, result)
    return result


def search_code(pattern: str, glob: str = "**/*.py") -> dict:
    """Search for a regex pattern in workspace source files."""
    started = time.perf_counter()
    ws = _require_ws()
    rx = re.compile(pattern)
    matches = []

    for p in ws.glob(glob):
        if not p.is_file():
            continue
        rel = p.relative_to(ws).as_posix()
        if rel.startswith("hidden_tests/"):
            continue
        if "__pycache__" in p.parts or ".pytest_cache" in p.parts:
            continue

        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        for i, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                matches.append({
                    "path": rel,
                    "line": i,
                    "text": line[:240],
                })

    result = {
        "status": "ok",
        "pattern": pattern,
        "matches": matches[:200],
        "count": len(matches),
        "duration_s": round(time.perf_counter() - started, 3),
    }
    _audit("search_code", {"pattern": pattern, "glob": glob}, result)
    return result


def apply_patch(path: str, old: str, new: str) -> dict:
    """Replace old text with new text in a source file. Only works in src/mini_agent_runtime.

    The old string must appear exactly once in the file.
    """
    started = time.perf_counter()
    result = None  # initialize to avoid unbound in except path of finally

    try:
        p = _safe_path(path, allow_tests=False)
        text = p.read_text(encoding="utf-8", errors="replace")
        if old not in text:
            result = {
                "status": "error",
                "error": "old text not found exactly once or at all",
                "instruction": "Use read_file to inspect the exact current content before patching.",
                "duration_s": round(time.perf_counter() - started, 3),
            }
            return result

        occurrences = text.count(old)
        if occurrences != 1:
            result = {
                "status": "error",
                "error": f"old text occurs {occurrences} times; patch would be ambiguous",
                "duration_s": round(time.perf_counter() - started, 3),
            }
            return result

        p.write_text(text.replace(old, new), encoding="utf-8")
        result = {
            "status": "ok",
            "path": path,
            "duration_s": round(time.perf_counter() - started, 3),
        }
        return result
    finally:
        try:
            _audit("apply_patch", {"path": path}, result if result is not None else {"status": "unknown"})
        except Exception:
            pass


def write_file(path: str, content: str) -> dict:
    """Write content to a file in src/mini_agent_runtime."""
    started = time.perf_counter()
    result = None

    try:
        p = _safe_path(path, allow_tests=False)
        p.write_text(content, encoding="utf-8")
        result = {
            "status": "ok",
            "path": path,
            "duration_s": round(time.perf_counter() - started, 3),
        }
        return result
    finally:
        try:
            _audit("write_file", {"path": path, "chars": len(content)},
                   result if result is not None else {"status": "unknown"})
        except Exception:
            pass


def run_tests(target: str = "tests", keyword: str = "") -> dict:
    """Run pytest on the specified target within the workspace.

    Agent can only run public tests. Hidden tests are blocked.
    """
    started = time.perf_counter()
    ws = _require_ws()

    if "hidden" in target.lower():
        result = {
            "status": "error",
            "error": "hidden tests are not accessible to agents",
            "duration_s": round(time.perf_counter() - started, 3),
        }
        _audit("run_tests", {"target": target, "keyword": keyword}, result)
        return result

    cmd = ["python", "-m", "pytest", target, "-q", "-v"]
    if keyword:
        cmd.extend(["-k", keyword])

    try:
        proc = subprocess.run(
            cmd,
            cwd=ws,
            text=True,
            capture_output=True,
            timeout=30,
            env={**os.environ, "PYTHONPATH": str(ws / "src")},
        )
    except subprocess.TimeoutExpired:
        result = {
            "status": "error",
            "error": "Test execution timed out (30s)",
            "duration_s": round(time.perf_counter() - started, 3),
        }
        _audit("run_tests", {"target": target, "keyword": keyword}, result)
        return result

    # Parse pytest summary line (format: "N failed, M passed in X.XXs")
    passed = 0
    failed = 0
    total = 0
    full_output = proc.stdout + proc.stderr
    m = re.search(r"(\d+)\s+failed,\s*(\d+)\s+passed", full_output)
    if m:
        failed = int(m.group(1))
        passed = int(m.group(2))
        total = failed + passed
    else:
        m = re.search(r"(\d+)\s+passed", full_output)
        if m:
            passed = int(m.group(1))
            total = passed

    result = {
        "status": "ok" if proc.returncode == 0 else "failed",
        "returncode": proc.returncode,
        "passed": passed,
        "failed": failed,
        "total": total,
        "stdout": proc.stdout[-8000:],
        "stderr": proc.stderr[-4000:],
        "duration_s": round(time.perf_counter() - started, 3),
        "instruction": (
            "If tests failed, inspect the traceback and patch root cause. "
            "Do not modify tests."
        ),
    }
    _audit("run_tests", {"target": target, "keyword": keyword}, result)
    return result


def run_static_scan() -> dict:
    """Run static analysis on src/mini_agent_runtime for security issues."""
    started = time.perf_counter()
    ws = _require_ws()
    issues = []

    for p in (ws / "src" / "mini_agent_runtime").rglob("*.py"):
        rel = p.relative_to(ws).as_posix()
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        if "eval(" in text or "exec(" in text:
            issues.append({"severity": "HIGH", "path": rel, "issue": "eval/exec usage"})
        if "return True" in text and "authorize" in p.name:
            issues.append({"severity": "MEDIUM", "path": rel, "issue": "possible permissive policy"})
        if "startswith(str(root))" in text:
            issues.append({"severity": "HIGH", "path": rel, "issue": "unsafe path prefix check"})
        if "as_completed(futures)" in text and "ordered" not in text and "index" not in text:
            issues.append({"severity": "MEDIUM", "path": rel, "issue": "parallel results may not preserve order"})
        if "time.time()" in text and "prefix" in p.name.lower():
            issues.append({"severity": "MEDIUM", "path": rel, "issue": "timestamp in cache prefix"})

    result = {
        "status": "ok",
        "issues": issues,
        "high_count": sum(1 for x in issues if x["severity"] == "HIGH"),
        "medium_count": sum(1 for x in issues if x["severity"] == "MEDIUM"),
        "duration_s": round(time.perf_counter() - started, 3),
    }
    _audit("run_static_scan", {}, result)
    return result


def get_diff() -> dict:
    """Get a unified diff of all changes made to src/mini_agent_runtime."""
    ws = _require_ws()
    lines = []

    for p in (ws / "src" / "mini_agent_runtime").rglob("*.py"):
        rel = p.relative_to(ws)
        fixture_file = FIXTURE_REPO / rel
        try:
            original = fixture_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        try:
            current = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if original != current:
            lines.extend(difflib.unified_diff(
                original.splitlines(),
                current.splitlines(),
                fromfile=f"a/{rel.as_posix()}",
                tofile=f"b/{rel.as_posix()}",
                lineterm="",
            ))

    diff_text = "\n".join(lines)[:20000]
    result = {
        "status": "ok",
        "diff": diff_text,
        "chars": len(diff_text),
    }
    _audit("get_diff", {}, result)
    return result


def inspect_audit_log() -> dict:
    """Return the complete tool-call audit log for this session.

    Reads from both in-memory cache and file (for subprocess events).
    """
    # Read file-based events first (subprocess-safe)
    events = []
    audit_path = _get_audit_path()
    try:
        if audit_path.exists():
            with open(audit_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
    except Exception:
        pass

    # Prefer file-based if it has entries, otherwise fall back to in-memory
    if events:
        return {
            "status": "ok",
            "events": events,
            "count": len(events),
        }

    return {
        "status": "ok",
        "events": _AUDIT_LOG,
        "count": len(_AUDIT_LOG),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Tool registry — all tools exposed to agents
# ═══════════════════════════════════════════════════════════════════════════

TOOLS = [
    init_workspace,
    list_files,
    read_file,
    search_code,
    apply_patch,
    write_file,
    run_tests,
    run_static_scan,
    get_diff,
    inspect_audit_log,
]
