# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | ✅ Active |
| 0.1.x   | ❌ End of life |

## Reporting a Vulnerability

Report security vulnerabilities to the project maintainers via GitHub Security Advisory. Do NOT open public issues for security bugs.

## Security Model

SeekFlow executes LLM-generated tool calls on your infrastructure. The v0.2.0 security model is:

### Trust Boundaries
1. **User input** → trusted (the human operator)
2. **System prompt** → trusted (defined by the developer)
3. **Model output** → untrusted (can be manipulated via prompt injection)
4. **Tool results** → untrusted (external data from web, files, databases, MCP servers)

### Mitigations
- **Policy Engine**: every tool call authorized before execution
- **Workspace sandbox**: file reads confined to configurable root
- **SSRF blocking**: URL validation blocks private IPs and restricted schemes
- **Secret redaction**: API keys, tokens, passwords redacted from logs/traces
- **Untrusted content wrapper**: tool outputs marked as data, not instructions
- **Default tools off**: dangerous tools require explicit opt-in
- **Per-tool timeout**: hung tools cannot block the runtime indefinitely

### Known Limitations
- Secret redaction is regex-based (best-effort), not a substitute for not putting secrets in tool output
- Thread-based tool timeout cannot forcibly kill Python threads (cooperative only)
- ContainerSandbox requires Docker; fallback is ProcessSandbox (less isolated)

## Dependency Policy
- All dependencies are pinned with known-good versions
- Bandit security scan runs in CI on every PR
- pip-audit checks for known vulnerabilities
