# Implement workspace-root file path sandbox with extension allowlisting

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** bug
**State:** ready-for-agent

## What to build

New module `seekflow.security` with the core path safety primitive `safe_join()` and a file-read policy helper:

1. **`safe_join(root: Path, user_path: str) -> Path`**
   - Resolves both `root` and `target = (root / user_path).resolve()` to absolute canonical paths
   - Raises `PermissionError` if `target` is not relative to `root` (catches `../`, symlink escapes, etc.)
   - Handles Windows path separators and drive letters correctly when on Windows

2. **`validate_file_access(path: Path, *, workspace_root: Path, allow_ext: set[str] | None = None, deny_ext: set[str] | None = None, max_bytes: int = 5_000_000) -> Path`**
   - Calls `safe_join()` first
   - Checks extension against `allow_ext` (if set) or `deny_ext` defaults: `.env`, `.key`, `.pem`, `.sqlite`, `.db`, `.log`, `.exe`, `.dll`, `.so`, `.bin`
   - Checks file size against `max_bytes`
   - Returns the validated resolved path on success, raises on violation

3. **Default deny-list for sensitive filenames**: even if extension is allowed, reject filenames matching `.env`, `credentials`, `secret`, `id_rsa`, `known_hosts`, `config.yaml` (common config patterns).

## Acceptance criteria

- [ ] `safe_join(Path("/workspace"), "../../etc/passwd")` raises `PermissionError`
- [ ] `safe_join(Path("/workspace"), "subdir/../../../etc/passwd")` raises `PermissionError`
- [ ] `safe_join(Path("/workspace"), "subdir/file.txt")` returns resolved path within workspace
- [ ] `validate_file_access(path, workspace_root=..., allow_ext={".txt", ".md"})` rejects `.env` files
- [ ] `validate_file_access(path, workspace_root=..., max_bytes=100)` rejects files over 100 bytes
- [ ] Sensitive filenames (`.env`, `id_rsa`, `credentials.json`) are rejected regardless of extension
- [ ] Empty user_path, null bytes, and non-string inputs are handled gracefully
- [ ] Regression test: `../../../etc/passwd` path traversal rejected
- [ ] Regression test: symlink pointing outside workspace root rejected (on platforms supporting symlinks)

## Blocked by

None — can start immediately. Used by issue #4 (safe_read_file) and #22 (file limits).
