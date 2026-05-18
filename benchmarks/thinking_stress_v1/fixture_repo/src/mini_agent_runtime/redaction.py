"""Secret redaction for log and trace safety.

BUG: only redacts sk- style keys. Missing: Bearer tokens, AWS keys, JWTs,
URL query tokens, and other common credential patterns.
"""

from __future__ import annotations

import re


def redact_secrets(text: str) -> str:
    """Redact secrets from logs.

    BUG:
    Only redacts sk- style keys.
    """
    text = re.sub(r"sk-[A-Za-z0-9]{8,}", "sk-REDACTED", text)
    return text
