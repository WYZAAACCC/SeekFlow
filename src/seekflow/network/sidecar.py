"""EgressSidecar — Lv3 network boundary for external tool containers.

The sidecar runs as a local HTTP proxy. External tools with --network none
can only reach the outside world through this sidecar, which enforces
per-tool EgressPolicy constraints.
"""
from __future__ import annotations

import socket
import threading
import time as _time
from dataclasses import dataclass, field
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any
from urllib.parse import urlparse

from seekflow.network.egress import EgressPolicy, EgressGateway, EgressAuditEntry


@dataclass
class EgressSidecarHandle:
    """Handle to a running egress sidecar."""
    proxy_url: str
    port: int
    audit_entries: list[EgressAuditEntry] = field(default_factory=list)
    _server: HTTPServer | None = None
    _thread: threading.Thread | None = None


class EgressSidecar:
    """Lv3 egress sidecar — local HTTP proxy with policy enforcement.

    Usage:
        sidecar = EgressSidecar()
        handle = sidecar.start(policy, "my-tool", "run-1")
        # Tool container uses HTTP_PROXY=http://host.docker.internal:{port}
        sidecar.stop(handle)
    """

    def start(
        self,
        policy: EgressPolicy,
        tool_name: str = "",
        run_id: str = "",
    ) -> EgressSidecarHandle:
        """Start the sidecar on a random available port."""
        gateway = EgressGateway(policy, tool_name=tool_name, run_id=run_id)

        # Find available port
        port = _find_free_port()

        server = HTTPServer(("127.0.0.1", port), _make_handler(gateway))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        return EgressSidecarHandle(
            proxy_url=f"http://host.docker.internal:{port}",
            port=port,
            audit_entries=gateway.audit_entries,
            _server=server,
            _thread=thread,
        )

    def stop(self, handle: EgressSidecarHandle) -> None:
        """Stop the sidecar and collect audit entries."""
        if handle._server:
            handle._server.shutdown()
        if handle._thread:
            handle._thread.join(timeout=2)


def _find_free_port() -> int:
    """Find a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_handler(gateway: EgressGateway):
    """Create a request handler class bound to a specific gateway."""
    class _ProxyHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_PUT(self):
            self._handle("PUT")

        def _handle(self, method: str):
            url = self.path
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len) if content_len > 0 else None

            ok, reason = gateway.check_request(url, method=method, request_body=body)
            if not ok:
                self.send_error(403, reason or "Blocked by egress policy")
                return

            # In full implementation: forward request to actual target
            # For now, return 501 (Not Implemented) for actual forwarding
            self.send_response(501)
            self.end_headers()
            self.wfile.write(b"Egress forwarding not yet implemented")

        def log_message(self, format, *args):
            pass  # suppress HTTP server logs

    return _ProxyHandler
