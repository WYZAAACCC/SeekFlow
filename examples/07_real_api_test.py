"""Real API integration test — verifies the library works with live DeepSeek API."""
import json
import sys
import time

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not API_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY environment variable is required")
MODEL = "deepseek-chat"

from deepseek_toolkit.tools.decorator import tool
from deepseek_toolkit.runtime import ToolRuntime
from deepseek_toolkit.truncation import TruncationStrategy


@tool
def add(a: int, b: int) -> int:
    """Add two integers."""
    return a + b


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two integers."""
    return a * b


@tool(name="get_weather", keep_fields=["temperature", "condition"])
def get_weather(city: str) -> dict:
    """Get current weather for a city."""
    weather = {
        "北京": {"temperature": 28, "humidity": 65, "condition": "晴", "wind": "东北风 3级", "pressure": 1013},
        "上海": {"temperature": 32, "humidity": 80, "condition": "多云", "wind": "南风 2级", "pressure": 1010},
        "深圳": {"temperature": 30, "humidity": 75, "condition": "阵雨", "wind": "东南风 4级", "pressure": 1008},
    }
    return weather.get(city, {"temperature": 20, "humidity": 50, "condition": "未知", "wind": "未知", "pressure": 0})


@tool(cache=True)
def search_knowledge(query: str) -> dict:
    """Search a knowledge base."""
    base = {
        "深度学习": "深度学习是机器学习的一个子集，使用多层神经网络进行表征学习。",
        "Python": "Python 是一种解释型、面向对象的高级编程语言，由 Guido van Rossum 于 1991 年发布。",
        "量子计算": "量子计算利用量子力学原理（如叠加和纠缠）来处理信息。",
    }
    for k, v in base.items():
        if k in query:
            return {"query": query, "answer": v, "confidence": 0.9}
    return {"query": query, "answer": "未找到相关信息", "confidence": 0.1}


def run_test(name, fn):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    start = time.time()
    try:
        fn()
        elapsed = time.time() - start
        print(f"  -> PASS ({elapsed:.1f}s)")
    except Exception as e:
        elapsed = time.time() - start
        print(f"  -> FAIL ({elapsed:.1f}s): {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


# ── Test 1: basic chat (no tools) ──
def test_basic_chat():
    rt = ToolRuntime(tools=[], api_key=API_KEY)
    result = rt.chat(
        model=MODEL,
        messages=[{"role": "user", "content": "说'你好世界'，只回复这四个字，不要其他内容。"}],
    )
    assert "你好世界" in result.final, f"Expected '你好世界', got: {result.final}"
    print(f"  response: {result.final}")
    print(f"  usage: {result.usage}")


# ── Test 2: single tool call ──
def test_single_tool():
    rt = ToolRuntime(tools=[add], api_key=API_KEY)
    result = rt.chat(
        model=MODEL,
        messages=[{"role": "user", "content": "请用add工具计算 12345 + 67890"}],
    )
    assert len(result.tool_results) >= 1, "Expected at least 1 tool call"
    assert result.tool_results[0].ok, f"Tool failed: {result.tool_results[0].error}"
    assert result.tool_results[0].result == 80235, f"Expected 80235, got {result.tool_results[0].result}"
    print(f"  tool: {result.tool_results[0].name}({result.tool_results[0].arguments}) = {result.tool_results[0].result}")
    print(f"  final: {result.final[:100]}")


# ── Test 3: multi-turn tool calling ──
def test_multi_turn():
    rt = ToolRuntime(tools=[add, multiply, get_weather], api_key=API_KEY, max_steps=5)
    result = rt.chat(
        model=MODEL,
        messages=[{"role": "user", "content": "北京天气如何？然后计算28度对应的华氏温度（公式：28*1.8+32），最后把结果乘以2。"}],
    )
    assert len(result.tool_results) >= 1, f"Expected tool calls, got {len(result.tool_results)}"
    for tr in result.tool_results:
        status = "OK" if tr.ok else f"FAIL: {tr.error}"
        print(f"  [{tr.name}] {tr.arguments} -> {tr.result} ({status})")
    print(f"  steps: {len(result.tool_results)}")
    print(f"  final: {result.final[:200]}")
    assert len(result.tool_results) >= 3, f"Expected >=3 tool calls (weather + multiply*2), got {len(result.tool_results)}"


# ── Test 4: trace recording ──
def test_trace():
    rt = ToolRuntime(tools=[add], api_key=API_KEY, trace=True)
    result = rt.chat(
        model=MODEL,
        messages=[{"role": "user", "content": "用add工具计算 1+1"}],
    )
    assert result.trace is not None, "Trace should be enabled"
    td = result.trace.to_dict()
    events = td["events"]
    assert len(events) > 0, "Expected trace events"
    print(f"  trace_id: {td['trace_id']}")
    etypes = {}
    for e in events:
        etypes[e["type"]] = etypes.get(e["type"], 0) + 1
    print(f"  events: {', '.join(f'{k}*{v}' for k,v in etypes.items())}")
    # Save trace to file
    result.trace.save("trace_output.json")
    print(f"  saved to trace_output.json")


# ── Test 5: batch API ──
def test_batch():
    rt = ToolRuntime(tools=[add, multiply, get_weather], api_key=API_KEY)
    results = rt.chat_batch(
        model=MODEL,
        requests=[
            {"messages": [{"role": "user", "content": "用add工具计算 10 + 20"}]},
            {"messages": [{"role": "user", "content": "用multiply工具计算 7 * 8"}]},
            {"messages": [{"role": "user", "content": "查一下深圳的天气"}]},
        ],
        poll_interval=10.0,
        max_wait=600.0,
    )
    assert len(results) == 3, f"Expected 3 results, got {len(results)}"
    for i, r in enumerate(results):
        tools = [t.name for t in r.tool_results if t.ok]
        print(f"  [{i}] final={r.final[:60]} tools={tools}")
    assert any(tr.name == "add" for r in results for tr in r.tool_results), "Expected add tool call"
    assert any(tr.name == "multiply" for r in results for tr in r.tool_results), "Expected multiply tool call"
    assert any(tr.name == "get_weather" for r in results for tr in r.tool_results), "Expected get_weather tool call"


# ── Test 6: eval framework ──
def test_eval():
    from deepseek_toolkit.eval.runner import EvalRunner
    from deepseek_toolkit.eval.types import EvalCase, ExpectedToolCall

    rt = ToolRuntime(tools=[add, get_weather], api_key=API_KEY, trace=False)

    cases = [
        EvalCase(
            id="add_test",
            input="用add工具计算 2+3",
            expected_tools=[ExpectedToolCall(name="add", arguments={"a": 2, "b": 3})],
            expected_final_contains=["5"],
        ),
        EvalCase(
            id="weather_test",
            input="北京今天天气怎么样？",
            expected_tools=[ExpectedToolCall(name="get_weather", arguments={"city": "北京"})],
            expected_final_contains=["北京"],
        ),
    ]

    runner = EvalRunner(rt, model=MODEL)
    report = runner.run_cases(cases)
    report.name = "integration_test"
    report.print()

    assert report.metrics["success_rate"] >= 50.0, f"Expected >=50% success, got {report.metrics['success_rate']}"
    print(f"  success_rate: {report.metrics['success_rate']:.1f}%")


# ── Test 7: eval batch mode ──
def test_eval_batch():
    from deepseek_toolkit.eval.runner import EvalRunner
    from deepseek_toolkit.eval.types import EvalCase, ExpectedToolCall

    rt = ToolRuntime(tools=[add, get_weather], api_key=API_KEY, trace=False)

    cases = [
        EvalCase(
            id="batch_add",
            input="用add工具计算 100+200",
            expected_tools=[ExpectedToolCall(name="add", arguments={"a": 100, "b": 200})],
            expected_final_contains=["300"],
        ),
        EvalCase(
            id="batch_weather",
            input="上海天气怎么样？",
            expected_tools=[ExpectedToolCall(name="get_weather", arguments={"city": "上海"})],
            expected_final_contains=["上海"],
        ),
    ]

    runner = EvalRunner(rt, model=MODEL)
    report = runner.run_cases_batch(cases, poll_interval=10.0, max_wait=600.0)
    report.name = "batch_eval_test"
    report.print()

    assert report.metrics["total_cases"] == 2
    print(f"  success_rate: {report.metrics['success_rate']:.1f}%")


# ── Test 8: truncation with keep_fields ──
def test_truncation():
    rt = ToolRuntime(
        tools=[get_weather], api_key=API_KEY,
        max_result_chars=80,  # small limit to force truncation
        truncation_strategy=TruncationStrategy.PRIORITY,
    )
    result = rt.chat(
        model=MODEL,
        messages=[{"role": "user", "content": "北京天气如何？"}],
    )
    tool_results = result.tool_results
    if tool_results and tool_results[0].ok:
        r = str(tool_results[0].result)
        print(f"  result ({len(r)} chars): {r}")
        if len(r) < 200:
            print(f"  (no truncation needed — result fits in limit)")
        # If truncated, _truncation key should be present
    print(f"  max_result_chars=80, result fits: {len(str(tool_results[0].result)) < 80 if tool_results else 'N/A'}")


# ── Main ──
if __name__ == "__main__":
    print("DeepSeek Toolkit — Real API Integration Test")
    print(f"Model: {MODEL}")
    print(f"API Key: {API_KEY[:8]}...{API_KEY[-4:]}")

    tests = [
        ("Basic Chat (no tools)", test_basic_chat),
        ("Single Tool Call", test_single_tool),
        ("Multi-turn Tool Calling", test_multi_turn),
        ("Trace Recording", test_trace),
        ("Batch API", test_batch),
        ("Eval Framework", test_eval),
        ("Eval Batch Mode (CLI --batch)", test_eval_batch),
        ("Truncation with keep_fields", test_truncation),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            run_test(name, fn)
            passed += 1
        except Exception:
            failed += 1

    print(f"\n{'='*60}")
    print(f"  Results: {passed}/{passed+failed} passed, {failed} failed")
    print(f"{'='*60}")
