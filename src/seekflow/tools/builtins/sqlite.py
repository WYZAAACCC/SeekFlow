"""Safe SQLite tool factory — read-only, workspace-bound, authorizer-protected."""
from __future__ import annotations

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


def _authorizer(action, arg1, arg2, dbname, source):
    if action in ALLOWED_SQL_ACTIONS:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


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
        import json as _json

        # Validate path is inside workspace
        try:
            safe_path = safe_join(root, db_path)
        except PermissionError:
            return f"SQL query blocked: path '{db_path}' is outside workspace"

        # Only SELECT allowed
        stripped = query.strip().upper()
        if not stripped.startswith("SELECT"):
            return "SQL query blocked: only SELECT queries are permitted"
        if ";" in query.rstrip(";"):
            return "SQL query blocked: multiple statements not allowed"

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
            conn.close()

            if len(rows) > max_rows:
                rows = rows[:max_rows]
                return _json.dumps(rows, ensure_ascii=False, indent=2)[:8000] + "\n...[truncated]"

            return _json.dumps(rows, ensure_ascii=False, indent=2)[:8000]
        except Exception as e:
            return f"SQL query failed: {e}"

    return query_sql.with_policy(ToolPolicy(
        capabilities={"filesystem.read", "data.sqlite"},
        risk="read",
        workspace_root=root,
        timeout_s=timeout_s,
        parallel_safe=False,
    ))
