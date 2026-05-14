# Implement SSRF protection: URL scheme/IP/domain validation + DNS rebinding guard

## Parent

[PRD: Security & Production Hardening](../PRD-security-production-hardening.md)

## Type

AFK

**Category:** bug
**State:** ready-for-agent

## What to build

New functions in `seekflow.security` that validate URLs before any HTTP request is made by built-in tools or user tools:

1. **`validate_url(url: str, *, allow_schemes: set[str] = {"https", "http"}, allow_domains: set[str] | None = None, block_private_ips: bool = True) -> bool`**
   - Parse URL, reject non-allowlisted schemes (blocks `file://`, `gopher://`, `ftp://`, `dict://`, etc.)
   - If `allow_domains` is set, only those exact domains pass
   - If `block_private_ips=True`, resolve the hostname and check every resulting IP against private ranges:
     - `127.0.0.0/8`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
     - `169.254.0.0/16` (link-local)
     - `0.0.0.0/8` (current network)
     - `::1` (IPv6 loopback), `fe80::/10` (link-local)
   - Block bare IP addresses that resolve to private ranges
   - Return `False` with a descriptive reason string (via exception or return type) for any violation

2. **DNS rebinding guard**: after resolving the hostname, verify that each resulting IP passes the same private-IP check. This catches TOCTOU attacks where DNS changes between validation and request.

3. **Integration point**: Modify `builtins.fetch_url()` and `agent.py` `download_page()` to call `validate_url()` before making the request. If validation fails, return an error string rather than making the request.

## Acceptance criteria

- [ ] `validate_url("http://127.0.0.1:8080/admin")` returns False (loopback)
- [ ] `validate_url("http://192.168.1.1/")` returns False (private IP)
- [ ] `validate_url("http://169.254.169.254/latest/meta-data/")` returns False (link-local, AWS metadata)
- [ ] `validate_url("file:///etc/passwd")` returns False (blocked scheme)
- [ ] `validate_url("gopher://localhost:25/")` returns False (blocked scheme)
- [ ] `validate_url("https://docs.deepseek.com/api")` returns True
- [ ] `validate_url("https://docs.deepseek.com", allow_domains={"example.com"})` returns False (domain not allowed)
- [ ] `validate_url("https://example.com", allow_domains={"example.com"})` returns True
- [ ] DNS rebinding: hostname resolving to private IP after initial lookup → rejected
- [ ] `fetch_url("http://localhost:8080/")` returns "Fetch failed: URL blocked" error string
- [ ] Regression test: localhost URL rejected by `validate_url`
- [ ] Regression test: private IP URL rejected
- [ ] Regression test: metadata service IP (169.254.169.254) rejected

## Blocked by

None — can start immediately.
