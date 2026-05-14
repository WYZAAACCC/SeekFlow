"""Hardened HTTP client with strict SSRF protection."""
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse

BLOCKED_HOSTS: frozenset[str] = frozenset({
    "localhost", "metadata.google.internal",
})

PRIVATE_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.IPv4Network("0.0.0.0/8"),
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("127.0.0.0/8"),
    ipaddress.IPv4Network("169.254.0.0/16"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("224.0.0.0/4"),
    ipaddress.IPv4Network("240.0.0.0/4"),
    ipaddress.IPv6Network("::1/128"),
    ipaddress.IPv6Network("fc00::/7"),
    ipaddress.IPv6Network("fe80::/10"),
]


class SSRFError(ValueError):
    """Raised when a URL fails SSRF validation."""
    pass


@dataclass(frozen=True)
class NetworkPolicy:
    allowed_domains: set[str]
    allowed_schemes: set[str] = field(default_factory=lambda: {"https"})
    allowed_ports: set[int] = field(default_factory=lambda: {443})
    block_private_ips: bool = True
    max_redirects: int = 3
    max_response_bytes: int = 1_000_000
    timeout_s: float = 10.0


def canonicalize_host(host: str) -> str:
    """IDNA normalize, lowercase, strip trailing dot."""
    h = host.lower().rstrip(".")
    try:
        h = h.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        pass
    return h


def domain_allowed(host: str, allowed_domains: set[str]) -> bool:
    """Check host against allowed domains (exact or safe subdomain suffix)."""
    host = canonicalize_host(host)
    if host in allowed_domains:
        return True
    for domain in allowed_domains:
        if host.endswith("." + domain):
            return True
    return False


def resolve_all(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve all A/AAAA records for a hostname. Raises on failure."""
    try:
        addr = ipaddress.ip_address(host)
        return [addr]
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as e:
        raise SSRFError(f"DNS resolution failed for '{host}': {e}") from e

    results: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for info in infos:
        try:
            results.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue

    if not results:
        raise SSRFError(f"No IP addresses resolved for '{host}'")
    return results


def is_forbidden_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if IP is private, loopback, link-local, multicast, or reserved."""
    for net in PRIVATE_NETWORKS:
        if ip in net:
            return True
    return False


def validate_url_strict(url: str, policy: NetworkPolicy) -> None:
    """Validate a URL against strict SSRF policy. Raises SSRFError on failure."""
    parsed = urlparse(url)

    if parsed.scheme not in policy.allowed_schemes:
        raise SSRFError(f"Scheme '{parsed.scheme}' not allowed")

    if parsed.username or parsed.password:
        raise SSRFError("URL with userinfo (user:pass@host) is forbidden")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFError("URL hostname is required")

    hostname = canonicalize_host(hostname)

    if hostname in BLOCKED_HOSTS:
        raise SSRFError(f"Hostname '{hostname}' is blocked")

    effective_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if policy.allowed_ports and effective_port not in policy.allowed_ports:
        raise SSRFError(f"Port {effective_port} not allowed")

    if not domain_allowed(hostname, policy.allowed_domains):
        raise SSRFError(f"Domain '{hostname}' not in allowed_domains")

    if policy.block_private_ips:
        ips = resolve_all(hostname)
        for ip in ips:
            if is_forbidden_ip(ip):
                raise SSRFError(f"IP {ip} is private/reserved/multicast")


def fetch_url_hardened(url: str, policy: NetworkPolicy) -> str:
    """Fetch a URL with SSRF protection and redirect validation.

    Uses httpx with follow_redirects=False — each redirect is independently
    validated through validate_url_strict before being followed.
    Stream-reads response body with max_response_bytes enforcement.
    """
    import re as _re
    import httpx
    from urllib.parse import urljoin

    current = url
    with httpx.Client(follow_redirects=False, timeout=policy.timeout_s) as client:
        for _ in range(policy.max_redirects + 1):
            validate_url_strict(current, policy)

            with client.stream("GET", current, headers={"User-Agent": "SeekFlow/1.0"}) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise SSRFError("Redirect without Location header")
                    current = urljoin(current, location)
                    continue

                resp.raise_for_status()

                chunks: list[bytes] = []
                total = 0
                for chunk in resp.iter_bytes():
                    total += len(chunk)
                    if total > policy.max_response_bytes:
                        raise SSRFError(
                            f"Response exceeds max_response_bytes ({policy.max_response_bytes})"
                        )
                    chunks.append(chunk)

                raw = b"".join(chunks)
                text = raw.decode("utf-8", errors="replace")
                text = _re.sub(r"<script[^>]*>.*?</script>", "", text, flags=_re.DOTALL)
                text = _re.sub(r"<style[^>]*>.*?</style>", "", text, flags=_re.DOTALL)
                text = _re.sub(r"<[^>]+>", " ", text)
                text = _re.sub(r"\s+", " ", text).strip()
                return text

    raise SSRFError(f"Too many redirects ({policy.max_redirects})")
