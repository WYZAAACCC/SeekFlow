"""Test built-in fetch_url tool factory."""
import pytest
from seekflow.tools.builtins.network import make_fetch_url
from seekflow.security.http import NetworkPolicy, validate_url_strict, SSRFError


def test_make_fetch_url_blocks_localhost():
    td = make_fetch_url(allowed_domains={"example.com"})
    result = td.func("http://localhost:8080/test")
    assert "blocked" in result.lower()


def test_make_fetch_url_blocks_private_ip():
    td = make_fetch_url(allowed_domains={"example.com"})
    result = td.func("http://127.0.0.1/test")
    assert "blocked" in result.lower()


def test_make_fetch_url_blocks_unknown_domain():
    td = make_fetch_url(allowed_domains={"example.com"})
    result = td.func("https://evil.com/test")
    assert "blocked" in result.lower()


def test_make_fetch_url_has_url_params():
    td = make_fetch_url(allowed_domains={"example.com"})
    assert td.policy.url_params == frozenset({"url"})


def test_make_fetch_url_has_correct_capabilities():
    td = make_fetch_url(allowed_domains={"example.com"})
    assert "network.public_http" in td.policy.capabilities
    assert td.policy.risk == "network"


def test_validate_url_strict_respects_https_only():
    policy = NetworkPolicy(
        allowed_domains={"example.com"},
        allowed_schemes={"https"},
        allowed_ports={443},
    )
    with pytest.raises(SSRFError):
        validate_url_strict("http://example.com/test", policy)
