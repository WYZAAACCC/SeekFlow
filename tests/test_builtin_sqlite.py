"""Test SQLite execution security."""
import pytest
import sqlite3
from pathlib import Path
from seekflow.tools.builtins.sqlite import make_sqlite_query, _authorizer, ALLOWED_SQL_ACTIONS


def test_sqlite_authorizer_allows_select():
    assert _authorizer(sqlite3.SQLITE_SELECT, None, None, None, None) == sqlite3.SQLITE_OK


def test_sqlite_authorizer_denies_insert():
    assert _authorizer(sqlite3.SQLITE_INSERT, None, None, None, None) == sqlite3.SQLITE_DENY


def test_sqlite_authorizer_denies_update():
    assert _authorizer(sqlite3.SQLITE_UPDATE, None, None, None, None) == sqlite3.SQLITE_DENY


def test_sqlite_authorizer_denies_delete():
    assert _authorizer(sqlite3.SQLITE_DELETE, None, None, None, None) == sqlite3.SQLITE_DENY


def test_sqlite_authorizer_denies_create():
    assert _authorizer(sqlite3.SQLITE_CREATE_INDEX, None, None, None, None) == sqlite3.SQLITE_DENY
    assert _authorizer(sqlite3.SQLITE_CREATE_TABLE, None, None, None, None) == sqlite3.SQLITE_DENY


def test_sqlite_readonly_allows_select(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (a int)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()

    td = make_sqlite_query(workspace_root=tmp_path)
    result = td.func(str(db_path), "SELECT a FROM t")
    assert "1" in result


def test_sqlite_readonly_blocks_insert(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (a int)")
    conn.commit()
    conn.close()

    td = make_sqlite_query(workspace_root=tmp_path)
    result = td.func(str(db_path), "INSERT INTO t VALUES (1)")
    assert "blocked" in result.lower()


def test_sqlite_readonly_blocks_delete(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (a int)")
    conn.commit()
    conn.close()

    td = make_sqlite_query(workspace_root=tmp_path)
    result = td.func(str(db_path), "DELETE FROM t")
    assert "blocked" in result.lower()


def test_sqlite_blocks_path_traversal(tmp_path):
    td = make_sqlite_query(workspace_root=tmp_path)
    result = td.func("../outside.db", "SELECT 1")
    assert "blocked" in result.lower() or "outside" in result.lower()


def test_sqlite_has_path_params(tmp_path):
    td = make_sqlite_query(workspace_root=tmp_path)
    assert td.policy.path_params == frozenset({"db_path"})


def test_sqlite_limits_rows(tmp_path):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE t (a int)")
    for i in range(10):
        conn.execute("INSERT INTO t VALUES (?)", (i,))
    conn.commit()
    conn.close()

    td = make_sqlite_query(workspace_root=tmp_path, max_rows=3)
    result = td.func(str(db_path), "SELECT a FROM t")
    assert "truncated" in result.lower()
