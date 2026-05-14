"""Built-in tools — commonly needed functions for DeepSeek agents."""
from __future__ import annotations

import json
import re
from pathlib import Path


def fetch_url(url: str, timeout: int = 15) -> str:
    """DEPRECATED. Use seekflow.tools.builtins.make_fetch_url() instead."""
    raise RuntimeError(
        "Unsafe legacy fetch_url is disabled. "
        "Use seekflow.tools.builtins.make_fetch_url(allowed_domains={...})."
    )


def parse_csv_str(text: str) -> str:
    """Parse CSV text to JSON array of objects."""
    import csv, io
    try:
        reader = csv.DictReader(io.StringIO(text))
        rows = [dict(row) for row in reader]
        return json.dumps(rows, ensure_ascii=False, indent=2)[:8000]
    except Exception as e:
        return f"CSV parse failed: {e}"


def run_python(code: str, timeout: int = 10) -> str:
    """DEPRECATED. Use seekflow.tools.builtins.make_python_exec(sandbox=...)."""
    raise RuntimeError(
        "Unsafe legacy run_python is disabled. "
        "Use seekflow.tools.builtins.make_python_exec(sandbox=ProcessSandbox())."
    )


def extract_entities(text: str) -> str:
    """Extract named entities (basic regex-based)."""
    entities: dict[str, list[str]] = {}
    emails = re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', text)
    if emails:
        entities["emails"] = emails
    urls = re.findall(r'https?://[^\s]+', text)
    if urls:
        entities["urls"] = urls
    phones = re.findall(r'\b1[3-9]\d{9}\b', text)
    if phones:
        entities["phones"] = phones
    return json.dumps(entities, ensure_ascii=False) if entities else "No entities found."


def query_sql(db_path: str, query: str) -> str:
    """DEPRECATED. Use seekflow.tools.builtins.make_sqlite_query(workspace_root=...)."""
    raise RuntimeError(
        "Unsafe legacy query_sql is disabled. "
        "Use seekflow.tools.builtins.make_sqlite_query(workspace_root=...)."
    )


def classify_text(text: str, labels: str) -> str:
    """Simple keyword-based classification. labels = comma-separated."""
    label_list = [l.strip() for l in labels.split(",")]
    text_lower = text.lower()
    scores = {}
    for label in label_list:
        scores[label] = text_lower.count(label.lower())
    best = max(scores, key=scores.get) if scores else "unknown"
    return json.dumps({"best_match": best, "scores": scores}, ensure_ascii=False)


__all__ = [
    "parse_csv_str", "extract_entities", "classify_text",
    # Legacy unsafe — disabled, use seekflow.tools.builtins instead:
    "fetch_url", "run_python", "query_sql",
]
