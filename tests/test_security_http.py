"""Test HTTP SSRF protection."""
import pytest
from seekflow.security.http import (
    NetworkPolicy, validate_url_strict, SSRFError,
    resolve_all, is_forbidden_ip, domain_allowed, canonicalize_host,
)


def test_blocks_localhost():
    policy = NetworkPolicy(allowed_domains={"example.com"}, allowed_ports={80, 443})
    with pytest.raises(SSRFError):
        validate_url_strict("http://localhost/login", policy)


def test_blocks_127_0_0_1():
    policy = NetworkPolicy(allowed_domains={"example.com"}, allowed_ports={80, 443})
    with pytest.raises(SSRFError):
        validate_url_strict("http://127.0.0.1/admin", policy)


def test_blocks_169_254_169_254():
    policy = NetworkPolicy(allowed_domains={"example.com"}, allowed_ports={80, 443})
    with pytest.raises(SSRFError):
        validate_url_strict("http://169.254.169.254/latest/meta-data", policy)


def test_blocks_private_ipv4():
    policy = NetworkPolicy(allowed_domains={"example.com"}, allowed_ports={80, 443})
    with pytest.raises(SSRFError):
        validate_url_strict("http://10.0.0.1/api", policy)


def test_blocks_ipv6_loopback():
    policy = NetworkPolicy(allowed_domains={"example.com"}, allowed_ports={80, 443})
    with pytest.raises(SSRFError):
        validate_url_strict("http://[::1]/api", policy)


def test_blocks_userinfo_trick():
    policy = NetworkPolicy(allowed_domains={"example.com"}, allowed_ports={80, 443})
    with pytest.raises(SSRFError):
        validate_url_strict("http://user:pass@example.com", policy)


def test_domain_not_in_allowlist_blocked():
    policy = NetworkPolicy(allowed_domains={"example.com"}, allowed_ports={80, 443})
    with pytest.raises(SSRFError):
        validate_url_strict("http://evil.com", policy)


def test_domain_allowed_exact():
    assert domain_allowed("example.com", {"example.com"}) is True


def test_domain_allowed_subdomain():
    assert domain_allowed("sub.example.com", {"example.com"}) is True


def test_domain_allowed_denies_different():
    assert domain_allowed("evil.com", {"example.com"}) is False


def test_https_default_allowed():
    policy = NetworkPolicy(allowed_domains={"deepseek.com"})
    # Should not raise — defaults to HTTPS port 443
    validate_url_strict("https://deepseek.com/status", policy)


def test_resolve_all_handles_ip_directly():
    ips = resolve_all("1.1.1.1")
    assert len(ips) >= 1


def test_is_forbidden_ip_private():
    import ipaddress
    assert is_forbidden_ip(ipaddress.IPv4Address("10.0.0.1")) is True
    assert is_forbidden_ip(ipaddress.IPv4Address("127.0.0.1")) is True
    assert is_forbidden_ip(ipaddress.IPv4Address("192.168.1.1")) is True


def test_is_forbidden_ip_public():
    import ipaddress
    assert is_forbidden_ip(ipaddress.IPv4Address("8.8.8.8")) is False


def test_canonicalize_host_lowercase():
    assert canonicalize_host("EXAMPLE.COM") == "example.com"


def test_blocks_private_192_168():
    policy = NetworkPolicy(allowed_domains={"example.com"}, allowed_ports={80, 443})
    with pytest.raises(SSRFError):
        validate_url_strict("http://192.168.1.1/api", policy)
