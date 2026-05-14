"""Safe network tool factory — SSRF-hardened HTTP fetch."""
from __future__ import annotations

from seekflow.security import validate_url
from seekflow.tools.decorator import tool
from seekflow.types import ToolPolicy


def make_fetch_url(
    *,
    allowed_domains: set[str],
    https_only: bool = True,
    timeout: float = 10.0,
    max_response_bytes: int = 1_000_000,
) -> "ToolDefinition":
    """Create an SSRF-hardened fetch_url tool bound to specific domains."""

    @tool(trusted=False)
    def fetch_url(url: str) -> str:
        import urllib.request as _ur

        if not validate_url(
            url,
            allow_domains=allowed_domains,
            allow_schemes={"https"} if https_only else {"https", "http"},
        ):
            return f"Fetch blocked: URL '{url[:200]}' failed security validation"

        try:
            req = _ur.Request(url, headers={"User-Agent": "SeekFlow/1.0"})
            with _ur.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if len(raw) > max_response_bytes:
                    raw = raw[:max_response_bytes]
                text = raw.decode("utf-8", errors="replace")
                return text
        except Exception as e:
            return f"Fetch failed: {e}"

    return fetch_url.with_policy(ToolPolicy(
        capabilities={"network.public_http"},
        risk="network",
        allowed_domains=allowed_domains,
        timeout_s=timeout,
        max_output_bytes=max_response_bytes,
        parallel_safe=True,
    ))
