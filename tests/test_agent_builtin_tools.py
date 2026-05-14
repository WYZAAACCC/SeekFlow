"""Test safe built-in tool factories."""
import pytest
from pathlib import Path
from seekflow.tools.builtins.compute import make_calculate
from seekflow.tools.builtins.filesystem import make_read_file, make_write_file, make_list_dir
from seekflow.tools.builtins.network import make_fetch_url
from seekflow.tools.builtins.python_exec import make_python_exec
from seekflow.tools.builtins.sqlite import make_sqlite_query
from seekflow.sandbox import NoSandbox, ProcessSandbox


def test_tools_builtins_module_imports():
    import seekflow.tools.builtins


def test_make_calculate_has_policy():
    td = make_calculate()
    assert td.name == "calculate"
    assert td.policy is not None
    assert "compute.basic" in td.policy.capabilities
    assert td.policy.risk == "read"
    assert td.policy.parallel_safe is True


def test_make_calculate_evaluates():
    td = make_calculate()
    result = td.func("2 + 3 * 4")
    assert "14" in result


def test_make_calculate_blocks_dangerous():
    td = make_calculate()
    result = td.func("__import__('os').system('ls')")
    assert "error" in result.lower() or "not an allowed" in result.lower()


def test_make_list_dir_has_policy(tmp_path):
    td = make_list_dir(workspace_root=tmp_path)
    assert td.policy is not None
    assert "filesystem.read" in td.policy.capabilities
    assert td.policy.path_params == frozenset({"path"})
    assert td.policy.workspace_root == tmp_path.resolve()


def test_make_list_dir_lists_files(tmp_path):
    (tmp_path / "a.txt").write_text("hello")
    (tmp_path / "b.txt").write_text("world")
    td = make_list_dir(workspace_root=tmp_path)
    result = td.func(".")
    assert "a.txt" in result
    assert "b.txt" in result


def test_make_read_file_has_policy(tmp_path):
    td = make_read_file(workspace_root=tmp_path)
    assert td.policy is not None
    assert "filesystem.read" in td.policy.capabilities
    assert td.policy.path_params == frozenset({"path"})


def test_make_read_file_reads(tmp_path):
    (tmp_path / "test.txt").write_text("hello world")
    td = make_read_file(workspace_root=tmp_path)
    result = td.func("test.txt")
    assert "hello world" in result


def test_allow_network_requires_domains():
    with pytest.raises(TypeError):
        make_fetch_url()  # requires allowed_domains


def test_allow_python_rejects_no_sandbox():
    with pytest.raises(ValueError, match="real sandbox"):
        make_python_exec(sandbox=NoSandbox())


def test_builtin_tool_policies_present(tmp_path):
    td = make_read_file(workspace_root=tmp_path)
    assert td.policy is not None
    assert "filesystem.read" in td.policy.capabilities


def test_write_file_has_approval(tmp_path):
    td = make_write_file(workspace_root=tmp_path)
    assert td.policy.requires_approval is True
    assert td.policy.risk == "write"


def test_fetch_url_has_domain_policy():
    td = make_fetch_url(allowed_domains={"api.example.com"})
    assert "api.example.com" in td.policy.allowed_domains
    assert td.policy.url_params == frozenset({"url"})


def test_sqlite_has_path_params(tmp_path):
    td = make_sqlite_query(workspace_root=tmp_path)
    assert td.policy.path_params == frozenset({"db_path"})


def test_python_exec_requires_approval():
    td = make_python_exec(sandbox=ProcessSandbox())
    assert td.policy.requires_approval is True
    assert "code.exec" in td.policy.capabilities
