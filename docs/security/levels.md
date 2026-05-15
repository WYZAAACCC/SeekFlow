# SeekFlow Security Levels

## Level Definitions

| Level | Status | Scope | Trust Model |
|-------|--------|-------|-------------|
| **Level 0** | Supported | Local trusted scripts | Fully trusted code in trusted environment |
| **Level 1** | Supported | Internal trusted users + trusted tools | Trusted users, registered tools |
| **Level 2** | Supported (current) | Non-fully-trusted prompts + trusted registered tools + limited file/network | Untrusted prompts, trusted tools, policy-enforced |
| **Level 3** | Not supported | Untrusted third-party tools / untrusted MCP / plugin market | Untrusted tools from external sources |
| **Level 4** | Not supported | Multi-tenant SaaS / strong tenant isolation / compliance audit | Mutual distrust between tenants |

---

## Level 2 — Current Capabilities (v0.3.7)

### What Level 2 supports

- **Non-fully-trusted prompts**: Prompts may come from partially-trusted users or external sources. The framework enforces policy on all tool calls regardless of prompt origin.
- **Trusted registered tools**: All tools are registered by the operator with explicit `ToolPolicy`. No dynamic/plugin-based tool loading.
- **Limited file access**: Filesystem tools require `workspace_root` and `filesystem.read`/`filesystem.write` capabilities. Path traversal is blocked via `safe_join()`.
- **Limited network access**: Network tools require non-empty `allowed_domains` and pass SSRF validation (`validate_url_strict`).
- **Process isolation with hard timeout**: Untrusted tools run in spawned subprocesses (`ProcessRunner`). Timeout kills via `terminate()` → 0.5s grace → `kill()`.
- **Schema validation with hallucination defense**: Tool arguments are validated against JsonSchema (Draft202012Validator) with default `additionalProperties=false`.

### What Level 2 does NOT support

- **Untrusted third-party tools**: All tools must be registered by the operator. No dynamic tool loading from external sources.
- **Untrusted MCP servers**: MCP tools inherit the trust of their server. No MCP sandboxing beyond what the MCP protocol provides.
- **Plugin markets**: No mechanism for loading tools from untrusted sources at runtime.
- **General code execution without containers**: `code_exec` tools require `ContainerSandbox` (Docker). Without it, they are **denied**.

### Isolation guarantees

| Runner | Isolation type | Use case |
|--------|---------------|----------|
| `InProcessRunner` | None (trust required) | Trusted read tools with `ToolPolicy(trusted=True, risk="read")` |
| `ProcessRunner` | Process boundary + hard timeout | Default for untrusted read/network/write tools |
| `ContainerRunner` | Docker container (`--network none`, `--read-only`, etc.) | Required for `code_exec`/`destructive` tools |

**ContainerRunner boundary**: The tool function runs **in-process** to generate a `CodeExecutionRequest`. Only tools with `ToolPolicy(trusted=True, container_codegen_trusted=True)` are accepted — the tool function must be a safe code-builder, not an arbitrary implementation. The generated code then runs inside the Docker container with full isolation. On timeout, the container is explicitly killed and removed (`docker kill` + `docker rm -f`) to prevent zombie containers.

**Important**: `ProcessRunner` provides **timeout isolation and crash isolation**, not full security sandboxing. A malicious tool running in `ProcessRunner` can access the host filesystem, environment variables, and network. For strong isolation, use `ContainerRunner` with `ContainerSandbox`.

---

## Level 3 — Future (not yet supported)

Level 3 would require:

- **Tool signing and verification**: Cryptographic signatures on tool code.
- **Capability-based MCP sandboxing**: Per-server capability limits with enforcement.
- **Plugin isolation**: Each plugin in its own sandbox (container or WASM).
- **Dynamic policy**: Policies evaluated at load time, not just registration time.

---

## Level 4 — Future (not yet supported)

Level 4 would require:

- **Per-tenant policy**: Isolation between tenants sharing the same runtime.
- **Compliance audit trail**: Immutable, append-only audit logs with cryptographic verification.
- **Resource accounting**: Per-tenant CPU/memory/network quota enforcement.
- **Data residency**: Tenant data confined to specific regions or storage backends.
