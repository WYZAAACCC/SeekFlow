"""EgressGateway — Lv3 network boundary for external tool execution.

Replaces library-level SSRF (validate_url_strict) with a network boundary:
external tools run with --network none and can only reach the outside
world through a local egress sidecar that enforces per-tool policies.
"""
from __future__ import annotations

import hashlib
import ipaddress
import time as _time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field


class EgressPolicy(BaseModel):
    """Network egress policy for a single external tool.

    Declares what domains, schemes, ports, and methods the tool may use.
    Enforced at the egress sidecar, not in the tool process.
    """

    allowed_domains: set[str] = Field(default_factory=set)
    allowed_schemes: set[str] = Field(default_factory=lambda: {"https"})
    allowed_ports: set[int] = Field(default_factory=lambda: {443})
    allowed_methods: set[str] = Field(default_factory=lambda: {"GET"})
    max_request_bytes: int = 64_000
    max_response_bytes: int = 1_000_000
    max_redirects: int = 3
    block_private_ips: bool = True
    require_tls: bool = True


@dataclass
class EgressAuditEntry:
    """Audit record for a single egress request."""
    timestamp: float = 0.0
    tool_name: str = ""
    run_id: str = ""
    method: str = "GET"
    url: str = ""
    domain: str = ""
    resolved_ip: str = ""
    status_code: int = 0
    request_hash: str = ""
    response_hash: str = ""
    bytes_sent: int = 0
    bytes_received: int = 0
    allowed: bool = True
    block_reason: str | None = None


class EgressGateway:
    """Lv3 egress boundary for external tool network access.

    In Phase E, this is a validation/mock layer. Full sidecar implementation
    (Phase E final) runs as a separate process that the external tool container
    proxies through. For now, it validates egress requests against the policy
    and provides the audit trail.
    """

    def __init__(self, policy: EgressPolicy, tool_name: str = "", run_id: str = ""):
        self._policy = policy
        self._tool_name = tool_name
        self._run_id = run_id
        self.audit_entries: list[EgressAuditEntry] = []

    def check_request(
        self,
        url: str,
        method: str = "GET",
        request_body: bytes | None = None,
    ) -> tuple[bool, str | None]:
        """Check whether a request is allowed by the egress policy.

        Returns (allowed, block_reason).
        """
        policy = self._policy
        start = _time.monotonic()

        # Parse URL
        try:
            parsed = urlparse(url)
        except Exception as e:
            return False, f"Invalid URL: {e}"

        # Scheme check
        if parsed.scheme not in policy.allowed_schemes:
            return False, f"Scheme '{parsed.scheme}' not in allowed_schemes"

        # TLS check
        if policy.require_tls and parsed.scheme != "https":
            return False, "TLS required"

        # Method check
        if method.upper() not in policy.allowed_methods:
            return False, f"Method '{method}' not in allowed_methods"

        # Port check
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if port not in policy.allowed_ports:
            return False, f"Port {port} not in allowed_ports"

        # Domain check
        hostname = parsed.hostname or ""
        if not hostname:
            return False, "No hostname in URL"

        if not _domain_allowed(hostname, policy.allowed_domains):
            return False, f"Domain '{hostname}' not in allowed_domains"

        # Request body size check
        if request_body and len(request_body) > policy.max_request_bytes:
            return False, f"Request body ({len(request_body)} bytes) exceeds max ({policy.max_request_bytes})"

        # Resolve DNS and check private IPs
        try:
            resolved = _resolve_host(hostname)
        except Exception:
            resolved = hostname  # DNS failed — block at sidecar level

        if policy.block_private_ips and _is_private_ip(resolved):
            return False, f"Resolved IP '{resolved}' is private/reserved"

        # Record audit entry
        request_hash = _hash_bytes((url + method).encode())[:16]
        self.audit_entries.append(EgressAuditEntry(
            timestamp=start,
            tool_name=self._tool_name,
            run_id=self._run_id,
            method=method,
            url=url,
            domain=hostname,
            resolved_ip=str(resolved),
            request_hash=request_hash,
            allowed=True,
        ))

        return True, None

    def check_response(
        self,
        status_code: int,
        response_body: bytes,
        redirect_count: int = 0,
    ) -> tuple[bool, str | None]:
        """Check whether a response passes egress policy constraints.

        Returns (allowed, block_reason).
        """
        policy = self._policy

        if redirect_count > policy.max_redirects:
            return False, f"Redirect count ({redirect_count}) exceeds max ({policy.max_redirects})"

        if len(response_body) > policy.max_response_bytes:
            return False, f"Response body ({len(response_body)} bytes) exceeds max ({policy.max_response_bytes})"

        if self.audit_entries:
            self.audit_entries[-1].status_code = status_code
            self.audit_entries[-1].bytes_received = len(response_body)

        return True, None


# ── Helpers ─────────────────────────────────────────────────────

BLOCKED_HOSTS: frozenset[str] = frozenset({
    "localhost", "metadata.google.internal",
})

PRIVATE_NETWORKS: list[Any] = []


def _init_private_networks():
    global PRIVATE_NETWORKS
    if PRIVATE_NETWORKS:
        return
    PRIVATE_NETWORKS = [
        ipaddress.IPv4Network("0.0.0.0/8"),
        ipaddress.IPv4Network("10.0.0.0/8"),
        ipaddress.IPv4Network("100.64.0.0/10"),
        ipaddress.IPv4Network("127.0.0.0/8"),
        ipaddress.IPv4Network("169.254.0.0/16"),
        ipaddress.IPv4Network("172.16.0.0/12"),
        ipaddress.IPv4Network("192.0.0.0/24"),
        ipaddress.IPv4Network("192.168.0.0/16"),
        ipaddress.IPv4Network("198.18.0.0/15"),
        ipaddress.IPv4Network("224.0.0.0/4"),
        ipaddress.IPv4Network("240.0.0.0/4"),
        ipaddress.IPv6Network("::1/128"),
        ipaddress.IPv6Network("::/128"),
        ipaddress.IPv6Network("2001:db8::/32"),
        ipaddress.IPv6Network("fc00::/7"),
        ipaddress.IPv6Network("fe80::/10"),
    ]


def _domain_allowed(hostname: str, allowed_domains: set[str]) -> bool:
    """Check if hostname matches an allowed domain (exact or subdomain)."""
    if not allowed_domains:
        return False
    hostname = hostname.lower()
    for domain in allowed_domains:
        domain = domain.lower()
        if hostname == domain:
            return True
        if hostname.endswith("." + domain):
            return True
    return False


def _resolve_host(hostname: str) -> str:
    """Resolve hostname to IP. Returns hostname string on failure."""
    try:
        import socket
        info = socket.getaddrinfo(hostname, None)
        if info:
            return info[0][4][0]
    except Exception:
        pass
    return hostname


def _is_private_ip(ip_str: str) -> bool:
    """Check if IP address is in a private/reserved range."""
    _init_private_networks()
    try:
        addr = ipaddress.ip_address(ip_str)
        for network in PRIVATE_NETWORKS:
            if addr in network:
                return True
    except ValueError:
        pass
    return False


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
