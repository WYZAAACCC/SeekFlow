"""Tests for json_repair.py — Confidence-gated JSON repair."""

from mini_agent_runtime.json_repair import repair_tool_args


def test_native_json_passes_always():
    r = repair_tool_args('{"path": "README.md"}', dangerous=False)
    assert r.ok is True
    assert r.value == {"path": "README.md"}
    assert r.confidence == 1.0


def test_low_confidence_repair_allowed_for_safe_tool():
    r = repair_tool_args("{'path': 'README.md'}", dangerous=False)
    assert r.ok is True
    assert r.value == {"path": "README.md"}


def test_low_confidence_repair_denied_for_dangerous_tool():
    r = repair_tool_args("{'cmd': 'rm -rf /'}", dangerous=True)
    assert r.ok is False


def test_native_json_for_dangerous_tool():
    r = repair_tool_args('{"cmd": "safe_command"}', dangerous=True)
    assert r.ok is True
    assert r.confidence == 1.0


def test_completely_broken_json_fails():
    r = repair_tool_args("not even json at all {{{", dangerous=False)
    assert r.ok is False
    assert r.confidence == 0.0


def test_trailing_comma_in_object_repaired():
    r = repair_tool_args('{"a": 1,}', dangerous=False)
    assert r.ok is True
    assert r.value == {"a": 1}
