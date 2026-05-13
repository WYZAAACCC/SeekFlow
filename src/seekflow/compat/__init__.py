"""SeekFlow v3 compatibility bridge — zero hard dependencies on LangChain/CrewAI."""
from seekflow.compat.bridge import (
    from_langchain_document,
    from_langchain_documents,
    from_langchain_tool,
    from_crewai_agent,
    from_crewai_tool,
)
from seekflow.compat.documents import DocumentLike, to_agent_text, validate_document
from seekflow.compat.embeddings import EmbeddingFunction, VectorStoreLike

__all__ = [
    "from_langchain_document",
    "from_langchain_documents",
    "from_langchain_tool",
    "from_crewai_agent",
    "from_crewai_tool",
    "DocumentLike",
    "to_agent_text",
    "validate_document",
    "EmbeddingFunction",
    "VectorStoreLike",
]
