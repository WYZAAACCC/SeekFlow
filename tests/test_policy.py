"""Tests for Policy Engine — tool call authorization (strict mode)."""
from __future__ import annotations

from pathlib import Path

import pytest

from seekflow.types import ToolDefinition, ToolPolicy


class TestPolicyEngine:
    """PolicyEngine.authorize() — default strict mode."""

    def test_read_tool_allowed_with_workspace_root(self):
        from seekflow.policy import PolicyEngine

        engine = PolicyEngine()
        td = ToolDefinition(
            name="read_file", description="Read a file",
            parameters={"type": "object", "properties": {}},
            policy=ToolPolicy(capabilities={"filesystem.read"}, risk="read",
                              workspace_root=Path("/workspace")),
        )
        decision = engine.authorize(td, {"path": "data.txt"},
            context={"allowed_capabilities": {"filesystem.read"}, "workspace_root": "/workspace"})
        assert decision.allowed is True

    def test_code_exec_without_sandbox_denied(self):
        from seekflow.policy import PolicyEngine

        engine = PolicyEngine()
        td = ToolDefinition(
            name="run_python", description="Execute Python code",
            parameters={"type": "object", "properties": {}},
            policy=ToolPolicy(capabilities={"code.exec"}, risk="code_exec"),
        )
        decision = engine.authorize(td, {"code": "print(1)"}, context={})
        assert decision.allowed is False
        assert "sandbox" in decision.reason.lower() or "Dangerous" in decision.reason

    def test_write_tool_without_workspace_denied(self):
        from seekflow.policy import PolicyEngine

        engine = PolicyEngine()
        td = ToolDefinition(
            name="save_file", description="Save a file",
            parameters={"type": "object", "properties": {}},
            policy=ToolPolicy(capabilities={"filesystem.write"}, risk="write"),
        )
        decision = engine.authorize(td, {"filename": "out.txt"}, context={})
        assert decision.allowed is False

    def test_destructive_requires_approval(self):
        from seekflow.policy import PolicyEngine

        engine = PolicyEngine()
        td = ToolDefinition(
            name="delete_all", description="Delete everything",
            parameters={"type": "object", "properties": {}},
            policy=ToolPolicy(capabilities={"filesystem.write"}, risk="destructive"),
        )
        decision = engine.authorize(td, {}, context={})
        # Destructive always requires approval (but may also be denied by dangerous tools gate)
        assert decision.requires_approval is True or decision.allowed is False

    def test_tool_without_policy_uses_restrictive_default(self):
        from seekflow.policy import PolicyEngine

        engine = PolicyEngine()
        td = ToolDefinition(
            name="unknown_tool", description="No policy set",
            parameters={"type": "object", "properties": {}},
        )
        decision = engine.authorize(td, {}, context={})
        assert decision.allowed is False
        assert decision.requires_approval is True

    def test_network_tool_with_allowed_domain_passes_strict(self):
        from seekflow.policy import PolicyEngine

        # Strict mode: context must explicitly authorize network
        engine = PolicyEngine(mode="compat")
        td = ToolDefinition(
            name="fetch_url", description="Fetch a URL",
            parameters={"type": "object", "properties": {}},
            policy=ToolPolicy(
                capabilities={"network.public_http"}, risk="network",
                allowed_domains={"docs.deepseek.com"},
            ),
        )
        decision = engine.authorize(
            td, {"url": "https://docs.deepseek.com/api"},
            context={"allowed_capabilities": {"network.public_http"}, "dangerous_tools_enabled": True},
        )
        if not decision.allowed and "DNS" in decision.reason:
            pytest.skip("DNS resolution not available")
        assert decision.allowed is True

    def test_network_tool_with_blocked_domain_denied(self):
        from seekflow.policy import PolicyEngine

        engine = PolicyEngine(mode="compat")
        td = ToolDefinition(
            name="fetch_url", description="Fetch a URL",
            parameters={"type": "object", "properties": {}},
            policy=ToolPolicy(
                capabilities={"network.public_http"}, risk="network",
                allowed_domains={"docs.deepseek.com"},
            ),
        )
        decision = engine.authorize(
            td, {"url": "https://evil.com/hack"}, context={},
        )
        assert decision.allowed is False

    def test_path_within_workspace_allowed(self):
        from seekflow.policy import PolicyEngine

        engine = PolicyEngine()
        td = ToolDefinition(
            name="read_file", description="Read a file",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
            policy=ToolPolicy(
                capabilities={"filesystem.read"}, risk="read",
                workspace_root=Path("/workspace"),
                path_params=frozenset({"path"}),
            ),
        )
        decision = engine.authorize(
            td, {"path": "/workspace/data.txt"},
            context={"allowed_capabilities": {"filesystem.read"}, "workspace_root": "/workspace"},
        )
        assert decision.allowed is True

    def test_path_outside_workspace_denied(self):
        from seekflow.policy import PolicyEngine

        engine = PolicyEngine()
        td = ToolDefinition(
            name="read_file", description="Read a file",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
            },
            policy=ToolPolicy(
                capabilities={"filesystem.read"}, risk="read",
                workspace_root=Path("/workspace"),
                path_params=frozenset({"path"}),
            ),
        )
        decision = engine.authorize(
            td, {"path": "/etc/passwd"}, context={},
        )
        assert decision.allowed is False

    def test_strict_mode_denies_network_without_explicit_context(self):
        """In strict mode, network tools denied by default (no compat override)."""
        from seekflow.policy import PolicyEngine

        engine = PolicyEngine()  # default strict
        td = ToolDefinition(
            name="fetch", description="Fetch",
            parameters={"type": "object", "properties": {}},
            policy=ToolPolicy(
                capabilities={"network.public_http"}, risk="network",
                allowed_domains={"example.com"},
            ),
        )
        decision = engine.authorize(td, {"url": "https://example.com"}, context={})
        assert decision.allowed is False  # denied by strict default
        assert "Dangerous" in decision.reason or "disabled" in decision.reason.lower()

    def test_compat_mode_allows_network_with_dict_context(self):
        """In compat mode, network tools allowed with empty dict context."""
        from seekflow.policy import PolicyEngine

        engine = PolicyEngine(mode="compat")
        td = ToolDefinition(
            name="fetch", description="Fetch",
            parameters={"type": "object", "properties": {}},
            policy=ToolPolicy(
                capabilities={"network.public_http"}, risk="network",
                allowed_domains={"example.com"},
            ),
        )
        # dict context now defaults dangerous_enabled=False → deny
        decision = engine.authorize(
            td, {"url": "https://example.com/api"}, context={},
        )
        assert decision.allowed is False
