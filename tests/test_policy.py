"""Tests for Policy Engine — tool call authorization."""
from __future__ import annotations

from pathlib import Path

import pytest

from seekflow.types import ToolDefinition, ToolPolicy


class TestPolicyEngine:
    """PolicyEngine.authorize() — centralized authorization gate."""

    def test_read_tool_allowed_with_default_policy(self):
        from seekflow.policy import PolicyEngine

        engine = PolicyEngine()
        td = ToolDefinition(
            name="read_file", description="Read a file",
            parameters={"type": "object", "properties": {}},
            policy=ToolPolicy(capabilities={"filesystem.read"}, risk="read"),
        )
        decision = engine.authorize(td, {"path": "data.txt"}, run_context={})
        assert decision.allowed is True

    def test_code_exec_without_sandbox_denied(self):
        from seekflow.policy import PolicyEngine

        engine = PolicyEngine()
        td = ToolDefinition(
            name="run_python", description="Execute Python code",
            parameters={"type": "object", "properties": {}},
            policy=ToolPolicy(capabilities={"code.exec"}, risk="code_exec"),
        )
        decision = engine.authorize(td, {"code": "print(1)"}, run_context={})
        assert decision.allowed is False
        assert "sandbox" in decision.reason.lower()

    def test_write_tool_without_workspace_denied(self):
        from seekflow.policy import PolicyEngine

        engine = PolicyEngine()
        td = ToolDefinition(
            name="save_file", description="Save a file",
            parameters={"type": "object", "properties": {}},
            policy=ToolPolicy(capabilities={"filesystem.write"}, risk="write"),
        )
        decision = engine.authorize(td, {"filename": "out.txt"}, run_context={})
        assert decision.allowed is False

    def test_destructive_requires_approval(self):
        from seekflow.policy import PolicyEngine

        engine = PolicyEngine()
        td = ToolDefinition(
            name="delete_all", description="Delete everything",
            parameters={"type": "object", "properties": {}},
            policy=ToolPolicy(capabilities={"filesystem.write"}, risk="destructive"),
        )
        decision = engine.authorize(td, {}, run_context={})
        assert decision.requires_approval is True

    def test_tool_without_policy_uses_restrictive_default(self):
        from seekflow.policy import PolicyEngine

        engine = PolicyEngine()
        td = ToolDefinition(
            name="unknown_tool", description="No policy set",
            parameters={"type": "object", "properties": {}},
            # policy=None → restrictive default
        )
        decision = engine.authorize(td, {}, run_context={})
        # No-policy tools are denied by default (must have explicit ToolPolicy)
        assert decision.allowed is False
        assert decision.requires_approval is True

    def test_network_tool_with_allowed_domain_passes(self):
        from seekflow.policy import PolicyEngine

        engine = PolicyEngine()
        td = ToolDefinition(
            name="fetch_url", description="Fetch a URL",
            parameters={"type": "object", "properties": {}},
            policy=ToolPolicy(
                capabilities={"network.public_http"}, risk="network",
                allowed_domains={"docs.deepseek.com"},
            ),
        )
        decision = engine.authorize(
            td, {"url": "https://docs.deepseek.com/api"}, run_context={},
        )
        assert decision.allowed is True

    def test_network_tool_with_blocked_domain_denied(self):
        from seekflow.policy import PolicyEngine

        engine = PolicyEngine()
        td = ToolDefinition(
            name="fetch_url", description="Fetch a URL",
            parameters={"type": "object", "properties": {}},
            policy=ToolPolicy(
                capabilities={"network.public_http"}, risk="network",
                allowed_domains={"docs.deepseek.com"},
            ),
        )
        decision = engine.authorize(
            td, {"url": "https://evil.com/hack"}, run_context={},
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
            ),
        )
        decision = engine.authorize(
            td, {"path": "/workspace/data.txt"}, run_context={},
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
            ),
        )
        decision = engine.authorize(
            td, {"path": "/etc/passwd"}, run_context={},
        )
        assert decision.allowed is False
