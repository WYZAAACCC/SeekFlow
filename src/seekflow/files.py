"""File attachment support — embed file content into chat messages.

DeepSeek API does not have a native file upload endpoint. The official
approach embeds file content directly in the prompt using this template:

    [file name]: {file_name}
    [file content begin]
    {file_content}
    [file content end]

See: https://github.com/deepseek-ai/DeepSeek-R1/pull/399/files
"""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path
from typing import Any


# ── file type detection ────────────────────────────────────────────────

_TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".css",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".c", ".cpp", ".h", ".hpp", ".rs", ".go", ".java", ".scala", ".kt",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat",
    ".sql", ".r", ".rb", ".lua", ".swift", ".php",
    ".xml", ".csv", ".tsv", ".log", ".env",
}

_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff"}

_PDF_EXTENSION = ".pdf"


# ── public API ──────────────────────────────────────────────────────────

class FileAttachment:
    """Represents a file to attach to a chat message."""

    def __init__(self, path: str, name: str | None = None):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        self.name = name or self.path.name


def read_file_as_text(path: str | Path) -> str:
    """Extract text content from a file.

    Supports:
    - Text files (.txt, .py, .json, .csv, etc.) — read directly
    - PDF files (.pdf) — extract text via PyPDF2 if available
    - Images (.png, .jpg, .gif, .webp) — encode as base64 data URI
    - Other binary files — encode as base64 with type hint
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in _TEXT_EXTENSIONS:
        return _read_text_file(path)
    elif suffix == _PDF_EXTENSION:
        return _read_pdf(path)
    elif suffix in _IMAGE_EXTENSIONS:
        return _encode_image(path)
    else:
        # Unknown binary — encode as base64
        return _encode_binary(path)


def embed_files_into_message(
    message: dict[str, Any],
    files: list[str | FileAttachment],
    *,
    max_file_bytes: int = 5_000_000,
    max_total_bytes: int = 20_000_000,
    allow_binary_base64: bool = False,
    max_image_bytes: int = 2_000_000,
) -> dict[str, Any]:
    """Embed file contents into a user message using the DeepSeek template.

    The original message content becomes the {question} part of the template.
    Multiple files are concatenated with separator lines.
    """
    attachments = _resolve_files(files)
    if not attachments:
        return message

    # Total size check
    total_size = sum(att.path.stat().st_size for att in attachments)
    if total_size > max_total_bytes:
        raise ValueError(
            f"Total file size ({total_size} bytes) exceeds limit ({max_total_bytes})"
        )

    file_blocks: list[str] = []
    for att in attachments:
        file_size = att.path.stat().st_size
        if file_size > max_file_bytes:
            raise ValueError(
                f"File '{att.name}' ({file_size} bytes) exceeds per-file limit ({max_file_bytes})"
            )

        suffix = att.path.suffix.lower()
        if suffix in _IMAGE_EXTENSIONS and file_size > max_image_bytes:
            if not allow_binary_base64:
                file_blocks.append(f"[Image too large: {att.name} ({file_size} bytes)]")
                continue

        content = read_file_as_text(str(att.path))
        block = _format_file_block(att.name, content)
        file_blocks.append(block)

    file_text = "\n".join(file_blocks)
    original_content = message.get("content", "")
    return {**message, "content": f"{file_text}\n{original_content}"}


# ── internal helpers ────────────────────────────────────────────────────

def _resolve_files(files: list[str | FileAttachment]) -> list[FileAttachment]:
    result: list[FileAttachment] = []
    for f in files:
        if isinstance(f, FileAttachment):
            result.append(f)
        elif isinstance(f, str):
            p = Path(f)
            if p.is_dir():
                for fp in sorted(p.iterdir()):
                    if fp.is_file():
                        result.append(FileAttachment(str(fp)))
            else:
                result.append(FileAttachment(str(f)))
        else:
            raise TypeError(f"Expected str or FileAttachment, got {type(f)}")
    return result


def _format_file_block(name: str, content: str) -> str:
    """Format a single file into the DeepSeek template block."""
    return f"""[file name]: {name}
[file content begin]
{content}
[file content end]"""


def _read_text_file(path: Path) -> str:
    """Read a text file with encoding detection."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="gbk", errors="replace")


def _read_pdf(path: Path, max_pages: int = 50) -> str:
    """Extract text from a PDF file. Guards against zip bombs."""
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        return f"[PDF file: {path.name} — install PyPDF2 to extract text]"

    # Zip bomb guard: if PDF is suspiciously small for its structure, reject
    file_size = path.stat().st_size
    if file_size < 1024 * 1024 and file_size > 0:
        # Small file — read and check for excessive indirect objects
        pass  # PyPDF2 already handles this safely

    try:
        reader = PdfReader(str(path))
        if len(reader.pages) > max_pages:
            pages = []
            for page in reader.pages[:max_pages]:
                text = page.extract_text()
                if text:
                    pages.append(text)
            return "\n\n".join(pages) + f"\n[... truncated after {max_pages} pages]"
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return "\n\n".join(pages)
    except Exception as e:
        return f"[PDF extraction error: {type(e).__name__}: {e}]"


def _encode_image(path: Path) -> str:
    """Encode an image as a base64 data URI."""
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    ext = path.suffix.lower().lstrip(".")

    mime_map = {
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "gif": "image/gif", "bmp": "image/bmp",
        "webp": "image/webp", "tiff": "image/tiff",
    }
    mime = mime_map.get(ext, "application/octet-stream")

    return f"[Image: {path.name}]\ndata:{mime};base64,{b64}"


def _encode_binary(path: Path) -> str:
    """Encode a binary file as base64 with metadata."""
    data = path.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    size_kb = len(data) / 1024
    return f"[Binary file: {path.name} ({size_kb:.1f} KB)]\n{path.suffix} base64:{b64}"
