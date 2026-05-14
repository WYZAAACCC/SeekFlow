# Build Policy Engine for centralized tool call authorization

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** enhancement
**State:** ready-for-agent

## What to build

New module `seekflow.policy` containing `PolicyEngine` — the centralized authorization gate that every tool call passes through before execution.

**`PolicyDecision`**:
```python
@dataclass
class PolicyDecision:
    allowed: bool
    reason: str = ""
    requires_approval: bool = False
    approval_context: dict | None = None
    sanitized_args: dict | None = None  # args after policy transformations
```

**`PolicyEngine`**:
- `authorize(tool_def: ToolDefinition, args: dict, context: RunContext) -> PolicyDecision`
- Checks in order:
  1. **Capability check**: does the tool's declared capabilities match what it's trying to do?
  2. **Workspace boundary**: if `workspace_root` set, validate all path arguments via `safe_join()`
  3. **Domain/IP allowlist**: if `allowed_domains` set, validate all URL arguments via `validate_url()`
  4. **Input size**: reject if serialized args exceed `max_input_bytes`
  5. **Risk-based gating**: `destructive` + no approval → deny; `code_exec` + no sandbox → deny
  6. **Approval check**: if `requires_approval=True`, return `requires_approval=True` (caller handles HITL)
  7. **Sanitization**: redact secrets from args before execution (best-effort)

**Integration**: `ToolExecutor.execute()` calls `policy_engine.authorize()` before invoking the tool function. On `allowed=False`, returns `ToolExecutionResult(ok=False, error=decision.reason)` without executing. On `requires_approval=True`, the executor signals back to the runtime which then invokes the HITL callback if configured.

**Default policies**: the engine ships with sensible defaults — deny code_exec unless sandbox configured, deny write without workspace root, require approval for destructive.

## Acceptance criteria

- [ ] `PolicyEngine.authorize()` returns `PolicyDecision(allowed=False)` for tool with code_exec capability and no sandbox configured
- [ ] `PolicyEngine.authorize()` returns `PolicyDecision(allowed=False)` for tool with filesystem.write and no workspace_root
- [ ] `PolicyEngine.authorize()` returns `PolicyDecision(allowed=True)` for tool with filesystem.read and valid workspace_root
- [ ] `PolicyEngine.authorize()` returns `PolicyDecision(requires_approval=True)` for destructive risk tool
- [ ] URL arguments validated against tool's `allowed_domains`
- [ ] Path arguments validated against tool's `workspace_root`
- [ ] `ToolExecutor.execute()` calls policy engine BEFORE `tool_def.func(**args)`
- [ ] Denied tool call returns error result without executing function
- [ ] Policy decision logged in tool audit trail (see issue #18)
- [ ] Unit test: read_file within workspace → allowed
- [ ] Unit test: read_file outside workspace → denied
- [ ] Unit test: fetch_url to allowed domain → allowed
- [ ] Unit test: fetch_url to blocked domain → denied
- [ ] Unit test: run_python without sandbox → denied

## Blocked by

- Issue #11 (ToolPolicy schema must exist)

## Depends on for integration

- Issue #5 (safe_join) — used for workspace boundary checks
- Issue #6 (validate_url) — used for domain/IP checks
