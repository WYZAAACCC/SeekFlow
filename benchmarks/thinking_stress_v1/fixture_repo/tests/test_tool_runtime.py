"""Tests for tool_runtime.py — Parallel execution ordering."""

import time

from mini_agent_runtime.tool_runtime import execute_parallel_tool_calls


def test_parallel_results_preserve_tool_call_order():
    def slow(value: str, delay: float):
        time.sleep(delay)
        return value

    calls = [
        {"id": "call_a", "function": {"name": "slow", "arguments": {"value": "A", "delay": 0.05}}},
        {"id": "call_b", "function": {"name": "slow", "arguments": {"value": "B", "delay": 0.01}}},
        {"id": "call_c", "function": {"name": "slow", "arguments": {"value": "C", "delay": 0.02}}},
    ]

    out = execute_parallel_tool_calls(calls, {"slow": slow})

    assert [x["tool_call_id"] for x in out] == ["call_a", "call_b", "call_c"]
    assert [x["content"] for x in out] == ["A", "B", "C"]


def test_parallel_execution_is_faster_than_serial():
    """The parallel executor should be faster than serial sum of delays."""
    def slow(value: str, delay: float):
        time.sleep(delay)
        return value

    calls = [
        {"id": "call_1", "function": {"name": "slow", "arguments": {"value": "X", "delay": 0.05}}},
        {"id": "call_2", "function": {"name": "slow", "arguments": {"value": "Y", "delay": 0.05}}},
        {"id": "call_3", "function": {"name": "slow", "arguments": {"value": "Z", "delay": 0.05}}},
    ]

    start = time.perf_counter()
    out = execute_parallel_tool_calls(calls, {"slow": slow})
    elapsed = time.perf_counter() - start

    # Parallel of 0.05s each should finish well under 0.12s
    # (serial would be ~0.15s+)
    assert len(out) == 3
    assert elapsed < 0.12, f"Execution took {elapsed:.3f}s — not parallel enough"


def test_single_tool_call_works():
    def identity(value: str):
        return value

    calls = [
        {"id": "only_call", "function": {"name": "identity", "arguments": {"value": "hello"}}},
    ]
    out = execute_parallel_tool_calls(calls, {"identity": identity})
    assert out[0]["tool_call_id"] == "only_call"
    assert out[0]["content"] == "hello"
