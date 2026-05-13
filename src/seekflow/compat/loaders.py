"""Document loaders — CSV, JSON, Markdown, PDF support.

Zero mandatory external deps. PDF uses PyPDF2 if available.
All loaders return DocumentLike-compatible dicts.
"""
from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any


def load_csv(path: str, encoding: str = "utf-8") -> list[dict]:
    """Load CSV file as documents (one per row)."""
    text = Path(path).read_text(encoding=encoding)
    reader = csv.DictReader(StringIO(text))
    docs = []
    for i, row in enumerate(reader):
        docs.append({
            "page_content": json.dumps(row, ensure_ascii=False),
            "metadata": {"source": path, "row": i},
        })
    return docs


def load_json(path: str, encoding: str = "utf-8") -> list[dict]:
    """Load JSON file as documents."""
    text = Path(path).read_text(encoding=encoding)
    data = json.loads(text)
    if isinstance(data, list):
        return [{
            "page_content": json.dumps(item, ensure_ascii=False),
            "metadata": {"source": path, "index": i},
        } for i, item in enumerate(data)]
    return [{
        "page_content": json.dumps(data, ensure_ascii=False, indent=2),
        "metadata": {"source": path},
    }]


def load_markdown(path: str, encoding: str = "utf-8") -> list[dict]:
    """Load Markdown file as a single document."""
    text = Path(path).read_text(encoding=encoding)
    return [{"page_content": text, "metadata": {"source": path, "format": "markdown"}}]


def load_text(path: str, encoding: str = "utf-8") -> list[dict]:
    """Load plain text file as a single document."""
    text = Path(path).read_text(encoding=encoding)
    return [{"page_content": text, "metadata": {"source": path, "format": "text"}}]


def load_pdf(path: str) -> list[dict]:
    """Load PDF file as documents (one per page). Requires PyPDF2."""
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        raise ImportError(
            "PDF support requires PyPDF2. Install with: pip install PyPDF2"
        )
    reader = PdfReader(path)
    docs = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text()
        if text and text.strip():
            docs.append({
                "page_content": text,
                "metadata": {"source": path, "page": i + 1},
            })
    return docs


def auto_load(path: str) -> list[dict]:
    """Auto-detect file type and load accordingly."""
    suffix = Path(path).suffix.lower()
    loaders = {
        ".csv": load_csv,
        ".json": load_json,
        ".md": load_markdown,
        ".txt": load_text,
        ".pdf": load_pdf,
    }
    loader = loaders.get(suffix)
    if loader is None:
        raise ValueError(
            f"Unsupported file type: {suffix}. "
            f"Supported: {list(loaders.keys())}"
        )
    return loader(path)


__all__ = ["load_csv", "load_json", "load_markdown", "load_text",
           "load_pdf", "auto_load"]
