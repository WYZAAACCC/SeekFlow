"""Tests for policy.py — Tool authorization and deny-by-default."""

from mini_agent_runtime.policy import ToolPolicy, authorize_tool_call


def test_missing_policy_denied_by_default():
    assert authorize_tool_call("unknown_tool", "network", {}) is False


def test_capability_must_match():
    policies = {
        "read_file": ToolPolicy(
            name="read_file",
            capabilities={"filesystem.read"},
            risk="read",
            trusted=True,
        )
    }
    assert authorize_tool_call("read_file", "filesystem.read", policies) is True
    assert authorize_tool_call("read_file", "network", policies) is False


def test_trusted_tool_still_needs_capability_match():
    policies = {
        "send_sms": ToolPolicy(
            name="send_sms",
            capabilities={"sendsms"},
            risk="write",
            trusted=True,
        )
    }
    assert authorize_tool_call("send_sms", "sendsms", policies) is True
    assert authorize_tool_call("send_sms", "filesystem.write", policies) is False


def test_multiple_tools_independent():
    policies = {
        "tool_a": ToolPolicy(
            name="tool_a", capabilities={"read"}, risk="read", trusted=True,
        ),
        "tool_b": ToolPolicy(
            name="tool_b", capabilities={"write"}, risk="write", trusted=False,
        ),
    }
    assert authorize_tool_call("tool_a", "read", policies) is True
    assert authorize_tool_call("tool_b", "write", policies) is True
    assert authorize_tool_call("tool_a", "write", policies) is False
