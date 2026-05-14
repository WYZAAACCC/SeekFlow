"""Prompt cache stabilization — Reasonix-inspired byte-stable prefix management.

DeepSeek caches the longest matching byte-prefix across sequential requests.
Cache hit = 10x cheaper input tokens. But any change to the prefix (system
prompt, tool schemas, early messages) invalidates the ENTIRE cache.

This module provides proactive cache stability:
1. CacheStabilizer — freezes the cacheable prefix at session start
2. CacheSentinel — detects prefix changes (passive, for logging)
3. append_only_context — replaces destructive trimming with compression

Key insight from Reasonix: cache stability is an architectural invariant,
not an optional feature. Every byte in the prefix matters.
"""

from __future__ import annotations

import hashlib
import json
import warnings
from dataclasses import dataclass, field
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════
# CacheStabilizer — proactive cache management (Reasonix Pillar 1)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class StablePrefix:
    """A frozen, byte-stable prefix for the session.

    The prefix is built ONCE at session start and never modified.
    DeepSeek will cache this prefix across all subsequent requests
    as long as it appears at the start of every messages array.
    """
    system_prompt: str = ""
    tool_schemas_json: str = ""
    frozen_bytes: bytes = b""
    frozen_hash: str = ""
    frozen_at: float = 0.0

    def is_valid(self, messages: list[dict]) -> bool:
        """Check if the current messages still start with the frozen prefix."""
        if not self.frozen_bytes or not messages:
            return False
        first = messages[0]
        if first.get("role") != "system":
            return False
        current = first.get("content", "").encode("utf-8")
        return current.startswith(self.frozen_bytes)


class CacheStabilizer:
    """Proactive cache stability — freeze prefix, detect drift, auto-repair.

    Usage:
        stabilizer = CacheStabilizer()
        stabilizer.freeze(system_prompt, tool_schemas_json)

        # Before each API call:
        messages = stabilizer.ensure_stable_prefix(messages)

        # After each call:
        stabilizer.record_request(success=True)
    """

    def __init__(self, warn_on_drift: bool = True):
        self._prefix: StablePrefix | None = None
        self._warn_on_drift = warn_on_drift
        self._drift_count = 0
        self._request_count = 0

    def freeze(self, system_prompt: str, tool_schemas: list[dict] | None = None) -> StablePrefix:
        """Freeze the cacheable prefix for this session.

        Must be called ONCE at session start. After freezing, the system
        prompt and tool schemas become immutable constants.
        """
        import time
        # Serialize tool schemas deterministically (sorted keys, no whitespace variance)
        tools_json = ""
        if tool_schemas:
            tools_json = json.dumps(tool_schemas, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

        # The cacheable prefix is: system_prompt [+ tool_schemas if appended to system]
        prefix = system_prompt.encode("utf-8")
        self._prefix = StablePrefix(
            system_prompt=system_prompt,
            tool_schemas_json=tools_json,
            frozen_bytes=prefix,
            frozen_hash=hashlib.sha256(prefix).hexdigest()[:16],
            frozen_at=time.time(),
        )
        return self._prefix

    def ensure_stable_prefix(self, messages: list[dict]) -> list[dict]:
        """Ensure messages start with the frozen prefix for cache stability.

        DeepSeek caches from the START of the messages array. If the first
        message's content has drifted (e.g., dynamic data appended), we
        strip the drift and emit a warning.
        """
        if self._prefix is None:
            return messages

        self._request_count += 1

        if not messages:
            return messages

        first = messages[0]
        if first.get("role") != "system":
            # No system message — cache won't work. Add frozen prefix.
            msg = {"role": "system", "content": self._prefix.system_prompt}
            return [msg] + list(messages)

        current = first.get("content", "")
        if not current.startswith(self._prefix.system_prompt):
            # System prompt has been modified — this kills cache
            self._drift_count += 1
            if self._warn_on_drift:
                warnings.warn(
                    f"Cache prefix DRIFT detected (request #{self._request_count}). "
                    f"Cache INVALIDATED. System prompt changed from frozen prefix. "
                    f"Dynamic content should be appended AFTER the frozen system prompt, "
                    f"not inserted into it. "
                    f"Drift count: {self._drift_count}/{self._request_count} requests.",
                    UserWarning,
                    stacklevel=2,
                )
            # Auto-repair: replace with frozen prefix + append drift as user context
            drift = current[len(self._prefix.system_prompt):].strip()
            repaired = [{"role": "system", "content": self._prefix.system_prompt}]
            repaired.extend(messages[1:])  # Keep user messages etc.
            if drift:
                # Append drift content as a separate user-prefixed context note
                repaired.insert(1, {"role": "user", "content": f"[Context]\n{drift}"})
            return repaired

        return messages

    @property
    def cache_health(self) -> dict[str, Any]:
        """Return cache health metrics."""
        return {
            "prefix_frozen": self._prefix is not None,
            "prefix_hash": self._prefix.frozen_hash if self._prefix else None,
            "drift_count": self._drift_count,
            "request_count": self._request_count,
            "drift_rate": self._drift_count / max(self._request_count, 1),
            "cache_stable": self._drift_count == 0,
        }


# ═══════════════════════════════════════════════════════════════════════════
# CacheSentinel — passive cache observation (kept for backward compat)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class CacheAdvice:
    status: str  # "first_request", "stable", "changed"
    message: str = ""


class CacheSentinel:
    """Detects prefix changes that would invalidate the prompt cache."""

    def __init__(self):
        self._prefix_hash: int | None = None

    def check(self, messages: list[dict]) -> CacheAdvice:
        prefix = self._extract_prefix(messages)
        h = hash(prefix)
        if self._prefix_hash is None:
            self._prefix_hash = h
            return CacheAdvice("first_request", "Cache baseline established.")
        if h != self._prefix_hash:
            self._prefix_hash = h
            return CacheAdvice(
                "changed",
                "Cache prefix changed — cache invalidated. "
                "Keep system message stable for best cache performance.",
            )
        return CacheAdvice("stable", "Cache prefix matches previous request.")

    @staticmethod
    def _extract_prefix(messages: list[dict]) -> tuple:
        return tuple(
            (m.get("role"), m.get("content"))
            for m in messages
            if m.get("role") == "system"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Append-only context management (replaces destructive trimming)
# ═══════════════════════════════════════════════════════════════════════════

def append_only_compress(
    messages: list[dict],
    max_context_tokens: int,
) -> list[dict]:
    """Compress context while preserving the cacheable prefix.

    Unlike _trim_messages() which removes old messages (destroying cache),
    this function KEEPS the system prefix intact and compresses old
    conversation turns into a stable summary appended as a system note.

    The byte-stable prefix (system message) never changes — cache is preserved.
    """
    from seekflow.token_counter import count_tokens

    if not messages or count_tokens(messages) <= max_context_tokens:
        return messages

    system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
    rest = messages[1:] if system_msg else list(messages)

    # Keep last N turns verbatim (newest messages)
    KEEP_LAST = 6  # Keep last 3 user-assistant pairs

    if len(rest) <= KEEP_LAST:
        return messages

    older = rest[:-KEEP_LAST]
    recent = rest[-KEEP_LAST:]

    # Compress older messages into a stable summary
    summary = _heuristic_summarize(older)

    result = []
    if system_msg:
        # Original system message preserved exactly — cache prefix intact
        result.append(dict(system_msg))
        # Compressed context as a SEPARATE user message — never alters system
        result.append({
            "role": "user",
            "content": (
                f"[Compressed Context — {len(older)} older messages summarized]\n"
                f"{summary}"
            ),
        })
    else:
        result.append({
            "role": "system",
            "content": "You are a helpful assistant.",
        })
        result.append({
            "role": "user",
            "content": f"[Compressed Context]\n{summary}",
        })
    result.extend(recent)
    return result


def _heuristic_summarize(messages: list[dict]) -> str:
    """Create a brief, stable summary of older messages."""
    parts: list[str] = []
    requests: list[str] = []
    errors: list[str] = []
    key_facts: list[str] = []

    for m in messages:
        content = str(m.get("content", ""))[:300]
        if not content.strip():
            continue
        role = m.get("role", "unknown")
        if role == "user":
            requests.append(content[:150])
        elif role == "tool":
            # Extract key numbers/facts from tool results
            if len(content) < 200:
                key_facts.append(content[:100])
        elif "error" in content.lower():
            errors.append(content[:100])
        elif role == "assistant" and len(content) > 50:
            key_facts.append(content[:120])

    if requests:
        parts.append("Requests: " + " | ".join(requests[-5:]))
    if key_facts:
        parts.append("Key findings: " + " | ".join(key_facts[-5:]))
    if errors:
        parts.append("Errors: " + " | ".join(errors[-3:]))

    return "\n".join(parts) if parts else "[No significant content to summarize]"


def extract_cached_tokens(usage: dict) -> int:
    """Extract cached token count from usage dict."""
    details = usage.get("prompt_tokens_details", {}) or {}
    return details.get("cached_tokens", 0)


# ═══════════════════════════════════════════════════════════════════════════
# Cache Compiler — proactive prefix analysis and optimization
# ═══════════════════════════════════════════════════════════════════════════

class CacheCompiler:
    """Compile system prompt + tools into a cache-optimized prefix.

    Usage:
        compiler = CacheCompiler()
        compiled = compiler.compile(system_prompt, tools_schema)
        # compiled.prefix_bytes, compiled.cacheable_byte_range
    """

    def compile(
        self,
        system_prompt: str,
        tool_schemas: list[dict] | None = None,
        strategy: str = "max_prefix_stability",
    ) -> dict:
        """Compile the cacheable prefix for a session."""
        tools_json = ""
        if tool_schemas:
            tools_json = json.dumps(
                tool_schemas, sort_keys=True, ensure_ascii=False,
                separators=(",", ":"),
            )

        prefix = system_prompt.encode("utf-8")
        prefix_hash = hashlib.sha256(prefix).hexdigest()[:16]

        return {
            "prefix_bytes": prefix,
            "prefix_hash": prefix_hash,
            "system_prompt_length": len(prefix),
            "tools_schema_json": tools_json,
            "tools_schema_hash": hashlib.sha256(
                tools_json.encode("utf-8")
            ).hexdigest()[:16] if tools_json else "",
            "cacheable_byte_range": (0, len(prefix)),
            "strategy": strategy,
        }

    def predict_cache_hit(
        self, compiled: dict, messages: list[dict],
    ) -> dict:
        """Predict whether the first message matches the compiled prefix."""
        if not messages:
            return {"hit": False, "confidence": 0.0,
                    "matched_bytes": 0, "total_prefix_bytes": len(compiled["prefix_bytes"])}

        first = messages[0]
        if first.get("role") != "system":
            return {"hit": False, "confidence": 0.0,
                    "matched_bytes": 0, "total_prefix_bytes": len(compiled["prefix_bytes"])}

        current = first.get("content", "").encode("utf-8")
        prefix = compiled["prefix_bytes"]
        matched = 0
        for a, b in zip(current, prefix):
            if a == b:
                matched += 1
            else:
                break

        total = len(prefix)
        confidence = matched / max(total, 1)
        return {
            "hit": matched == total,
            "confidence": round(confidence, 4),
            "matched_bytes": matched,
            "total_prefix_bytes": total,
        }
