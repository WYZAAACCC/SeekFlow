"""Embedding Function and Vector Store Protocols."""
from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

from seekflow.compat.documents import DocumentLike

# Embedding function: takes text, returns vector
EmbeddingFunction = Callable[[str], list[float]]


@runtime_checkable
class VectorStoreLike(Protocol):
    """Any object with search capability is a Vector Store."""

    def search(
        self, query: str | list[float], top_k: int = 5
    ) -> list[DocumentLike]: ...


def get_embedding_dim(fn: EmbeddingFunction, sample_text: str = "test") -> int:
    """Infer embedding dimension by running the function once."""
    vec = fn(sample_text)
    return len(vec)
