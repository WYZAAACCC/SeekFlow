"""Document Protocol — accept LangChain Documents and plain text.

No runtime dependency on LangChain. Uses duck typing.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DocumentLike(Protocol):
    """Any object with page_content and metadata is a Document."""
    page_content: str
    metadata: dict


def to_agent_text(docs: list[Any]) -> str:
    """Convert a list of Document-like objects to Agent-readable text."""
    parts: list[str] = []
    for i, doc in enumerate(docs):
        # Handle dict — wrap as DocumentLike
        if isinstance(doc, dict):
            content = doc.get("page_content", "")
            meta = doc.get("metadata", {})
        elif isinstance(doc, str):
            content = doc
            meta = {"source": f"inline-{i}"}
        elif hasattr(doc, "page_content"):
            content = doc.page_content
            meta = getattr(doc, "metadata", {})
        else:
            raise TypeError(
                f"Unsupported document type: {type(doc)}. "
                f"Expected: DocumentLike (page_content + metadata), dict, or str."
            )
        source = meta.get("source", f"document-{i}")
        # Sanitize: ensure UTF-8, replace non-decodable bytes
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        elif isinstance(content, str):
            content = content.encode("utf-8", errors="replace").decode("utf-8")
        parts.append(f"## {source}\n\n{content}")
    return "\n\n".join(parts)


def validate_document(obj: Any) -> bool:
    """Check if an object satisfies the DocumentLike protocol."""
    return (
        hasattr(obj, "page_content")
        and isinstance(getattr(obj, "page_content"), str)
        and hasattr(obj, "metadata")
        and isinstance(getattr(obj, "metadata"), dict)
    )
