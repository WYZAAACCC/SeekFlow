"""Safe SQLite tool factory — read-only, workspace-bound, authorizer-protected."""
from __future__ import annotations

import json as _json
import sqlite3
import time
from pathlib import Path

from seekflow.security import safe_join
from seekflow.tools.decorator import tool
from seekflow.types import ToolPolicy

ALLOWED_SQL_ACTIONS = frozenset({
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
})

# Token-based forbidden keywords (coarse first line, authorizer is second line)
FORBIDDEN_SQL_TOKENS: frozenset[str] = frozenset({
    "ATTACH", "DETACH", "INSERT", "UPDATE", "DELETE",
    "DROP", "ALTER", "CREATE", "REPLACE", "VACUUM",
})

# Safe PRAGMA patterns
ALLOWED_PRAGMA_PREFIXES: tuple[str, ...] = (
    "PRAGMA TABLE_INFO",
    "PRAGMA INDEX_LIST",
    "PRAGMA TABLE_LIST",
    "PRAGMA JOURNAL_MODE",
    "PRAGMA PAGE_SIZE",
    "PRAGMA PAGE_COUNT",
    "PRAGMA SCHEMA_VERSION",
    "PRAGMA USER_VERSION",
    "PRAGMA FOREIGN_KEY_LIST",
    "PRAGMA INDEX_INFO",
)


def _authorizer(action, arg1, arg2, dbname, source):
    if action in ALLOWED_SQL_ACTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def _validate_sql_tokens(query: str) -> str | None:
    """Coarse tokenizer check. Returns error message or None if allowed."""
    upper = query.upper()
    tokens = upper.replace("(", " ( ").replace(")", " ) ").replace(",", " ").split()
    for token in tokens:
        if token in FORBIDDEN_SQL_TOKENS:
            return f"SQL query blocked: '{token}' statements are not permitted"
    return None


def _is_allowed_sql(query: str) -> str | None:
    """Check if a SQL query is allowed. Returns None if allowed, error message if not."""
    stripped = query.strip()
    upper = stripped.upper()

    # Allow SELECT or WITH ... SELECT
    if upper.startswith("SELECT"):
        pass
    elif upper.startswith("WITH") and "SELECT" in upper:
        pass
    elif any(upper.startswith(p) for p in ALLOWED_PRAGMA_PREFIXES):
        pass
    else:
        return "SQL query blocked: only SELECT, WITH...SELECT, and safe PRAGMA queries are permitted"

    # Block multiple statements
    if ";" in stripped.rstrip(";"):
        return "SQL query blocked: multiple statements not allowed"

    # Tokenizer check
    err = _validate_sql_tokens(stripped)
    if err:
        return err

    return None


def make_sqlite_query(
    *,
    workspace_root: str | Path,
    max_rows: int = 1000,
    timeout_s: float = 2.0,
) -> "ToolDefinition":
    """Create a read-only, workspace-bound SQLite query tool."""
    root = Path(workspace_root).resolve()

    @tool(trusted=False)
    def query_sql(db_path: str, query: str) -> str:
        # Validate path is inside workspace
        try:
            safe_path = safe_join(root, db_path)
        except PermissionError:
            return f"SQL query blocked: path '{db_path}' is outside workspace"

        # Validate query
        err = _is_allowed_sql(query)
        if err:
            return err

        conn = None
        try:
            uri = f"file:{safe_path.as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=timeout_s)
            conn.set_authorizer(_authorizer)

            deadline = time.monotonic() + timeout_s

            def progress():
                if time.monotonic() > deadline:
                    return 1
                return 0

            conn.set_progress_handler(progress, 1000)
            cur = conn.execute(query)
            rows = [
                dict(zip([c[0] for c in cur.description], row))
                for row in cur.fetchmany(max_rows + 1)
            ]

            if len(rows) > max_rows:
                rows = rows[:max_rows]
                return _json.dumps(rows, ensure_ascii=False, indent=2)[:8000] + "\n...[truncated]"

            return _json.dumps(rows, ensure_ascii=False, indent=2)[:8000]
        except Exception as e:
            return f"SQL query failed: {e}"
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    return query_sql.with_policy(ToolPolicy(
        capabilities={"filesystem.read", "data.sqlite"},
        risk="read",
        workspace_root=root,
        path_params=frozenset({"db_path"}),
        timeout_s=timeout_s,
        max_input_bytes=100_000,
        max_output_bytes=1_000_000,
        parallel_safe=False,
    ))
