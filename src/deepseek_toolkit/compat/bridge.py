"""Integration bridge — convert LangChain/CrewAI objects to DTK format.

Zero hard dependency on LangChain or CrewAI. Everything is duck-typed.
"""
from __future__ import annotations

from typing import Any


def from_langchain_document(lc_doc: Any) -> dict:
    """Convert a LangChain Document to DTK DocumentLike dict."""
    return {
        "page_content": getattr(lc_doc, "page_content", ""),
        "metadata": dict(getattr(lc_doc, "metadata", {}) or {}),
    }


def from_langchain_documents(lc_docs: list[Any]) -> list[dict]:
    """Convert a list of LangChain Documents."""
    return [from_langchain_document(d) for d in lc_docs]


def from_langchain_tool(lc_tool: Any) -> Any:
    """Wrap a LangChain @tool function for DTK Agent.

    LangChain tools decorated with @tool have .name, .description, .func.
    Returns the underlying callable that DTK can use directly.
    """
    if hasattr(lc_tool, "func"):
        return lc_tool.func
    if callable(lc_tool):
        return lc_tool
    raise TypeError(f"Cannot convert {type(lc_tool)} to DTK tool")


def from_crewai_agent(ca_agent: Any) -> dict:
    """Extract CrewAI Agent config for DTK Agent creation."""
    return {
        "role": getattr(ca_agent, "role", ""),
        "goal": getattr(ca_agent, "goal", ""),
        "backstory": getattr(ca_agent, "backstory", ""),
    }


def from_crewai_tool(ca_tool: Any) -> Any:
    """Wrap a CrewAI @tool function for DTK Agent."""
    if hasattr(ca_tool, "func"):
        return ca_tool.func
    if callable(ca_tool):
        return ca_tool
    raise TypeError(f"Cannot convert {type(ca_tool)} to DTK tool")


__all__ = [
    "from_langchain_document", "from_langchain_documents",
    "from_langchain_tool", "from_crewai_agent", "from_crewai_tool",
]
