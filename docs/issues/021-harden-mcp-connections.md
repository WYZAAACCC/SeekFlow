# Harden MCP connections: trust levels, capability allowlists, startup timeout, error observability

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** bug
**State:** ready-for-agent

## What to build

`MCPToolExecutor.connect_and_register()` currently:
- Silently `continue`s on connection failure, masking configuration errors
- Has no trust level concept for MCP servers
- Applies no capability allowlist — all tools from a server are registered
- Has no startup timeout for server processes
- Manual subprocess path has no stderr management

Fix each:

1. **Trust levels** on `MCPServerConfig`:
```python
class MCPTrustLevel(Enum):
    TRUSTED = "trusted"      # all capabilities allowed
    SANDBOXED = "sandboxed"  # read-only capabilities only
    UNTRUSTED = "untrusted"  # each tool requires approval
```

2. **Capability allowlist**: `MCPServerConfig` accepts `allowed_capabilities: set[str] | None`. If set, only tools matching these capabilities are registered. Tools from the server with capabilities outside the allowlist are skipped with a warning.

3. **Startup timeout**: `MCPServerConfig` accepts `startup_timeout: float = 10.0`. If the server doesn't respond to `initialize` within the timeout, the connection fails with a clear error. Previously this could hang indefinitely.

4. **Error observability**: Instead of `except Exception: continue`, connection failures are:
   - Logged at ERROR level with server name, command, and exception details
   - Stored in `MCPToolExecutor.connection_errors: dict[str, str]` for programmatic access
   - Optional `fail_fast: bool` on executor — if True, raises on first connection error instead of continuing
   - The `connect_and_register` return value includes tools that were successfully registered

5. **Stderr management**: manual subprocess path captures stderr and logs it at WARNING level. Stderr lines are truncated to 1000 chars each, max 10 lines.

6. **Schema validation**: each tool's `inputSchema` from the MCP server is validated against JSON Schema draft-07. Invalid schemas are rejected with a warning instead of silently registered.

## Acceptance criteria

- [ ] `MCPTrustLevel` enum defined and used in config
- [ ] `UNTRUSTED` server tools require approval for each call
- [ ] `SANDBOXED` server tools restricted to read capabilities only
- [ ] `allowed_capabilities` filters tools at registration time
- [ ] Startup timeout enforced (server unresponsive → error logged, not hung)
- [ ] Connection failures logged at ERROR with full context
- [ ] `connection_errors` dict accessible for health checks
- [ ] `fail_fast=True` raises on first connection error
- [ ] Stderr from manual subprocess captured and logged (truncated)
- [ ] Invalid inputSchema → warning, tool skipped
- [ ] Unit test: connection failure → error logged, executor continues (fail_fast=False)
- [ ] Unit test: connection failure → raises (fail_fast=True)
- [ ] Unit test: untrusted server → tools registered but require approval
- [ ] Unit test: schema validation rejects invalid schema

## Blocked by

None — can start immediately.
