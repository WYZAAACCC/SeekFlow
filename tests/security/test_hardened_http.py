"""Tests for hardened HTTP/SSRF module."""
import pytest

from seekflow.security.http import (
    NetworkPolicy, validate_url_strict, SSRFError, domain_allowed,
)


class TestDomainAllowed:
    def test_exact_match(self):
        assert domain_allowed("example.com", {"example.com"}) is True

    def test_subdomain_match(self):
        assert domain_allowed("sub.example.com", {"example.com"}) is True

    def test_prefix_attack_blocked(self):
        assert domain_allowed("evilexample.com", {"example.com"}) is False


class TestValidateUrlStrict:
    def test_https_allowed_skips_no_dns(self):
        """validate_url_strict allows https to allowed domain (DNS may fail in CI)."""
        policy = NetworkPolicy(allowed_domains={"docs.deepseek.com"})
        try:
            validate_url_strict("https://docs.deepseek.com/api", policy)
        except SSRFError as e:
            if "DNS" in str(e):
                pytest.skip("DNS resolution not available in test environment")
            raise

    def test_http_rejected_by_default(self):
        policy = NetworkPolicy(allowed_domains={"example.com"})
        with pytest.raises(SSRFError):
            validate_url_strict("http://example.com/page", policy)

    def test_userinfo_rejected(self):
        policy = NetworkPolicy(allowed_domains={"example.com"})
        with pytest.raises(SSRFError, match="userinfo"):
            validate_url_strict("https://user:pass@example.com/api", policy)

    def test_blocked_hostname(self):
        policy = NetworkPolicy(allowed_domains={"example.com"})
        with pytest.raises(SSRFError):
            validate_url_strict("https://localhost:8000/admin", policy)


class TestNetworkPolicy:
    def test_default_https_only(self):
        policy = NetworkPolicy(allowed_domains={"example.com"})
        assert policy.allowed_schemes == {"https"}
        assert policy.allowed_ports == {443}
        assert policy.block_private_ips is True
