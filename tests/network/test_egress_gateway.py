"""Phase E: EgressGateway — network boundary enforcement tests."""
import pytest

from seekflow.network.egress import (
    EgressPolicy, EgressGateway, EgressAuditEntry,
    _domain_allowed, _is_private_ip, _resolve_host,
)


class TestEgressPolicy:
    """EgressPolicy model defaults."""

    def test_default_policy(self):
        policy = EgressPolicy()
        assert policy.allowed_schemes == {"https"}
        assert policy.allowed_ports == {443}
        assert policy.allowed_methods == {"GET"}
        assert policy.require_tls is True
        assert policy.block_private_ips is True
        assert policy.max_redirects == 3

    def test_custom_policy(self):
        policy = EgressPolicy(
            allowed_domains={"api.example.com"},
            allowed_methods={"GET", "POST"},
            allowed_ports={443, 8443},
        )
        assert "api.example.com" in policy.allowed_domains
        assert "POST" in policy.allowed_methods


class TestEgressGateway:
    """EgressGateway request checking."""

    def test_allowed_domain_passes(self):
        policy = EgressPolicy(allowed_domains={"api.example.com"})
        gw = EgressGateway(policy)
        ok, reason = gw.check_request("https://api.example.com/data")
        assert ok
        assert reason is None

    def test_subdomain_passes(self):
        policy = EgressPolicy(allowed_domains={"example.com"})
        gw = EgressGateway(policy)
        ok, _ = gw.check_request("https://api.example.com/data")
        assert ok

    def test_disallowed_domain_blocked(self):
        policy = EgressPolicy(allowed_domains={"example.com"})
        gw = EgressGateway(policy)
        ok, reason = gw.check_request("https://evil.com/data")
        assert not ok
        assert "evil.com" in reason

    def test_http_blocked_when_tls_required(self):
        policy = EgressPolicy(require_tls=True, allowed_schemes={"http", "https"})
        gw = EgressGateway(policy)
        ok, reason = gw.check_request("http://api.example.com/data")
        assert not ok
        assert "TLS" in reason

    def test_disallowed_method_blocked(self):
        policy = EgressPolicy(allowed_domains={"api.example.com"},
                              allowed_methods={"GET"})
        gw = EgressGateway(policy)
        ok, reason = gw.check_request("https://api.example.com/data", method="POST")
        assert not ok
        assert "POST" in reason

    def test_disallowed_port_blocked(self):
        policy = EgressPolicy(allowed_domains={"api.example.com"},
                              allowed_ports={443})
        gw = EgressGateway(policy)
        ok, reason = gw.check_request("https://api.example.com:8080/data")
        assert not ok
        assert "8080" in reason

    def test_oversized_request_blocked(self):
        policy = EgressPolicy(allowed_domains={"api.example.com"},
                              max_request_bytes=100)
        gw = EgressGateway(policy)
        ok, reason = gw.check_request(
            "https://api.example.com/data",
            request_body=b"x" * 200,
        )
        assert not ok
        assert "exceeds max" in reason

    def test_private_ip_blocked(self):
        policy = EgressPolicy(allowed_domains={"localhost"},
                              block_private_ips=True)
        gw = EgressGateway(policy)
        ok, reason = gw.check_request("https://localhost/data")
        assert not ok

    def test_audit_entries_recorded(self):
        policy = EgressPolicy(allowed_domains={"api.example.com"})
        gw = EgressGateway(policy, tool_name="test-tool", run_id="run-1")
        gw.check_request("https://api.example.com/data")
        assert len(gw.audit_entries) == 1
        assert gw.audit_entries[0].tool_name == "test-tool"
        assert gw.audit_entries[0].allowed is True

    def test_response_check_redirect_limit(self):
        policy = EgressPolicy(allowed_domains={"api.example.com"})
        gw = EgressGateway(policy)
        ok, reason = gw.check_response(200, b"ok", redirect_count=5)
        assert not ok
        assert "Redirect" in reason

    def test_response_check_size_limit(self):
        policy = EgressPolicy(max_response_bytes=100)
        gw = EgressGateway(policy)
        ok, reason = gw.check_response(200, b"x" * 200)
        assert not ok
        assert "exceeds max" in reason


class TestDomainHelper:
    """Domain matching logic."""

    def test_exact_match(self):
        assert _domain_allowed("example.com", {"example.com"})

    def test_subdomain_match(self):
        assert _domain_allowed("api.example.com", {"example.com"})

    def test_no_match(self):
        assert not _domain_allowed("evil.com", {"example.com"})

    def test_case_insensitive(self):
        assert _domain_allowed("API.Example.COM", {"example.com"})


class TestIPHelper:
    """IP classification."""

    def test_private_ip_detected(self):
        assert _is_private_ip("10.0.0.1")
        assert _is_private_ip("192.168.1.1")
        assert _is_private_ip("127.0.0.1")
        assert _is_private_ip("172.16.0.1")

    def test_public_ip_passes(self):
        assert not _is_private_ip("8.8.8.8")
        assert not _is_private_ip("1.1.1.1")

    def test_ipv6_loopback(self):
        assert _is_private_ip("::1")

    def test_unresolvable_not_private(self):
        # If we can't parse it as IP, it's not private
        assert not _is_private_ip("not-an-ip")
