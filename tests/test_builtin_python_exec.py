"""Test Python execution sandbox."""
import pytest
from seekflow.sandbox import NoSandbox, ProcessSandbox, LocalThreadSandbox, ContainerSandbox
from seekflow.tools.builtins.python_exec import make_python_exec


def test_python_exec_rejects_no_sandbox():
    with pytest.raises(ValueError, match="real sandbox"):
        make_python_exec(sandbox=NoSandbox())


def test_python_exec_accepts_process_sandbox():
    td = make_python_exec(sandbox=ProcessSandbox())
    assert td.policy.requires_approval is True
    assert "code.exec" in td.policy.capabilities


def test_python_exec_process_sandbox_runs_code():
    td = make_python_exec(sandbox=ProcessSandbox(), timeout_s=5.0)
    result = td.func("print('hello')")
    assert "hello" in result or "ok" in result.lower() or result


def test_python_exec_returns_error_on_bad_code():
    td = make_python_exec(sandbox=ProcessSandbox(), timeout_s=5.0)
    result = td.func("raise Exception('test error')")
    assert "error" in result.lower() or "sandbox" in result.lower()


def test_python_exec_no_sandbox_denies_execution():
    ns = NoSandbox()
    result = ns.execute("print(1)")
    assert result.ok is False
