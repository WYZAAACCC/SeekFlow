"""
End-to-end integration test against real DeepSeek API.
Tests the complete pipeline: tool definition → tool loop → trace → eval.
"""
import json
import sys
import tempfile
from pathlib import Path

# Fix Windows GBK encoding for emoji/unicode output
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from deepseek_toolkit.tools.decorator import tool
from deepseek_toolkit.tools.registry import ToolRegistry
from deepseek_toolkit.tools.executor import ToolExecutor
from deepseek_toolkit.tools.strict import check_strict_compatibility
from deepseek_toolkit.repair.json_repair import repair_json_arguments
from deepseek_toolkit.repair.coercion import coerce_arguments
from deepseek_toolkit.client import DeepSeekClient
from deepseek_toolkit.runtime import ToolRuntime
from deepseek_toolkit.trace.recorder import TraceRecorder
from deepseek_toolkit.mcp.config import MCPServerConfig
from deepseek_toolkit.mcp.adapter import mcp_tool_to_deepseek_tool
from deepseek_toolkit.eval.types import EvalCase, ExpectedToolCall
from deepseek_toolkit.eval.runner import EvalRunner

API_KEY = open("apikey.txt").read().strip()


@tool
def get_weather(city: str, unit: str = "celsius") -> dict:
    """Get current weather for a given city."""
    weather_db = {
        "北京": {"temperature": 22, "condition": "多云", "humidity": 55},
        "上海": {"temperature": 28, "condition": "小雨", "humidity": 80},
        "杭州": {"temperature": 25, "condition": "晴", "humidity": 45},
    }
    info = weather_db.get(city, {"temperature": 20, "condition": "未知", "humidity": 60})
    return {"city": city, **info, "unit": unit}


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


def test1_tool_registry_and_schema():
    """Test 1: ToolRegistry exports valid DeepSeek schema."""
    print("=" * 60)
    print("TEST 1: ToolRegistry + Schema Export")
    registry = ToolRegistry()
    registry.register(get_weather)
    registry.register(add)
    registry.register(multiply)

    assert registry.has("get_weather")
    assert registry.has("add")
    assert len(registry.list()) == 3

    tools = registry.to_deepseek_tools(strict=False)
    assert len(tools) == 3
    for t in tools:
        assert t["type"] == "function"
        assert "name" in t["function"]
        assert "parameters" in t["function"]

    print(f"  PASS: {len(tools)} tools exported")
    print(f"  Tools: {[t['function']['name'] for t in tools]}")
    return registry


def test2_json_repair():
    """Test 2: JSON repair pipeline works."""
    print("\n" + "=" * 60)
    print("TEST 2: JSON Repair + Coercion")

    # Single quotes → double
    r = repair_json_arguments("{'city': '北京'}")
    assert r.ok
    assert r.value["city"] == "北京"
    print("  PASS: Single quotes → double quotes")

    # Trailing commas
    r = repair_json_arguments('{"a": 1, "b": 2,}')
    assert r.ok
    assert r.value == {"a": 1, "b": 2}
    print("  PASS: Trailing comma removal")

    # Markdown code block
    r = repair_json_arguments('```json\n{"city": "杭州"}\n```')
    assert r.ok
    assert r.value["city"] == "杭州"
    print("  PASS: Markdown code block stripping")

    # Type coercion
    schema = {"type": "object", "properties": {"count": {"type": "integer"}, "price": {"type": "number"}, "active": {"type": "boolean"}}}
    coerced, notes = coerce_arguments({"count": "42", "price": "19.9", "active": "true"}, schema)
    assert coerced == {"count": 42, "price": 19.9, "active": True}
    assert len(notes) == 3
    print(f"  PASS: Type coercion (str→int, str→float, str→bool)")


def test3_strict_check():
    """Test 3: Strict mode compatibility check."""
    print("\n" + "=" * 60)
    print("TEST 3: Strict Checker")

    valid = [{"type": "function", "function": {"name": "test", "description": "A test", "parameters": {"type": "object", "properties": {"x": {"type": "string"}}}}}]
    r = check_strict_compatibility(valid)
    assert r.ok
    print("  PASS: Valid schema passes strict check")

    # Missing parameters entirely = error-level issue
    problematic = [{"type": "function", "function": {"name": "bad", "description": "Test"}}]
    r = check_strict_compatibility(problematic)
    assert not r.ok
    print(f"  PASS: Problematic schema detected ({len(r.issues)} issues)")


def test4_tool_executor():
    """Test 4: ToolExecutor executes tools correctly."""
    print("\n" + "=" * 60)
    print("TEST 4: Tool Executor")

    registry = ToolRegistry()
    registry.register(add)
    executor = ToolExecutor(registry)

    from deepseek_toolkit.types import ToolCall
    result = executor.execute(ToolCall(id="c1", name="add", arguments={"a": 3, "b": 4}))
    assert result.ok
    assert result.result == 7
    print(f"  PASS: add(3, 4) = {result.result}, elapsed={result.elapsed_ms}ms")

    # Test with string arguments (simulating model output)
    result = executor.execute(ToolCall(id="c2", name="add", arguments='{"a": 10, "b": 20}'))
    assert result.ok
    assert result.result == 30
    print(f"  PASS: add('10', '20') via string args = {result.result}")


def test5_deepseek_client():
    """Test 5: DeepSeekClient sends real API call and parses response."""
    print("\n" + "=" * 60)
    print("TEST 5: DeepSeekClient (real API, non-tool)")

    client = DeepSeekClient(api_key=API_KEY)
    response = client.chat(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "Say 'hello' in JSON: {\"word\": \"hello\"}"}],
    )
    assert response.content is not None
    assert response.finish_reason in ("stop", "length")
    assert response.usage is not None
    print(f"  PASS: API responded in {response.usage.get('total_tokens', '?')} tokens")
    print(f"  Content preview: {response.content[:80]}...")


def test6_tool_calling_loop():
    """Test 6: Full tool calling loop with real API."""
    print("\n" + "=" * 60)
    print("TEST 6: Full Tool Calling Loop (real API)")

    runtime = ToolRuntime(
        tools=[get_weather],
        api_key=API_KEY,
        trace=True,
        max_steps=3,
    )

    result = runtime.chat(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "北京今天天气怎么样？"}],
    )

    assert result.final is not None
    assert len(result.messages) > 0
    print(f"  PASS: Tool loop completed")
    print(f"  Final response: {result.final[:120]}...")
    print(f"  Tool calls executed: {len(result.tool_results)}")
    for tr in result.tool_results:
        print(f"    - {tr.name}({tr.arguments}) → {tr.result}, ok={tr.ok}, elapsed={tr.elapsed_ms}ms")
    print(f"  Total messages: {len(result.messages)}")

    # Test trace
    assert result.trace is not None
    trace_dict = result.trace.to_dict()
    events = [e["type"] for e in trace_dict["events"]]
    print(f"  Trace events: {events}")

    # Save trace to file
    with tempfile.TemporaryDirectory() as tmp:
        trace_path = Path(tmp) / "trace.json"
        result.trace.save(str(trace_path))
        saved = json.loads(trace_path.read_text())
        assert saved["trace_id"] == trace_dict["trace_id"]
        print(f"  PASS: Trace saved and reloaded ({len(saved['events'])} events)")


def test7_multi_tool():
    """Test 7: Multiple tools with model choosing the right one."""
    print("\n" + "=" * 60)
    print("TEST 7: Multi-tool Selection (real API)")

    runtime = ToolRuntime(
        tools=[add, multiply, get_weather],
        api_key=API_KEY,
        trace=True,
        max_steps=2,
    )

    result = runtime.chat(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "请用工具计算 123 + 456"}],
    )

    print(f"  Final: {result.final[:120]}...")
    print(f"  Tools called: {len(result.tool_results)}")
    for tr in result.tool_results:
        print(f"    - {tr.name}({tr.arguments}) → {tr.result}")
    assert len(result.tool_results) > 0, "Expected at least one tool call"
    assert any(tr.name == "add" for tr in result.tool_results), f"Expected 'add' to be called, got: {[tr.name for tr in result.tool_results]}"
    print("  PASS: Model selected correct tool")


def test8_empty_tools():
    """Test 8: Empty tool list degrades to plain chat."""
    print("\n" + "=" * 60)
    print("TEST 8: Plain Chat (no tools)")

    runtime = ToolRuntime(api_key=API_KEY)
    result = runtime.chat(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "用一句话介绍Python"}],
    )
    assert result.final is not None
    assert len(result.tool_results) == 0
    print(f"  PASS: Plain chat works")
    print(f"  Response: {result.final[:100]}...")


def test9_mcp_config():
    """Test 9: MCP server config and tool conversion."""
    print("\n" + "=" * 60)
    print("TEST 9: MCP Config + Adapter")

    config = MCPServerConfig.stdio(
        name="fs",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "."],
    )
    assert config.name == "fs"
    assert config.transport == "stdio"
    params = config.to_stdio_params()
    assert params.command == "npx"
    print(f"  PASS: MCPServerConfig created")
    print(f"  Stdio params: {params.command} {params.args}")

    # Mock MCP tool → DeepSeek conversion
    from unittest.mock import MagicMock
    mock_tool = MagicMock()
    mock_tool.name = "read_file"
    mock_tool.description = "Read a file from disk"
    mock_tool.inputSchema = {"type": "object", "properties": {"path": {"type": "string"}}}
    ds_tool = mcp_tool_to_deepseek_tool("fs", mock_tool)
    assert ds_tool["function"]["name"] == "fs.read_file"
    print(f"  PASS: MCP tool → DeepSeek schema (name: {ds_tool['function']['name']})")


def test10_eval_framework():
    """Test 10: Eval framework with mock runtime."""
    print("\n" + "=" * 60)
    print("TEST 10: Eval Framework")

    from deepseek_toolkit.types import ToolRuntimeResult, ToolExecutionResult
    from unittest.mock import MagicMock

    runtime = MagicMock()
    runtime.chat.return_value = ToolRuntimeResult(
        final="The weather in Hangzhou is sunny, 25 degrees.",
        messages=[],
        tool_results=[
            ToolExecutionResult(
                tool_call_id="c1", name="get_weather",
                arguments={"city": "Hangzhou"}, ok=True,
                result={"temperature": 25}, elapsed_ms=500,
            ),
        ],
    )

    cases = [
        EvalCase(
            id="w1", input="What is the weather in Hangzhou?",
            expected_tools=[ExpectedToolCall(name="get_weather", arguments={"city": "Hangzhou"})],
            expected_final_contains=["Hangzhou", "sunny"],
        ),
    ]

    runner = EvalRunner(runtime, model="deepseek-chat")
    report = runner.run_cases(cases)

    assert report.metrics["total_cases"] == 1
    assert report.metrics["success_rate"] == 100.0
    assert report.metrics["tool_name_accuracy"] == 100.0
    print(f"  PASS: Eval report generated")
    print(f"  Metrics: {report.metrics}")
    report.print()


def main():
    print("\U0001f680 DeepSeek Toolkit -- End-to-End Integration Test")
    print(f"   API Key: {API_KEY[:12]}...")
    print()

    results = []

    # Local-only tests (no API needed)
    for test in [
        test1_tool_registry_and_schema,
        test2_json_repair,
        test3_strict_check,
        test4_tool_executor,
        test9_mcp_config,
        test10_eval_framework,
    ]:
        try:
            test()
            results.append((test.__name__, "PASS", None))
        except Exception as e:
            results.append((test.__name__, "FAIL", str(e)))

    # Real API tests
    for test in [
        test5_deepseek_client,
        test6_tool_calling_loop,
        test7_multi_tool,
        test8_empty_tools,
    ]:
        try:
            test()
            results.append((test.__name__, "PASS", None))
        except Exception as e:
            results.append((test.__name__, "FAIL", str(e)))
            print(f"  FAIL: {e}")

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    passed = sum(1 for _, status, _ in results if status == "PASS")
    failed = sum(1 for _, status, _ in results if status == "FAIL")
    for name, status, error in results:
        if status == "PASS":
            print(f"  ✅ {name}")
        else:
            print(f"  ❌ {name}: {error}")
    print(f"\n  {passed} passed, {failed} failed out of {len(results)} tests")

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
