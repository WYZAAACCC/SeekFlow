"""Tests for seekflow.security — path sandbox, URL validation, secret redaction."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


class TestSafeJoin:
    """safe_join — resolve a user-supplied path within a workspace root."""

    def test_simple_subdir_returns_resolved_path(self):
        from seekflow.security import safe_join

        result = safe_join(Path("/workspace"), "subdir/file.txt")
        assert result == Path("/workspace/subdir/file.txt").resolve()

    def test_parent_traversal_rejected(self):
        from seekflow.security import safe_join

        with pytest.raises(PermissionError, match="outside workspace"):
            safe_join(Path("/workspace"), "../etc/passwd")

    def test_nested_parent_traversal_rejected(self):
        from seekflow.security import safe_join

        with pytest.raises(PermissionError, match="outside workspace"):
            safe_join(Path("/workspace"), "subdir/../../../etc/passwd")

    def test_absolute_path_outside_root_rejected(self):
        from seekflow.security import safe_join

        with pytest.raises(PermissionError, match="outside workspace"):
            safe_join(Path("/workspace"), "/etc/passwd")

    def test_empty_user_path_returns_root(self):
        from seekflow.security import safe_join

        result = safe_join(Path("/workspace"), "")
        assert result == Path("/workspace").resolve()

    def test_dot_path_returns_root(self):
        from seekflow.security import safe_join

        result = safe_join(Path("/workspace"), ".")
        assert result == Path("/workspace").resolve()

    def test_resolves_symlink_escapes(self, tmp_path):
        """If the user_path targets a symlink outside root, it's rejected."""
        from seekflow.security import safe_join

        root = tmp_path / "workspace"
        root.mkdir()
        (root / "allowed").mkdir()

        # Create a symlink inside workspace pointing outside
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret")

        link = root / "link"
        target = os.path.relpath(str(outside / "secret.txt"), str(root))
        try:
            link.symlink_to(target)
        except OSError:
            pytest.skip("symlink creation requires elevated privileges on this platform")

        with pytest.raises(PermissionError, match="outside workspace"):
            safe_join(root, "link")


class TestValidateFileAccess:
    """validate_file_access — workspace + extension + size validation."""

    def test_file_within_workspace_allowed(self, tmp_path):
        from seekflow.security import validate_file_access

        root = tmp_path / "ws"
        root.mkdir()
        f = root / "data.txt"
        f.write_text("hello")

        result = validate_file_access(f, workspace_root=root, allow_ext={".txt", ".md"})
        assert result == f.resolve()

    def test_file_outside_workspace_rejected(self, tmp_path):
        from seekflow.security import validate_file_access

        root = tmp_path / "ws"
        root.mkdir()
        outside = tmp_path / "outside.txt"
        outside.write_text("hi")

        with pytest.raises(PermissionError, match="outside workspace"):
            validate_file_access(outside, workspace_root=root)

    def test_env_extension_rejected_by_default_deny(self, tmp_path):
        from seekflow.security import validate_file_access

        root = tmp_path / "ws"
        root.mkdir()
        env_file = root / ".env"
        env_file.write_text("SECRET=123")

        with pytest.raises(PermissionError, match="blocked"):
            validate_file_access(env_file, workspace_root=root)

    def test_key_extension_rejected(self, tmp_path):
        from seekflow.security import validate_file_access

        root = tmp_path / "ws"
        root.mkdir()
        key_file = root / "id_rsa.key"
        key_file.write_text("PRIVATE KEY")

        with pytest.raises(PermissionError, match="blocked"):
            validate_file_access(key_file, workspace_root=root)

    def test_pem_extension_rejected(self, tmp_path):
        from seekflow.security import validate_file_access

        root = tmp_path / "ws"
        root.mkdir()
        pem_file = root / "cert.pem"
        pem_file.write_text("CERT")

        with pytest.raises(PermissionError, match="blocked"):
            validate_file_access(pem_file, workspace_root=root)

    def test_sqlite_extension_rejected(self, tmp_path):
        from seekflow.security import validate_file_access

        root = tmp_path / "ws"
        root.mkdir()
        db_file = root / "data.sqlite"
        db_file.write_text("sqlite format 3")

        with pytest.raises(PermissionError, match="blocked"):
            validate_file_access(db_file, workspace_root=root)

    def test_custom_allow_ext_overrides_deny(self, tmp_path):
        from seekflow.security import validate_file_access

        root = tmp_path / "ws"
        root.mkdir()
        log_file = root / "app.log"
        log_file.write_text("INFO: started")

        # By default .log is denied, custom allow overrides
        result = validate_file_access(log_file, workspace_root=root, allow_ext={".log", ".txt"})
        assert result == log_file.resolve()

    def test_file_too_large_rejected(self, tmp_path):
        from seekflow.security import validate_file_access

        root = tmp_path / "ws"
        root.mkdir()
        big_file = root / "big.txt"
        big_file.write_text("x" * 200)

        with pytest.raises(PermissionError, match="too large"):
            validate_file_access(big_file, workspace_root=root, max_bytes=100)

    def test_sensitive_filename_rejected(self, tmp_path):
        from seekflow.security import validate_file_access

        root = tmp_path / "ws"
        root.mkdir()
        secret = root / ".env"
        secret.write_text("KEY=val")

        # .env is a sensitive filename regardless of extension
        with pytest.raises(PermissionError):
            validate_file_access(secret, workspace_root=root)

    def test_nonexistent_file_rejected(self, tmp_path):
        from seekflow.security import validate_file_access

        root = tmp_path / "ws"
        root.mkdir()

        with pytest.raises(FileNotFoundError):
            validate_file_access(root / "nope.txt", workspace_root=root)


class TestValidateUrl:
    """SSRF protection — block private IPs, restricted schemes, domain allowlisting."""

    def test_public_https_url_allowed(self):
        from seekflow.security import validate_url

        assert validate_url("https://docs.deepseek.com/api") is True

    def test_public_http_url_allowed(self):
        from seekflow.security import validate_url

        assert validate_url("http://example.com/page") is True

    def test_localhost_blocked(self):
        from seekflow.security import validate_url

        assert validate_url("http://127.0.0.1:8080/admin") is False

    def test_localhost_hostname_blocked(self):
        from seekflow.security import validate_url

        assert validate_url("http://localhost/admin") is False

    def test_private_ip_10_blocked(self):
        from seekflow.security import validate_url

        assert validate_url("http://10.0.0.1/api") is False

    def test_private_ip_192_168_blocked(self):
        from seekflow.security import validate_url

        assert validate_url("http://192.168.1.1/admin") is False

    def test_private_ip_172_blocked(self):
        from seekflow.security import validate_url

        assert validate_url("http://172.16.0.1/api") is False

    def test_link_local_metadata_ip_blocked(self):
        from seekflow.security import validate_url

        assert validate_url("http://169.254.169.254/latest/meta-data/") is False

    def test_file_scheme_blocked(self):
        from seekflow.security import validate_url

        assert validate_url("file:///etc/passwd") is False

    def test_gopher_scheme_blocked(self):
        from seekflow.security import validate_url

        assert validate_url("gopher://localhost:25/") is False

    def test_ftp_scheme_blocked_by_default(self):
        from seekflow.security import validate_url

        assert validate_url("ftp://example.com/file") is False

    def test_domain_allowlist_blocks_non_allowed(self):
        from seekflow.security import validate_url

        assert validate_url("https://docs.deepseek.com", allow_domains={"example.com"}) is False

    def test_domain_allowlist_allows_matching(self):
        from seekflow.security import validate_url

        assert validate_url("https://example.com", allow_domains={"example.com"}) is True

    def test_custom_allowed_schemes(self):
        from seekflow.security import validate_url

        assert validate_url("ftp://example.com/file", allow_schemes={"https", "http", "ftp"}) is True


class TestRedactSecrets:
    """redact_secrets — remove API keys, tokens, passwords from text."""

    def test_deepseek_api_key_redacted(self):
        from seekflow.security import redact_secrets

        result = redact_secrets("Authorization: Bearer sk-abc123def456ghijklmnopqrstuvwxyz")
        assert "sk-[REDACTED]" in result
        assert "sk-abc123" not in result

    def test_bearer_token_redacted(self):
        from seekflow.security import redact_secrets

        result = redact_secrets("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456")
        assert "Bearer [REDACTED]" in result
        assert "abcdefghijklmnopqrstuvwxyz" not in result

    def test_api_key_assignment_redacted(self):
        from seekflow.security import redact_secrets

        result = redact_secrets('api_key = "my-super-secret-key-here-123"')
        assert "[REDACTED]" in result
        assert "my-super-secret-key-here-123" not in result

    def test_password_assignment_redacted(self):
        from seekflow.security import redact_secrets

        result = redact_secrets("password: hunter2000!")
        assert "[REDACTED]" in result
        assert "hunter2000" not in result

    def test_jwt_token_redacted(self):
        from seekflow.security import redact_secrets

        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4JqT"
        result = redact_secrets(f"token: {jwt}")
        # JWT content must be gone (either via JWT-specific or generic redaction)
        assert jwt not in result
        assert "REDACTED" in result

    def test_database_connection_string_redacted(self):
        from seekflow.security import redact_secrets

        result = redact_secrets("postgresql://user:password123@localhost:5432/db")
        assert "postgresql://[REDACTED]@localhost:5432/db" in result
        assert "password123" not in result

    def test_mysql_connection_string_redacted(self):
        from seekflow.security import redact_secrets

        result = redact_secrets("mysql://admin:secret@db.internal:3306/mydb")
        assert "mysql://[REDACTED]@db.internal:3306/mydb" in result

    def test_normal_text_passes_unchanged(self):
        from seekflow.security import redact_secrets

        text = "The weather today is sunny with a high of 25 degrees."
        assert redact_secrets(text) == text

    def test_empty_string_returns_empty(self):
        from seekflow.security import redact_secrets

        assert redact_secrets("") == ""

    def test_multiple_secrets_in_one_text(self):
        from seekflow.security import redact_secrets

        text = "key1=sk-abc123def456ghijklmnopqrstuvwx, key2=sk-zyx987wvutsrqponmlkjihgfedcba"
        result = redact_secrets(text)
        assert "sk-abc123" not in result
        assert "sk-zyx987" not in result
        assert result.count("[REDACTED]") >= 2


class TestUntrustedContent:
    """UntrustedContent wrapper for tool outputs."""

    def test_wrap_untrusted_produces_structured_output(self):
        from seekflow.security import wrap_untrusted

        result = wrap_untrusted("fetch_url", "<html>some page</html>", mime="text/html")
        assert result.source == "fetch_url"
        assert result.trusted is False
        assert result.mime == "text/html"
        assert "<html>some page</html>" in result.content

    def test_policy_note_present(self):
        from seekflow.security import wrap_untrusted

        result = wrap_untrusted("web_search", "search results here")
        assert "untrusted" in result.policy_note.lower()

    def test_wrapper_includes_provenance(self):
        from seekflow.security import wrap_untrusted

        prov = {"url": "https://example.com", "fetched_at": 1700000000.0}
        result = wrap_untrusted("fetch_url", "content", provenance=prov)
        assert result.provenance == prov
