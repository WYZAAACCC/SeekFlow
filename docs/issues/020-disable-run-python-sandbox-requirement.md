# Disable run_python by default; require sandbox policy for code execution

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** bug
**State:** ready-for-agent

## What to build

`builtins.run_python()` currently writes user code to a temp file and executes it via `subprocess.run(["python", tmp.name])` with only a timeout. This exposes the host filesystem, network, environment variables, and process space to any code the model generates. This must be disabled by default and require explicit sandbox configuration.

1. **`run_python` disabled by default**: the function is gated behind `ToolPolicy(risk="code_exec", requires_approval=True)`. When `dangerous_tools=False` (default), it's not registered. When `dangerous_tools=True`, it's registered but `PolicyEngine` denies it unless a sandbox is configured.

2. **Sandbox abstraction** (`seekflow.sandbox`):
```python
class ToolSandbox(ABC):
    @abstractmethod
    def execute(self, code: str, timeout: float, env: dict | None = None) -> SandboxResult: ...

class LocalThreadSandbox(ToolSandbox):
    """Current behavior — execute in subprocess. Emits loud warning on use."""
    # Preserved for backward compat but marked UNSAFE

class ContainerSandbox(ToolSandbox):
    """Docker/podman-based isolation."""
    # P2 implementation — interface defined now

class NoSandbox(ToolSandbox):
    """Always denies execution."""
```

3. **`run_python` rewrite**: accepts a `sandbox: ToolSandbox` parameter. Default sandbox is `NoSandbox()` which returns an error. Users must explicitly configure a sandbox to enable code execution.

4. **`PolicyEngine` integration**: tools with `risk="code_exec"` require `sandbox is not NoSandbox` to pass authorization. Otherwise returns `PolicyDecision(allowed=False, reason="code_exec requires a configured sandbox")`.

5. **Current implementation preserved as `LocalThreadSandbox`** with a deprecation warning: "LocalThreadSandbox runs code on the host with no isolation. For production, use ContainerSandbox."

## Acceptance criteria

- [ ] `run_python` requires `ToolPolicy(risk="code_exec")` to register
- [ ] `PolicyEngine` denies code_exec tools when sandbox is NoSandbox
- [ ] `NoSandbox` is the default — code execution denied by default
- [ ] `LocalThreadSandbox` works but emits `DeprecationWarning`
- [ ] `ContainerSandbox` interface defined (implementation in issue #27)
- [ ] `dangerous_tools=False` (default) → `run_python` not available
- [ ] `dangerous_tools=True` + `LocalThreadSandbox` → `run_python` works with warning
- [ ] Unit test: code_exec without sandbox → PolicyEngine denies
- [ ] Unit test: code_exec with LocalThreadSandbox → PolicyEngine allows with warning

## Blocked by

- Issue #11 (ToolPolicy schema)
- Issue #12 (Policy Engine)

## Depends on for full implementation

- Issue #27 (ContainerSandbox — P2)
