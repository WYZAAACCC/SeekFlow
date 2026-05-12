"""Vector Store Protocol — re-exports from embeddings module."""
from deepseek_toolkit.compat.embeddings import VectorStoreLike, EmbeddingFunction, get_embedding_dim

__all__ = ["VectorStoreLike", "EmbeddingFunction", "get_embedding_dim"]
