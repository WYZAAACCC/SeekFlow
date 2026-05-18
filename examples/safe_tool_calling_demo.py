"""Safe Tool Calling Demo — Path sandbox, SSRF protection, secret redaction.

SeekFlow intercepts dangerous operations before they execute:
- Path traversal (../../etc/passwd) → blocked by safe_join()
- SSRF to metadata endpoint → blocked by validate_url()
- API keys in logs → redacted by redact_secrets()

All of these work WITHOUT an agent — just import and call the functions directly.

Run:
    python examples/safe_tool_calling_demo.py
"""

import os
from seekflow.security import safe_join, validate_url, redact_secrets
from seekflow.sandbox import ProcessSandbox

# ── 1. Path Sandbox: blocks directory traversal ──
print("=== 1. Path Sandbox ===")
try:
    safe_join("/workspace", "../../etc/passwd")
    print("  WARNING: traversal NOT blocked!")
except (ValueError, PermissionError) as e:
    print(f"  Blocked ../ traversal: {type(e).__name__}")

try:
    safe_join("/workspace", "%2e%2e/secret.txt")
    print("  WARNING: encoded traversal NOT blocked!")
except (ValueError, PermissionError) as e:
    print(f"  Blocked %%2e%%2e traversal: {type(e).__name__}")

print(f"  Normal path works: {safe_join('/workspace', 'src/app.py')}")

# ── 2. SSRF Protection: blocks internal/metadata IPs ──
print("\n=== 2. SSRF Protection ===")
tests = [
    ("http://169.254.169.254/latest/meta-data", False, "metadata endpoint"),
    ("https://api.example.com/v1", True, "public API"),
    ("http://192.168.1.1/admin", False, "private IP"),
    ("http://10.0.0.1/internal", False, "class A private"),
    ("http://127.0.0.1:8080/debug", False, "loopback"),
]
for url, expected, label in tests:
    result = validate_url(url)
    status = "OK" if result == expected else f"FAIL (expected {expected})"
    print(f"  {url:50s} -> {result:5}  [{status}] {label}")

# Domain allowlist mode
print(f"\n  With domain allowlist:")
print(f"    api.example.com   -> {validate_url('https://api.example.com/v1', allow_domains={'api.example.com'})}")
print(f"    evil.com          -> {validate_url('https://evil.com/page', allow_domains={'api.example.com'})}")

# ── 3. Secret Redaction: strips credentials from logs ──
print("\n=== 3. Secret Redaction ===")
samples = [
    "DEBUG: api_key=sk-1234567890abcdef1234567890",
    "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature",
    "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE",
    '{"password": "s3cr3t_p@ssw0rd!", "username": "admin"}',
]
for text in samples:
    safe = redact_secrets(text)
    changed = "REDACTED" if safe != text else "UNCHANGED"
    print(f"  {changed}: {safe[:80]}")

# ── 4. Agent setup with dangerous tools (proper API) ──
print("\n=== 4. Agent Setup ===")
print("""
Correct way to load tools with SeekFlow v0.3.7:

    from seekflow import DeepSeekAgent
    from seekflow.sandbox import ProcessSandbox

    agent = DeepSeekAgent(
        role="researcher", goal="search and analyze information", backstory="senior researcher",
        api_key="sk-...", model="deepseek-v4-pro",
        dangerous_tools=True,  # explicit opt-in
    )
    agent.with_default_tools()                        # 4 safe tools
    agent.allow_filesystem(root="/workspace")          # 3 file tools
    agent.allow_network(domains={"api.example.com"})   # 1 network tool
    agent.allow_python(sandbox=ProcessSandbox())       # 1 code tool
    agent.allow_sqlite(root="/data", readonly=True)    # 1 SQL tool
    # Total: 10 tools, all policy-enforced

Note: dangerous_tools=True alone does NOT add tools.
You must explicitly call allow_*() for each category you need.
""")
