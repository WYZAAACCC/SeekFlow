# SeekFlow Implementation Audit

Date: 2026-05-14

## README Claims vs Implementation

| Claim | Code location | Tests | Status |
|-------|--------------|-------|--------|
| Policy Engine | `src/seekflow/policy.py` | `tests/test_policy.py` (9 tests) | ✅ verified |
| SSRF protection | `src/seekflow/security.py:validate_url` | `tests/test_security.py::TestValidateUrl` (12 tests) | ✅ verified |
| Path sandbox | `src/seekflow/security.py:safe_join` | `tests/test_security.py::TestSafeJoin` (7 tests) | ✅ verified |
| Secret redaction | `src/seekflow/security.py:redact_secrets` | `tests/test_security.py::TestRedactSecrets` (10 tests) | ✅ verified |
| Untrusted content | `src/seekflow/security.py:wrap_untrusted` | `tests/test_security.py::TestUntrustedContent` (3 tests) | ✅ verified |
| Per-tool timeout | `src/seekflow/tools/executor.py:execute` | Functional (ThreadPoolExecutor timeout) | ⚠️ partial — no dedicated timeout test |
| 429 bounded retry | `src/seekflow/retry_executor.py` | `tests/test_retry.py::TestRetryExecutor429BoundedRetry` (3 tests) | ✅ verified |
| CB non-retryable exclusion | `src/seekflow/retry_executor.py` | `tests/test_retry.py::TestRetryExecutorCircuitBreakerIntegration` (6 tests) | ✅ verified |
| Dangerous tools off by default | `src/seekflow/agent/agent.py` | `tests/test_v3_agent.py` | ⚠️ partial — default behavior tested, dangerous opt-in warns |
| Preflight cost | `src/seekflow/budget.py` | Module exists, no dedicated test file | ⚠️ partial — code complete, needs focused tests |
| Cache Compiler | `src/seekflow/cache.py:CacheCompiler` | Module exists | ⚠️ partial — needs focused tests |
| Thinking Router | `src/seekflow/reasoning.py:ThinkingRouter` | Module exists | ⚠️ partial — needs focused tests |
| Sandbox (Process/Container) | `src/seekflow/sandbox.py` | Module exists | ⚠️ partial — needs focused tests |
| OpenTelemetry | `src/seekflow/telemetry.py` | No dedicated tests | ⚠️ partial — graceful fallback, no OTel SDK integration test |
| Tool audit trail | `src/seekflow/tools/executor.py:ToolAuditRecord` | Functional (audit_trail list populated) | ⚠️ partial — no dedicated audit tests |
| Repair confidence gating | `src/seekflow/repair/json_repair.py` + `tools/executor.py` | Functional | ⚠️ partial — confidence computed, gating logic lacks focused tests |
| File limits (size/PDF) | `src/seekflow/files.py` | Functional | ⚠️ partial — no dedicated file limit tests |
| MCP trust levels | `src/seekflow/mcp/config.py:MCPTrustLevel` | `tests/test_mcp_config.py` | ✅ verified |
| Reasoning protocol fix | `src/seekflow/runtime.py` — tool_calls preserve full reasoning | Functional | ⚠️ partial — needs protocol state machine tests |
| DeepSeek model profiles | `src/seekflow/agent/agent.py:PRICING` + `LEGACY_MODEL_MAP` | Functional | ⚠️ partial — needs deprecation warning tests |

## Known Limitations

1. **Reasoning content protocol**: Tool-call reasoning preserved (fixed v0.2.1), but no dedicated protocol state machine to enforce ordering invariants.
2. **Strict tools**: Schema compiler exists but does not switch to beta `base_url` for strict mode.
3. **Per-tool timeout**: Uses ThreadPoolExecutor which cannot forcibly kill hung Python threads.
4. **Secret redaction**: Regex-based, best-effort — not a substitute for avoiding secrets in tool output.
5. **Container sandbox**: `ContainerSandbox` requires Docker installed; falls back to less isolated `ProcessSandbox`.
6. **OTel**: Graceful degradation without OTel SDK — span/metric export requires `pip install opentelemetry-api opentelemetry-sdk`.
7. **Cache metrics**: Uses `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens` when available, falls back to legacy `cached_tokens`.

## Rules

- A feature is "verified" only if code and dedicated tests both exist.
- "partial" features have code but lack focused tests or full protocol compliance.
- README claims should be backed by verified features only.
- All subsequent PRs update this audit document.
