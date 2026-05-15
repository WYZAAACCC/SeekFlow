# SeekFlow Production Readiness Checklist

Checklist for graduating SeekFlow between security levels. Current target: **Level 2 semi-production** (v0.3.x).

## Release Gate

Every release must pass:

- [ ] `pytest` — 0 failed
- [ ] `python scripts/check_xfail_policy.py --strict-core` exits 0
- [ ] `ruff check` — 0 errors
- [ ] `README.md` version == `pyproject.toml` version
- [ ] No known P0/P1 security gaps

## Security Gates (v0.3.x)

- [ ] policy.runner cannot decrease required isolation (PR-1)
- [ ] code_exec/destructive tools without `container_codegen_trusted` are denied (PR-2)
- [ ] ProcessRunner bounds all output types, not just strings (PR-3)
- [ ] Cache read/write unified under `_cache_allowed` (PR-4)
- [ ] `metadata.trusted` no longer controls output wrapping (PR-5)
- [ ] No-policy tools are denied by default (PR-6)
- [ ] `authorize_with_context()` emits DeprecationWarning (PR-7)
- [ ] ContainerSandbox timeout does explicit `docker kill/rm` (PR-8)
- [ ] `check_xfail_policy.py --strict-core` available (PR-9)
- [ ] Documentation clearly states Level 2 boundaries (PR-10)

## Test Gates

- [ ] Runner minimum isolation tests pass (≥3)
- [ ] Container runner semantics tests pass (≥3)
- [ ] Process large output tests pass (≥3)
- [ ] Cache policy tests pass (≥3)
- [ ] Trusted output tests pass (≥3)
- [ ] No-policy execution tests pass (≥3)
