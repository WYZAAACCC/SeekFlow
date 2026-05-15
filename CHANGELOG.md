# SeekFlow Changelog

## v0.3.7 — Level 2 Semi-Production + Lv3 Zero-Trust Tool Gateway

> Release date: 2026-05-16

### Lv3: Zero-Trust Tool Gateway (New)

SeekFlow graduates from a trusted Python tool runtime to a **zero-trust tool gateway**.
Third-party tools no longer enter the host Python process — they run in isolated containers
via ToolManifest contracts.

#### Phase B: ToolManifest v1 + Policy Pipeline

- **ToolManifest v1**: Declarative tool identity/capability/sandbox contract (`src/seekflow/tools/manifest.py`)
  - `NetworkManifest`, `FilesystemManifest`, `EnvManifest`, `SandboxManifest`
  - SHA-256 digest + signature fields for integrity verification
- **Manifest Loader**: YAML/JSON loading with auto format detection (`src/seekflow/tools/manifest_loader.py`)
- **Manifest Verifier**: Digest validation + signature verification placeholder (`src/seekflow/tools/manifest_verify.py`)
- **PolicyCompiler**: Compiles `ToolManifest` → `ToolPolicy` with Lv3 rules:
  - `source != "local"` → `trusted=False`, `trusted_output=False`, `runner=container`
  - Network/filesystem/env manifests compiled into policy constraints
- **PolicyLinter**: 11 DENY/WARN security rules (L001–L011):
  - Non-local tools cannot use in_process/process runner
  - Network requires allowed_domains; public_http requires url_params
  - Filesystem requires workspace_root; write requires approval
  - code_exec/destructive requires container runner
  - trusted_output denied for external sources
  - Wildcard domains and public-suffix-only domains blocked
- **ToolRegistry.register_from_manifest()**: Full verify → compile → lint → register pipeline
- **close_object_schema**: Applied at manifest load, MCP discovery, and executor validation

#### Phase C: ExternalToolRunner

- **ExternalToolRunner**: Containerized execution for third-party tools (`src/seekflow/tools/external_runner.py`)
  - JSON protocol: stdin input, stdout single JSON result
  - Docker isolation: `--network none`, `--cap-drop ALL`, `--read-only`
  - Fresh container per execution with unique name
  - Timeout → `docker kill` + `docker rm -f` (zombie prevention)
  - Output bounded + JSON validated + schema validated
  - Stderr captured for audit, never reaches model
- **planner.py**: `RUNNER_ORDER` extended with `external_container` (level 3)
  - `source != "local"` hard-gated to `external_container` early-return
- **executor.py**: `_runner_for()` dispatches `external_container` to `ExternalToolRunner`

#### Phase D: MCPGateway

- **MCPServerConfig hardening**:
  - `trust_level` default changed from `SANDBOXED` → `UNTRUSTED`
  - `command_digest` for command pinning
  - `freeze_tools` + `require_approval_for_mutation`
  - `call_timeout`, `idle_timeout`, `max_calls_per_run`
- **to_stdio_params()**: Now enforces `env_allowlist` filtering
- **MCPGateway** (`src/seekflow/mcp/gateway.py`):
  - `connect_and_freeze()`: tool discovery + schema freeze + policy compilation
  - `detect_mutation()`: tool list and schema change detection
  - `verify_frozen()`: re-discovery + mutation check + approval gate
  - `GatewayAuditRecord`: per-call request/response hashes
  - `kill_tree()`: process tree cleanup
- **MCP Policy** (`src/seekflow/mcp/policy.py`):
  - `validate_server_config`: MCP001–MCP004
  - `validate_tool_under_server`: MCP101–MCP103 (ceiling enforcement)

#### Phase E: EgressGateway + SecretBroker

- **EgressGateway** (`src/seekflow/network/egress.py`):
  - `EgressPolicy`: domains, schemes, ports, methods, TLS, private IP blocking
  - Request/response checking with size limits + redirect limits
  - Domain matching (exact + subdomain, case-insensitive)
  - DNS resolution + 12 RFC private/reserved IP ranges blocked
  - `EgressAuditEntry`: per-request audit trail
- **SecretBroker** (`src/seekflow/secrets/broker.py`):
  - `SecretRef`: name, scope, required, TTL
  - `resolve_for_tool()`: explicit secret injection, no ambient env
  - Env + Memory providers
  - `SecretAuditEntry`: audited without exposing values

#### Phase F: DurableAuditStore

- **AuditEvent**: Full tool identity + hashes + egress + secret refs (`src/seekflow/audit/model.py`)
- **JSONLAuditStore**: Append-only JSONL with `fsync` durability
- **SQLiteAuditStore**: WAL mode, indexed `query_by_run()`
- **verify_audit_chain()**: Hash chain integrity + tamper detection
- **CLI**: `seekflow audit verify` / `seekflow audit export`

### Lv2: Security Gates (from Improve13/14)

- **Runner minimum isolation**: `policy.runner` can only increase isolation, never decrease
- **ContainerRunner codegen gate**: `container_codegen_trusted=True` required
- **ProcessRunner bounded output**: All output types size-bounded in child process
- **Cache policy**: Default read-only; idempotent network with explicit opt-in
- **trusted_output in ToolPolicy**: Separated from execution trust; default False
- **No-policy deny-by-default**: `allow_unsafe_no_policy_execution` opt-in
- **authorize_with_context()**: DeprecationWarning
- **ContainerSandbox**: Named containers + explicit `docker kill/rm` on timeout
- **@model_validator**: ToolPolicy security invariants at construction time
- **CI**: `check_xfail_policy.py --strict-core` in GitHub Actions

### CLI

- **seekflow tool inspect/verify/install/list/audit**: Full Lv3 tool lifecycle CLI
- **seekflow audit verify/export**: Durable audit chain verification

---

## v0.3.6 — Level 2 Semi-Production Candidate

> Previous release baseline. ToolRunner isolation, hard timeout kill, JSON Schema
> validation, resource limit enforcement, container fail-closed.

---

## v0.2.0 — Policy Engine + Security Architecture

> PolicyEngine, ToolPolicy, path sandbox, SSRF protection, secret redaction,
> untrusted content wrapping, audit trail, thinking router, cache compiler.
