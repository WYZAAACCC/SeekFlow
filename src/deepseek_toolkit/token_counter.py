"""Token counting for DeepSeek models.

Uses tiktoken when available, falls back to character/4 estimation.
"""
from __future__ import annotations

try:
    import tiktoken
    _HAS_TIKTOKEN = True
except ImportError:
    _HAS_TIKTOKEN = False

_ENCODING_NAME = "cl100k_base"
_ENCODING_CACHE: dict[str, object] = {}  # model -> encoding instance


def count_tokens(messages: list[dict], model: str = "deepseek-v4-pro") -> int:
    """Count tokens for a list of chat messages."""
    if not messages:
        return 0

    total = 0
    for msg in messages:
        content = msg.get("content") or ""
        if isinstance(content, str):
            total += count_text(content)

        # Count reasoning_content
        rc = msg.get("reasoning_content")
        if rc:
            total += count_text(rc)

        # Count tool calls
        for tc in msg.get("tool_calls", []) or []:
            func = tc.get("function", {})
            total += count_text(func.get("name", ""))
            total += count_text(func.get("arguments", ""))

        # Message overhead (~4 tokens per message)
        total += 4

    return total


def count_text(text: str, model: str = "deepseek-v4-pro") -> int:
    """Count tokens for a single text string.

    Uses tiktoken when available. For Chinese text, applies a
    correction factor — cl100k_base underestimates Chinese by 20-40%.
    Each CJK character counts as ~1.5 tokens (not ~0.3 as char/4 would).
    """
    if _HAS_TIKTOKEN:
        if _ENCODING_NAME not in _ENCODING_CACHE:
            _ENCODING_CACHE[_ENCODING_NAME] = tiktoken.get_encoding(_ENCODING_NAME)
        enc = _ENCODING_CACHE[_ENCODING_NAME]
        return len(enc.encode(text))

    # Fallback with Chinese-awareness: count CJK chars separately
    cjk = sum(1 for c in text if '一' <= c <= '鿿' or '㐀' <= c <= '䶿')
    non_cjk = len(text) - cjk
    # Chinese: ~1.5 tokens/char, non-Chinese: ~0.25 tokens/char (4 chars/token)
    return max(1, int(cjk * 1.5 + non_cjk / 4))
