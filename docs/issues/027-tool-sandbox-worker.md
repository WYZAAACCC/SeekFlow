# Implement Tool Sandbox Worker with container/jail isolation

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** enhancement
**State:** ready-for-agent

## What to build

Implement the `ContainerSandbox` and `ProcessSandbox` backends for `seekflow.sandbox` (interface defined in issue #20), providing real isolation for code execution.

**`ProcessSandbox`** (no Docker dependency, works on any machine):
- Execute code in a subprocess with `subprocess.run()` but with hardened isolation:
  - `env={}` — no inherited environment variables (explicit allowlist only)
  - `cwd=/tmp/sandbox-<uuid>` — isolated temp directory, deleted after execution
  - `preexec_fn=os.setuid/setgid` (Unix) — drop privileges to nobody
  - Resource limits via `resource.setrlimit()`: CPU time, memory (RLIMIT_AS), file size (RLIMIT_FSIZE), process count (RLIMIT_NPROC)
  - Network isolation: not enforceable in pure Python subprocess, so block any network-using stdlib modules by pre-pending a restrictive startup snippet
  - `umask 0o077` — files created in sandbox not readable by other users

**`ContainerSandbox`** (Docker-based, full isolation):
- Build a minimal `seekflow-sandbox` Docker image (FROM python:3.11-slim, no network tools)
- Execute code via `docker run --rm --network none --memory 256m --cpus 1 --read-only --tmpfs /tmp:noexec --user 1000:1000 seekflow-sandbox python -c "<code>"`
- No network, read-only rootfs, non-root user, memory/cpu limits
- Container auto-removed after execution

**Security policy per sandbox type:**
| Capability | ProcessSandbox | ContainerSandbox |
|-----------|---------------|-----------------|
| filesystem.read | workspace only | workspace only |
| filesystem.write | sandbox dir only | sandbox dir only |
| network | ❌ blocked | ❌ blocked (--network none) |
| env access | ❌ empty | ❌ empty |
| CPU limit | RLIMIT_CPU | --cpus 1 |
| Memory limit | RLIMIT_AS | --memory 256m |
| Timeout | subprocess timeout | docker timeout |

**Fallback chain**: `ToolExecutor` tries `ContainerSandbox` first (if Docker available), falls back to `ProcessSandbox` (with loud warning), falls back to `NoSandbox` (denies execution).

## Acceptance criteria

- [ ] `ProcessSandbox.execute()` runs Python code in isolated subprocess
- [ ] Subprocess has no inherited env vars (env={})
- [ ] Subprocess runs as nobody user (Unix) with dropped privileges
- [ ] CPU limit enforced (infinite loop killed within timeout)
- [ ] Memory limit enforced (excessive allocation → MemoryError or OOM kill)
- [ ] `ContainerSandbox.execute()` runs code in Docker container
- [ ] Docker container has --network none (verified: `urllib.request` fails)
- [ ] Docker container has --read-only rootfs (verified: file creation fails outside /tmp)
- [ ] Fallback chain: Container → Process → NoSandbox
- [ ] `NoSandbox` always returns error (code execution denied)
- [ ] Sandbox timeout independent of tool timeout (tool timeout can be shorter)
- [ ] Unit test: ProcessSandbox, code "print(open('/etc/passwd').read())" → sandbox directory has no /etc/passwd
- [ ] Unit test: ProcessSandbox, code "import os; print(os.environ)" → empty dict
- [ ] Unit test: ProcessSandbox, code "while True: pass" → killed by timeout
- [ ] Unit test: ContainerSandbox, code "import urllib; urllib.request.urlopen('http://example.com')" → network error

## Blocked by

- Issue #20 (sandbox interface defined, NoSandbox and LocalThreadSandbox implemented)
