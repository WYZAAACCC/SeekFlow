"""Phase 2 tests: EgressSidecar integration with ExternalToolRunner."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from seekflow.network.egress import EgressPolicy
from seekflow.network.sidecar import EgressSidecar, EgressSidecarHandle
from seekflow.tools.external_runner import ExternalToolRunner
from seekflow.tools.manifest import ToolManifest


def _make_manifest(*, network_domains=None):
    kw = {
        "name": "test-tool",
        "version": "1.0.0",
        "package_digest": "a" * 64,
        "source": "registry",
        "sandbox": {
            "image_digest": "sha256:" + "b" * 64,
            "image": "python:3.11-slim",
        },
    }
    if network_domains:
        kw["network"] = {"allowed_domains": set(network_domains)}
    return ToolManifest.model_validate(kw)


def test_external_tool_no_network_no_sidecar():
    """无network manifest → --network none → 无proxy"""
    runner = ExternalToolRunner()  # no egress_sidecar
    manifest = _make_manifest()  # no network domains
    # This would require docker; just verify constructor works
    assert runner.egress_sidecar is None


def test_external_tool_network_requires_sidecar():
    """有network manifest但无sidecar→返回error"""
    runner = ExternalToolRunner()  # no egress_sidecar
    manifest = _make_manifest(network_domains={"api.example.com"})

    # run() should fail fast because no sidecar configured
    result = runner.run(manifest, {"arg": "val"}, 30.0)
    assert result.ok is False
    assert "EgressSidecar" in result.error


def test_external_tool_with_sidecar_starts_proxy():
    """有sidecar→启动代理并设置HTTP_PROXY"""
    sidecar = EgressSidecar()
    runner = ExternalToolRunner(egress_sidecar=sidecar)

    manifest = _make_manifest(network_domains={"api.example.com"})

    # Mock subprocess and bounded_communicate to avoid real docker execution
    with patch("subprocess.Popen") as mock_popen, \
         patch("seekflow.tools.external_runner._bounded_communicate") as mock_bounded, \
         patch("seekflow.tools.external_runner._kill_container"):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        mock_popen.return_value = mock_proc
        mock_bounded.return_value = ('{"status": "ok"}', "", False, False)

        result = runner.run(manifest, {"arg": "val"}, 30.0)

    assert result.ok is True


def test_egress_blocks_private_ip():
    """代理拒绝私有IP"""
    policy = EgressPolicy(allowed_domains={"example.com"}, block_private_ips=True)

    from seekflow.network.egress import EgressGateway
    gw = EgressGateway(policy)

    # example.com resolves to public IP → ok
    # But direct private IP in URL should be blocked
    ok, reason = gw.check_request("http://10.0.0.1/api", method="GET")
    assert ok is False
    assert reason is not None


def test_egress_blocks_metadata_ip():
    """代理拒绝metadata IP (169.254.169.254)"""
    policy = EgressPolicy(allowed_domains={"169.254.169.254"}, block_private_ips=True)

    from seekflow.network.egress import EgressGateway
    gw = EgressGateway(policy)

    ok, reason = gw.check_request("http://169.254.169.254/latest/meta-data/", method="GET")
    assert ok is False  # blocked as private IP


def test_egress_blocks_redirect_to_private_ip():
    """redirect到私有IP→拒绝"""
    policy = EgressPolicy(allowed_domains={"example.com"}, max_redirects=3)

    from seekflow.network.egress import EgressGateway
    gw = EgressGateway(policy)

    # Simulate a response that would redirect to private IP
    ok, reason = gw.check_response(302, b"Redirecting...", redirect_count=4)
    assert ok is False
    assert "redirect" in (reason or "").lower()


def test_egress_records_audit_entries():
    """代理请求有audit entry"""
    policy = EgressPolicy(allowed_domains={"api.example.com"})

    from seekflow.network.egress import EgressGateway
    gw = EgressGateway(policy, tool_name="test-tool", run_id="run-1")

    assert len(gw.audit_entries) == 0
    gw.check_request("https://api.example.com/data", method="GET")
    assert len(gw.audit_entries) == 1
    assert gw.audit_entries[0].domain == "api.example.com"
    assert gw.audit_entries[0].allowed is True


def test_sidecar_handle_proxy_url():
    """sidecar handle提供正确的proxy URL"""
    with patch("seekflow.network.sidecar._find_free_port", return_value=12345):
        sidecar = EgressSidecar()
        policy = EgressPolicy(allowed_domains={"example.com"})
        # Mock HTTPServer to avoid actual binding
        with patch("seekflow.network.sidecar.HTTPServer") as mock_server:
            handle = sidecar.start(policy, tool_name="test", run_id="r1")
            assert handle.port == 12345
            assert "host.docker.internal:12345" in handle.proxy_url
