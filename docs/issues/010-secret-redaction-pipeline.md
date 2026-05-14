# Implement secret/PII redaction across error messages, logs, traces, and tool results

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** bug
**State:** ready-for-agent

## What to build

New function `redact_secrets(text: str) -> str` in `seekflow.security` that scans for and replaces credential patterns before any text enters the model context, log output, or trace data.

**Patterns to redact:**
- DeepSeek API keys: `sk-[a-zA-Z0-9]{32,}` → `sk-[REDACTED]`
- Bearer tokens in headers/strings: `Bearer\s+[a-zA-Z0-9._\-]+` → `Bearer [REDACTED]`
- Generic API key assignments: `(api_key|apikey|secret|password|token|auth)\s*[:=]\s*["']?[^"'\s]{8,}["']?` → `$1=[REDACTED]` (case-insensitive)
- JWT tokens: `eyJ[a-zA-Z0-9._\-]{20,}` → `[REDACTED_JWT]`
- Database connection strings: `(postgresql|mysql|mongodb|redis|sqlite)://[^@]+@` → `$1://[REDACTED]@`
- AWS/GCP/Azure credential patterns: `AKIA[0-9A-Z]{16}`, `AIza[0-9A-Za-z\-_]{35}`, etc.

**Integration points:**
1. `ToolExecutor.execute()` — call before returning tool result string
2. `ToolRuntime.chat()` — call when appending error messages to message list
3. `TraceRecorder` — call in `record()` for any string field
4. Exception handling — call in `__str__` or log emission
5. `_compress_reasoning()` — call on reasoning content before context injection

**Design constraint**: redaction must be fast (regex-based, sub-millisecond for typical strings). It is best-effort — not a replacement for not putting secrets in tool outputs in the first place. The documentation must state this clearly.

**`RedactionStats`** tracking: count redactions per run, exposed in `RunDiagnostics` for awareness.

## Acceptance criteria

- [ ] `redact_secrets('Authorization: Bearer sk-abc123def456')` returns `'Authorization: Bearer [REDACTED]'`
- [ ] `redact_secrets('api_key = "my-secret-key-here"')` returns `'api_key=[REDACTED]'`
- [ ] `redact_secrets('postgresql://user:pass@localhost/db')` returns `'postgresql://[REDACTED]@localhost/db'`
- [ ] `redact_secrets('eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4')` returns `'[REDACTED_JWT]'`
- [ ] Normal text without secrets passes through unchanged
- [ ] Redaction invoked in ToolExecutor before tool results enter message list
- [ ] Redaction invoked in TraceRecorder for all string-valued event data
- [ ] `RunDiagnostics` includes redaction count
- [ ] Regression test: API key in tool error message → redacted in model context
- [ ] Regression test: JWT in web page content → redacted in trace
- [ ] Performance: redacting 100KB string < 10ms

## Blocked by

None — can start immediately.
