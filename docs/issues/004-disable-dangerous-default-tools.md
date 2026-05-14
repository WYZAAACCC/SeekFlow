# Disable dangerous default tools, add `dangerous_tools` flag + safe tool variants

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** bug
**State:** ready-for-agent

## What to build

`Agent.with_default_tools()` currently registers 11 tools including `read_file`, `web_search`, `download_page`, `fetch_url`, `run_python`, `query_sql`, `save_result` — all without any permission model. A prompt-injected model can read local files, make arbitrary HTTP requests, execute Python code on the host, write files, and query SQLite databases.

1. **Change default behavior**: `with_default_tools()` registers only `calculate` (AST-safe math evaluator). All other tools require explicit opt-in.

2. **Add `dangerous_tools` parameter** to `Agent.__init__()`: when `True`, registers all 11 tools (preserving backward compatibility for users who understand the risk). Default is `False`.

3. **Provide safe tool factory functions** that wrap dangerous tools with policy constraints:
   - `safe_read_file(root: Path, allow_ext: set[str])` → `read_file` scoped to workspace
   - `safe_fetch_url(allow_domains: set[str])` → `fetch_url` with domain allowlist
   - `safe_web_search(provider: str)` → `web_search` with controlled provider
   
   These safe variants are documented as the recommended path and usable without `dangerous_tools=True`.

4. **Add runtime warning**: when `dangerous_tools=True` is used, emit a `UserWarning` at agent creation time listing the risks.

## Acceptance criteria

- [ ] `Agent.with_default_tools()` with default parameters registers ONLY `calculate`
- [ ] `Agent(dangerous_tools=True).with_default_tools()` registers all 11 tools (backward compat)
- [ ] `safe_read_file(root=Path("/workspace"), allow_ext={".txt", ".md", ".json"})` returns a tool that rejects paths outside root
- [ ] `safe_fetch_url(allow_domains={"docs.deepseek.com"})` returns a tool that rejects other domains
- [ ] `Agent(dangerous_tools=True)` emits a `UserWarning` describing the risks
- [ ] Regression test: `dangerous_tools=False` (default) → `read_file` not available
- [ ] Regression test: `dangerous_tools=True` → all 11 tools available
- [ ] Regression test: `safe_read_file(root=...)` blocks `../` traversal

## Blocked by

None — can start immediately. (Issue #5 implements the underlying `safe_join` and can be developed in parallel.)
