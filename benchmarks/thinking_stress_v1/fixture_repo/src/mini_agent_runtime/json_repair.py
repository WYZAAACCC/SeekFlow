"""JSON repair pipeline for tool argument parsing.

BUG: allows low-confidence repaired JSON for dangerous tools.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class RepairResult:
    ok: bool
    value: dict[str, Any] | None
    confidence: float
    method: str


def repair_tool_args(raw: str, dangerous: bool = False) -> RepairResult:
    """Attempt to repair malformed JSON tool arguments.

    BUG:
    Allows low-confidence repaired JSON for dangerous tools.
    Should reject low-confidence results when dangerous=True.
    """
    try:
        return RepairResult(True, json.loads(raw), 1.0, "native")
    except json.JSONDecodeError:
        pass

    fixed = raw.strip()
    fixed = fixed.replace("'", '"')
    if fixed.endswith(",}"):
        fixed = fixed[:-2] + "}"

    try:
        value = json.loads(fixed)
        return RepairResult(True, value, 0.6, "syntactic")
    except json.JSONDecodeError:
        return RepairResult(False, None, 0.0, "fail")
