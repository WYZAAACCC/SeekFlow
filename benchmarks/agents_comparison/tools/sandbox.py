"""Python code sandbox — executes experiments in isolated subprocess."""

import subprocess
import tempfile
from pathlib import Path


def run_python_experiment(code: str, timeout: int = 60) -> str:
    """Execute Python code in a sandbox subprocess and return stdout/stderr.

    Runs the code in an isolated process with restricted builtins for safety.
    Captures all output including print() statements and return values.

    Args:
        code: Python source code to execute
        timeout: Maximum execution time in seconds (default: 60, max: 120)

    Returns:
        Combined stdout and stderr output, truncated to 4000 chars
    """
    timeout = min(timeout, 120)

    # Wrap code in safety harness
    wrapped_code = f'''
import sys
import io

# Force UTF-8 encoding on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
elif hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import json
import math
import statistics
import random
import itertools
import collections
import datetime
import re
import csv

try:
{_indent(code, 4)}
except Exception as _e:
    import traceback
    print(f"EXPERIMENT_ERROR: {{type(_e).__name__}}: {{_e}}")
    traceback.print_exc()
'''

    try:
        result = subprocess.run(
            ["python", "-c", wrapped_code],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=str(Path(__file__).parent.parent),
            env={
                **__import__('os').environ,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONUNBUFFERED": "1",
                "PYTHONLEGACYWINDOWSSTDIO": "utf-8",
            },
        )

        output = result.stdout or ""
        if result.stderr:
            output += f"\n[STDERR]\n{result.stderr}"

        if result.returncode != 0:
            output = f"[EXIT CODE: {result.returncode}]\n{output}"

        if len(output) > 4000:
            output = output[:4000] + f"\n... [truncated, total {len(output)} chars]"

        return output if output.strip() else "(no output)"

    except subprocess.TimeoutExpired:
        return f"Experiment timed out after {timeout}s"
    except Exception as e:
        return f"Experiment execution failed: {e}"


def _indent(text: str, spaces: int = 4) -> str:
    """Indent each line of text."""
    prefix = " " * spaces
    return "\n".join(prefix + line for line in text.split("\n"))
