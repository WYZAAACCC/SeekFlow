# Implement comprehensive tool audit trail per execution

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** enhancement
**State:** ready-for-agent

## What to build

Every tool execution must produce an audit record capturing the full decision chain. This enables security review, debugging, and compliance.

**`ToolAuditRecord`**:
```python
@dataclass
class ToolAuditRecord:
    timestamp: float
    tool_name: str
    tool_call_id: str
    args_hash: str              # SHA256 of canonical JSON args
    result_hash: str | None     # SHA256 of canonical JSON result
    latency_ms: int
    ok: bool
    error: str | None
    policy_decision: str        # "allowed", "denied", "approval_required"
    policy_reason: str
    risk_level: str
    repair_attempted: bool
    repair_confidence: float | None
    cache_hit: bool
    redactions: int
    run_id: str
    step: int
```

**Integration**: `ToolExecutor.execute()` populates and emits an audit record after every execution (success or failure). The record is:
1. Appended to `TraceRecorder` events (for JSON trace export)
2. Emitted as a structured log at DEBUG level
3. Stored in `RunState.audit_trail` (for in-memory access during the run)

**Hash computation**: `args_hash` uses canonical JSON (`json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(",", ":"))`) before SHA256. This enables deduplication and idempotency key generation. Sensitive values are redacted BEFORE hashing (via `redact_secrets()` from issue #10).

**Audit trail export**: `TraceRecorder.export()` includes the full audit trail array. `ToolRuntimeResult` exposes `audit_trail` for programmatic access.

## Acceptance criteria

- [ ] `ToolAuditRecord` populated for every tool execution
- [ ] `args_hash` computed from canonical JSON (deterministic, redacted)
- [ ] `result_hash` computed from canonical JSON result (None on error)
- [ ] Audit record includes policy_decision and policy_reason
- [ ] Audit records appended to TraceRecorder
- [ ] Audit records accessible via `ToolRuntimeResult.audit_trail`
- [ ] Structured log emitted at DEBUG level with audit data
- [ ] Same args produce same args_hash (deterministic)
- [ ] Unit test: successful tool → audit record with ok=True, hashes present
- [ ] Unit test: denied tool → audit record with ok=False, policy_decision="denied"
- [ ] Unit test: two calls with same args → identical args_hash

## Blocked by

- Issue #12 (Policy Engine — provides policy_decision)

## Depends on for integration

- Issue #10 (secret redaction — used before hashing)
