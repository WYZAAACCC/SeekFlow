# Define ToolPolicy schema and integrate into ToolDefinition

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** enhancement
**State:** ready-for-agent

## What to build

New `ToolPolicy` model in `seekflow.policy` (or `seekflow.types`) and `ToolDefinition` extension:

```python
class ToolPolicy(BaseModel):
    capabilities: set[str] = Field(default_factory=set)
    risk: Literal["read", "write", "network", "code_exec", "destructive"] = "read"
    timeout_s: float = 30.0
    max_input_bytes: int = 1_000_000
    max_output_bytes: int = 100_000
    parallel_safe: bool = False
    requires_approval: bool = False
    allowed_domains: set[str] = Field(default_factory=set)
    workspace_root: Path | None = None
```

**Capability taxonomy:**
- `filesystem.read` — read files within workspace
- `filesystem.write` — write/modify files
- `network.public_http` — HTTP/HTTPS to public internet
- `network.any` — any network access (MCP, raw sockets)
- `code.exec` — execute code (Python, shell)
- `database.read` — read-only database queries
- `database.write` — write/modify database
- `system.command` — run system commands

**Risk levels and what they imply:**
- `read` — no side effects, parallel-safe, no approval needed
- `write` — idempotent by default, requires idempotency key
- `network` — subject to URL validation, domain allowlisting
- `code_exec` — requires sandbox, disabled by default
- `destructive` — always requires human approval

**`ToolDefinition` extension**: add `policy: ToolPolicy | None = None` field. When `None`, `PolicyEngine` uses a restrictive default policy (deny network/code_exec, 30s timeout, no parallel safety).

**Builder API**: `ToolDefinition.with_policy(ToolPolicy(...)) -> ToolDefinition` for fluent construction.

## Acceptance criteria

- [ ] `ToolPolicy` model exists with all fields and valid defaults
- [ ] Capability taxonomy documented with clear semantics
- [ ] `ToolDefinition.policy` field added (optional, None = restrictive default)
- [ ] `ToolDefinition.with_policy(policy)` returns modified copy
- [ ] ToolPolicy serializes/deserializes correctly (JSON roundtrip)
- [ ] Backward compat: existing `ToolDefinition` usage without policy still works (policy=None)
- [ ] Unit test: policy with `risk="destructive"` → `requires_approval=True` is auto-set
- [ ] Unit test: invalid risk value raises ValidationError

## Blocked by

None — can start immediately.
