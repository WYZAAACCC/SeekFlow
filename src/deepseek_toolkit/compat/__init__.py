"""DTK v3 compatibility bridge — zero hard dependencies on LangChain/CrewAI."""
from deepseek_toolkit.compat.bridge import (
    from_langchain_document,
    from_langchain_documents,
    from_langchain_tool,
    from_crewai_agent,
    from_crewai_tool,
)
from deepseek_toolkit.compat.documents import DocumentLike, to_agent_text, validate_document
from deepseek_toolkit.compat.embeddings import EmbeddingFunction, VectorStoreLike

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
