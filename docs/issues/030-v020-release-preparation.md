# v0.2.0 release: CHANGELOG, SECURITY.md, threat model, hardening guide, CI badges

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

HITL

**Category:** enhancement
**State:** ready-for-human

## What to build

Prepare and publish SeekFlow v0.2.0 with all required release artifacts, documentation, and CI infrastructure to support the "production-grade" claim.

### Deliverables

1. **CHANGELOG.md**: document all changes from v0.1.x to v0.2.0:
   - Breaking changes with migration instructions
   - P0 security fixes (10 items)
   - New modules: policy, security, sandbox, budget, state
   - Deprecated: old `with_default_tools()` behavior, `_sanitize_tool_output()`, semantic message injection
   - New public APIs (list all 8+ new functions)

2. **SECURITY.md**: security policy document:
   - Supported versions (v0.2.0+)
   - Reporting process (email or GitHub Security Advisory)
   - Security model overview: capabilities, risk levels, policy engine
   - Known limitations: regex-based secret redaction (best-effort), thread-based tool timeout (not killable)
   - Dependency policy and vulnerability scanning

3. **Threat model**: `docs/threat-model.md`:
   - Assets: API keys, user data, model outputs, tool execution environment
   - Threat actors: malicious model output, prompt injection via external data, SSRF via tools
   - Trust boundaries: model output (untrusted), tool results (untrusted), user input (trusted), system prompt (trusted)
   - Mitigations: Policy Engine, workspace sandbox, SSRF blocking, secret redaction, untrusted content wrapper
   - Attack surface analysis per tool category

4. **Hardening guide**: `docs/hardening-guide.md`:
   - Quickstart: minimum safe configuration
   - Workspace configuration for file tools
   - URL allowlisting for network tools
   - Sandbox setup for code execution (Docker, process limits)
   - MCP server trust configuration
   - Cost budget configuration and recommendations
   - Production checklist (10-item checklist)

5. **CI/CD pipeline** (`.github/workflows/ci.yml`):
   - Python matrix: 3.10, 3.11, 3.12, 3.13
   - Lint: ruff check
   - Type check: mypy --strict (all modules, zero ignore_errors)
   - Test: pytest with coverage >= 80%
   - Security scan: bandit, pip-audit
   - Badges: tests, coverage, mypy, ruff, PyPI version

6. **pyproject.toml updates**:
   - Bump version to 0.2.0
   - Update classifier from "Beta" to "Production/Stable" (or keep Beta if not ready)
   - Fix dependency count in README (9 core deps, not 6)
   - Add `security` extra: `pip install seekflow[security]`

7. **Examples update**: all example code in README and docs updated to use safe API variants.

## Acceptance criteria

- [ ] `CHANGELOG.md` covers all breaking changes with migration steps
- [ ] `SECURITY.md` includes reporting process and known limitations
- [ ] `docs/threat-model.md` covers all trust boundaries and mitigations
- [ ] `docs/hardening-guide.md` includes production checklist
- [ ] CI passes: Python 3.10-3.13, ruff, mypy strict (zero ignore_errors), pytest >= 80% coverage
- [ ] `bandit` scan passes with zero high-severity findings
- [ ] `pip-audit` passes with zero known vulnerabilities
- [ ] README dependency count corrected (9, not 6)
- [ ] README badges updated and linked to CI
- [ ] All example code uses safe API (no bare `with_default_tools()` without `dangerous_tools=True`)
- [ ] Git tag `v0.2.0` created and pushed
- [ ] PyPI release published: `pip install seekflow==0.2.0`

## Blocked by

- Issues #1 through #29 (all must be completed and merged before release)

## HITL notes

- **Human decision required**: whether to change classifier from "Beta" to "Production/Stable" or keep at Beta for v0.2.0
- **Human decision required**: version number — is 0.2.0 correct or should this be 0.1.1 given the breaking change scope
- **Human action required**: PyPI publish token, GitHub release creation
