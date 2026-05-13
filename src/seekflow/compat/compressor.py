"""Context Compressor — LLM-based structured summarization.

Inspired by Claude Code's /compact: generates a structured 6-section
summary of dropped context rather than just truncating. Falls back to
heuristic text-snippet when no LLM summarizer is available.

Design principles (from Claude Code research):
1. Append-only history — compression creates summaries, never deletes
2. Structured format — XML-tagged sections for better model comprehension
3. Recent verbatim — last N messages preserved word-for-word
4. Layered compression — old→summary, mid→compressed, new→verbatim
"""
from __future__ import annotations

import warnings
from typing import Any


class ContextCompressor:
    """LLM-based context compression with structured summaries.

    Usage:
        # Heuristic mode (no API call):
        cc = ContextCompressor(max_tokens=900000)
        compressed = cc.compress(messages)

        # LLM mode (intelligent summarization):
        cc = ContextCompressor(max_tokens=900000, summarizer_agent=my_agent)
        compressed = cc.compress(messages)
    """

    def __init__(self, max_tokens: int = 900000, keep_last: int = 4,
                 summarizer_agent: Any = None):
        self._max_tokens = max_tokens
        self._keep_last = keep_last
        self._summarizer = summarizer_agent
        self._compression_count = 0

    def should_compress(self, messages: list[dict]) -> bool:
        return self._estimate_tokens(messages) > self._max_tokens

    def compress(self, messages: list[dict]) -> list[dict]:
        if not self.should_compress(messages):
            return messages

        self._compression_count += 1
        removed = len(messages) - self._keep_last
        warnings.warn(
            f"ContextCompressor #{self._compression_count}: compressing "
            f"{len(messages)} messages → ~{self._keep_last + 2} segments "
            f"(removed {removed} older messages)."
        )

        system = messages[0] if messages and messages[0].get("role") == "system" else None
        rest = messages[1:] if system else list(messages)

        if len(rest) <= self._keep_last:
            return messages

        older = rest[:-self._keep_last]
        recent = rest[-self._keep_last:]

        # Try LLM summarization, fall back to heuristic
        if self._summarizer is not None:
            summary = self._llm_summarize(older)
        else:
            summary = self._heuristic_summarize(older)

        compressed = []
        if system:
            compressed.append(system)
        compressed.append({
            "role": "system",
            "content": self._format_summary(summary),
        })
        compressed.extend(recent)
        return compressed

    # ── LLM-based summarization (Claude Code style) ──────────────

    def _llm_summarize(self, messages: list[dict]) -> dict:
        """Ask the summarizer agent to produce a structured summary."""
        raw = self._format_messages(messages)
        prompt = (
            "请将以下对话历史压缩为结构化摘要。保留所有关键信息。\n\n"
            "<summary_format>\n"
            "1. 主要请求和意图\n"
            "2. 关键发现和决策\n"
            "3. 错误和修复\n"
            "4. 已完成的步骤\n"
            "5. 待处理事项\n"
            "6. 重要上下文（文件、数据、约束）\n"
            "</summary_format>\n\n"
            f"对话历史:\n{raw[:12000]}\n\n"
            "请用中文输出上述6个章节的结构化摘要。每个章节2-4句话。"
        )
        try:
            result = self._summarizer.run(prompt)
            return {"llm_summary": result.final_output}
        except Exception as e:
            warnings.warn(f"LLM summarization failed ({e}), falling back to heuristic")
            return self._heuristic_summarize(messages)

    # ── Heuristic fallback ───────────────────────────────────────

    @staticmethod
    def _heuristic_summarize(messages: list[dict]) -> dict:
        sections: dict[str, list[str]] = {
            "requests": [], "decisions": [], "errors": [],
            "completed": [], "pending": [], "context": [],
        }
        for m in messages:
            content = str(m.get("content", ""))[:300]
            if not content.strip():
                continue
            role = m.get("role", "unknown")
            if role == "user":
                sections["requests"].append(content[:150])
            elif "error" in content.lower() or "错误" in content or "fail" in content.lower():
                sections["errors"].append(content[:200])
            elif role == "assistant":
                sections["decisions"].append(content[:150])
            elif role == "tool":
                sections["context"].append(content[:200])

        return {
            "heuristic": True,
            "requests": sections["requests"][-3:],
            "decisions": sections["decisions"][-3:],
            "errors": sections["errors"][-2:],
            "context": sections["context"][-3:],
        }

    @staticmethod
    def _format_summary(summary: dict) -> str:
        if summary.get("llm_summary"):
            return f"[压缩上下文 #{summary.get('compression_id', '')}]\n{summary['llm_summary']}"

        parts = ["[压缩上下文 — 启发式摘要]"]
        if summary.get("requests"):
            parts.append("请求: " + "; ".join(summary["requests"]))
        if summary.get("decisions"):
            parts.append("决策: " + "; ".join(summary["decisions"]))
        if summary.get("errors"):
            parts.append("错误: " + "; ".join(summary["errors"]))
        if summary.get("context"):
            parts.append("上下文: " + "; ".join(summary["context"]))
        return "\n".join(parts)

    # ── Helpers ──────────────────────────────────────────────────

    @staticmethod
    def _estimate_tokens(messages: list[dict]) -> int:
        from seekflow.token_counter import count_tokens
        return count_tokens(messages)

    @staticmethod
    def _format_messages(messages: list[dict]) -> str:
        parts = []
        for m in messages:
            role = m.get("role", "unknown")
            content = str(m.get("content", ""))[:800]
            if content.strip():
                parts.append(f"[{role}]: {content}")
        return "\n".join(parts)
