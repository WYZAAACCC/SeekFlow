"""Built-in tools — commonly needed functions for DeepSeek agents."""
from __future__ import annotations

import json
import re
from pathlib import Path


def fetch_url(url: str, timeout: int = 15) -> str:
    """HTTP GET request. Returns response text (max 8000 chars)."""
    import urllib.request as _ur
    try:
        req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with _ur.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            if len(text) > 8000:
                text = text[:8000] + "\n...[truncated]"
            return text
    except Exception as e:
        return f"Fetch failed: {e}"


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
    """Execute Python code in a subprocess sandbox. Returns stdout."""
    import subprocess, tempfile, os as _os
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False)
    try:
        tmp.write(code)
        tmp.close()
        result = subprocess.run(
            ["python", tmp.name], capture_output=True, text=True,
            timeout=timeout,
        )
        out = result.stdout[:4000]
        if result.stderr:
            out += f"\n[stderr]: {result.stderr[:1000]}"
        return out or "[no output]"
    except subprocess.TimeoutExpired:
        return f"[timeout after {timeout}s]"
    except Exception as e:
        return f"Execution failed: {e}"
    finally:
        try:
            _os.unlink(tmp.name)
        except Exception:
            pass


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
    """Execute a SQLite query. Returns JSON array of rows."""
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.execute(query)
        rows = [dict(zip([c[0] for c in cur.description], row)) for row in cur.fetchall()]
        conn.close()
        return json.dumps(rows, ensure_ascii=False, indent=2)[:8000]
    except Exception as e:
        return f"SQL query failed: {e}"


def classify_text(text: str, labels: str) -> str:
    """Simple keyword-based classification. labels = comma-separated."""
    label_list = [l.strip() for l in labels.split(",")]
    text_lower = text.lower()
    scores = {}
    for label in label_list:
        scores[label] = text_lower.count(label.lower())
    best = max(scores, key=scores.get) if scores else "unknown"
    return json.dumps({"best_match": best, "scores": scores}, ensure_ascii=False)


__all__ = ["fetch_url", "parse_csv_str", "run_python", "extract_entities",
           "query_sql", "classify_text"]
