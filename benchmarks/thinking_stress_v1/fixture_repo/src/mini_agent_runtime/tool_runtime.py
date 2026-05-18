"""Parallel tool execution runtime.

BUG: returns results in completion order, not original tool_calls order.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable


def execute_parallel_tool_calls(
    tool_calls: list[dict[str, Any]],
    registry: dict[str, Callable[..., Any]],
) -> list[dict[str, Any]]:
    """Execute tool calls concurrently.

    BUG:
    Returns results by completion order, causing unstable message ordering.
    """
    def run_one(call: dict[str, Any]) -> dict[str, Any]:
        name = call["function"]["name"]
        args = call["function"].get("arguments", {})
        if isinstance(args, str):
            import json
            args = json.loads(args)
        result = registry[name](**args)
        return {
            "tool_call_id": call["id"],
            "name": name,
            "content": result,
        }

    results = []
    with ThreadPoolExecutor(max_workers=min(8, len(tool_calls))) as pool:
        futures = [pool.submit(run_one, call) for call in tool_calls]
        for fut in as_completed(futures):
            results.append(fut.result())

    return results
