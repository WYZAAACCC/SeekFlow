"""Safe network tool factory — SSRF-hardened HTTP fetch using hardened client."""
from __future__ import annotations

from seekflow.tools.decorator import tool
from seekflow.types import ToolPolicy


def make_fetch_url(
    *,
    allowed_domains: set[str],
    https_only: bool = True,
    timeout: float = 10.0,
    max_response_bytes: int = 1_000_000,
) -> "ToolDefinition":
    """Create an SSRF-hardened fetch_url tool bound to specific domains.

    Uses ``fetch_url_hardened()`` from ``security.http`` which enforces:
    DNS fail-closed, all-IP checking, per-redirect validation, userinfo rejection.
    """
    if not allowed_domains:
        raise ValueError("make_fetch_url requires non-empty allowed_domains")

    @tool(trusted=False)
    def fetch_url(url: str) -> str:
        from seekflow.security.http import (
            NetworkPolicy, fetch_url_hardened, SSRFError,
        )
        policy = NetworkPolicy(
            allowed_domains=allowed_domains,
            allowed_schemes={"https"} if https_only else {"https", "http"},
            max_response_bytes=max_response_bytes,
            timeout_s=timeout,
        )
        try:
            return fetch_url_hardened(url, policy)
        except SSRFError as e:
            return f"Fetch blocked: {e}"

    return fetch_url.with_policy(ToolPolicy(
        capabilities={"network.public_http"},
        risk="network",
        allowed_domains=allowed_domains,
        url_params=frozenset({"url"}),
        timeout_s=timeout,
        max_input_bytes=20_000,
        max_output_bytes=max_response_bytes,
        parallel_safe=True,
    ))
