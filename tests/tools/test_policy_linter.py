"""Phase B: PolicyLinter — security lint rules enforcement."""
from pathlib import Path

import pytest

from seekflow.types import ToolPolicy
from seekflow.tools.policy_linter import (
    lint_policy, has_errors, LintIssue, ALL_RULES,
    _rule_no_local_runner_for_external,
    _rule_network_requires_domains,
    _rule_filesystem_requires_workspace,
    _rule_write_requires_approval,
    _rule_code_exec_requires_container,
    _rule_no_trusted_output_for_external,
    _rule_no_wildcard_domains,
    _rule_no_public_suffix_only_domains,
    _rule_path_params_for_filesystem,
)


class TestLintRules:
    """Individual lint rule tests."""

    def test_L001_no_local_runner_for_registry(self):
        issues = _rule_no_local_runner_for_external(
            ToolPolicy(runner="in_process"), "registry")
        assert len(issues) == 1
        assert issues[0].code == "L001"

    def test_L001_no_local_runner_for_mcp(self):
        issues = _rule_no_local_runner_for_external(
            ToolPolicy(runner="process"), "mcp")
        assert len(issues) == 1
        assert issues[0].code == "L001"

    def test_L001_ok_for_local_source(self):
        issues = _rule_no_local_runner_for_external(
            ToolPolicy(runner="in_process"), "local")
        assert len(issues) == 0

    def test_L001_ok_for_container_runner(self):
        issues = _rule_no_local_runner_for_external(
            ToolPolicy(runner="container"), "registry")
        assert len(issues) == 0

    # ── L002/L003: Network ──────────────────────────────────────

    def test_L002_network_requires_domains(self):
        policy = ToolPolicy(risk="network")
        issues = _rule_network_requires_domains(policy, "local")
        assert any(i.code == "L002" for i in issues)

    def test_L002_network_with_domains_passes(self):
        policy = ToolPolicy(risk="network", allowed_domains={"example.com"})
        issues = _rule_network_requires_domains(policy, "local")
        assert not any(i.code == "L002" for i in issues)

    def test_L003_public_http_requires_url_params(self):
        policy = ToolPolicy(capabilities={"network.public_http"})
        issues = _rule_network_requires_domains(policy, "local")
        assert any(i.code == "L003" for i in issues)

    def test_L003_public_http_with_url_params_passes(self):
        policy = ToolPolicy(
            capabilities={"network.public_http"},
            url_params=frozenset({"url"}),
        )
        issues = _rule_network_requires_domains(policy, "local")
        assert not any(i.code == "L003" for i in issues)

    # ── L004: Filesystem workspace ───────────────────────────────

    def test_L004_filesystem_requires_workspace(self):
        policy = ToolPolicy(capabilities={"filesystem.read"})
        issues = _rule_filesystem_requires_workspace(policy, "local")
        assert any(i.code == "L004" for i in issues)

    def test_L004_filesystem_with_workspace_passes(self):
        policy = ToolPolicy(
            capabilities={"filesystem.read"},
            workspace_root=Path("/tmp"),
        )
        issues = _rule_filesystem_requires_workspace(policy, "local")
        assert not any(i.code == "L004" for i in issues)

    # ── L005: Write requires approval ────────────────────────────

    def test_L005_write_without_approval(self):
        policy = ToolPolicy(capabilities={"filesystem.write"})
        issues = _rule_write_requires_approval(policy, "local")
        assert any(i.code == "L005" for i in issues)

    def test_L005_write_with_approval_passes(self):
        policy = ToolPolicy(
            capabilities={"filesystem.write"},
            requires_approval=True,
        )
        issues = _rule_write_requires_approval(policy, "local")
        assert not any(i.code == "L005" for i in issues)

    def test_L005_write_with_trusted_codegen_passes(self):
        policy = ToolPolicy(
            capabilities={"filesystem.write"},
            trusted=True, container_codegen_trusted=True,
        )
        issues = _rule_write_requires_approval(policy, "local")
        assert not any(i.code == "L005" for i in issues)

    # ── L006: code_exec container ────────────────────────────────

    def test_L006_code_exec_in_process(self):
        policy = ToolPolicy(risk="code_exec", capabilities={"code.exec"},
                            runner="in_process")
        issues = _rule_code_exec_requires_container(policy, "local")
        assert any(i.code == "L006" for i in issues)

    def test_L006_destructive_in_process(self):
        policy = ToolPolicy(risk="destructive", runner="process")
        issues = _rule_code_exec_requires_container(policy, "local")
        assert any(i.code == "L006" for i in issues)

    def test_L006_code_exec_container_passes(self):
        policy = ToolPolicy(risk="code_exec", capabilities={"code.exec"},
                            runner="container")
        issues = _rule_code_exec_requires_container(policy, "local")
        assert not any(i.code == "L006" for i in issues)

    # ── L007: trusted_output for external ────────────────────────

    def test_L007_trusted_output_for_registry(self):
        policy = ToolPolicy(trusted=True, trusted_output=True)
        issues = _rule_no_trusted_output_for_external(policy, "registry")
        assert any(i.code == "L007" for i in issues)

    def test_L007_trusted_output_for_local_passes(self):
        policy = ToolPolicy(trusted_output=True, trusted=True)
        issues = _rule_no_trusted_output_for_external(policy, "local")
        assert len(issues) == 0

    # ── L009: Wildcard domains ───────────────────────────────────

    def test_L009_wildcard_domain(self):
        policy = ToolPolicy(allowed_domains={"*"})
        issues = _rule_no_wildcard_domains(policy, "local")
        assert any(i.code == "L009" for i in issues)

    def test_L009_no_wildcard_passes(self):
        policy = ToolPolicy(allowed_domains={"example.com"})
        issues = _rule_no_wildcard_domains(policy, "local")
        assert not any(i.code == "L009" for i in issues)

    # ── L010: Public suffix domains ──────────────────────────────

    def test_L010_non_fqdn(self):
        policy = ToolPolicy(allowed_domains={"com"})
        issues = _rule_no_public_suffix_only_domains(policy, "local")
        assert any(i.code == "L010" for i in issues)

    def test_L010_fqdn_passes(self):
        policy = ToolPolicy(allowed_domains={"api.example.com"})
        issues = _rule_no_public_suffix_only_domains(policy, "local")
        assert not any(i.code == "L010" for i in issues)

    # ── L011: Path params for filesystem ─────────────────────────

    def test_L011_filesystem_without_path_params_warns(self):
        policy = ToolPolicy(capabilities={"filesystem.read"})
        issues = _rule_path_params_for_filesystem(policy, "local")
        assert any(i.code == "L011" for i in issues)
        assert issues[0].severity == "warning"

    def test_L011_filesystem_with_path_params_passes(self):
        policy = ToolPolicy(
            capabilities={"filesystem.read"},
            path_params=frozenset({"path"}),
        )
        issues = _rule_path_params_for_filesystem(policy, "local")
        assert not any(i.code == "L011" for i in issues)


class TestLintPipeline:
    """Full lint pipeline tests."""

    def test_all_rules_registered(self):
        assert len(ALL_RULES) >= 10

    def test_has_errors_detects_error(self):
        issues = [LintIssue(severity="error", code="L001", message="test")]
        assert has_errors(issues) is True

    def test_has_errors_ignores_warning(self):
        issues = [LintIssue(severity="warning", code="L008", message="test")]
        assert has_errors(issues) is False

    def test_custom_rule_set(self):
        """Only specified rules are run."""
        def _custom_rule(policy, source):
            return [LintIssue(severity="error", code="X001", message="custom")]

        issues = lint_policy(
            ToolPolicy(risk="read"),
            source="local",
            rules=[_custom_rule],
        )
        assert len(issues) == 1
        assert issues[0].code == "X001"

    def test_broken_rule_is_caught(self):
        """A rule that raises an exception produces L999."""
        def _broken_rule(policy, source):
            raise RuntimeError("boom")

        issues = lint_policy(
            ToolPolicy(risk="read"),
            source="local",
            rules=[_broken_rule],
        )
        assert any(i.code == "L999" for i in issues)
