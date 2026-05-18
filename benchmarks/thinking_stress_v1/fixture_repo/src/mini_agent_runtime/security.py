"""Path sandbox and SSRF protection layer.

BUGS:
- safe_join uses unsafe string prefix check (bypassable with ../, %2e%2e/, symlinks).
- validate_url only blocks literal 'localhost' and '127.', missing private IPs,
  IPv6 loopback, metadata endpoint, integer/hex IP forms.
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from urllib.parse import urlparse


def safe_join(workspace_root: str, user_path: str) -> Path:
    """Join user path inside workspace.

    BUG:
    - String prefix check is unsafe.
    - Does not decode percent-encoded traversal.
    - Does not resolve symlinks.
    """
    root = Path(workspace_root)
    candidate = root / user_path
    if not str(candidate).startswith(str(root)):
        raise ValueError("path escapes workspace")
    return candidate


def validate_url(url: str, allowed_domains: set[str] | None = None) -> bool:
    """Validate URL for network tools.

    BUG:
    - Only checks scheme and literal localhost.
    - Does not block private IPs, metadata IP, IPv6 loopback, decimal IP.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False

    host = parsed.hostname or ""
    if "localhost" in host or host.startswith("127."):
        return False

    if allowed_domains and host not in allowed_domains:
        return False

    return True
