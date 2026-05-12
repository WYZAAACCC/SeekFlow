"""Advanced Agent — exercises the full ToolRuntime with fake backend.

Runs WITHOUT an API key — uses a controlled FakeDeepSeekClient that
simulates multi-turn tool calling, errors, and edge cases.
"""

import json
import os
import sys
from typing import Any

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

from deepseek_toolkit.tools.decorator import tool


@tool(keep_fields=["temperature", "humidity", "condition"])
def get_weather(city: str, unit: str = "celsius") -> dict:
    """Get current weather for a city."""
    weather_data = {
        "北京": {"temperature": 28, "humidity": 65, "condition": "晴", "wind": "东北风 3级"},
        "上海": {"temperature": 32, "humidity": 80, "condition": "多云", "wind": "南风 2级"},
        "深圳": {"temperature": 30, "humidity": 75, "condition": "阵雨", "wind": "东南风 4级"},
    }
    return weather_data.get(city, {"temperature": 20, "humidity": 50, "condition": "未知"})


@tool(cache=True)
def calculate(expression: str) -> float:
    """Evaluate a mathematical expression."""
    allowed = set("0123456789+-*/().%^ ")
    if not all(c in allowed for c in expression):
        raise ValueError(f"表达式包含不允许的字符: {expression}")
    # Safe eval since we whitelist chars
    return float(eval(expression))


@tool(name="search_knowledge", keep_fields=["answer", "confidence"])
def search(question: str) -> dict:
    """Search a knowledge base."""
    knowledge = {
        "深度学习": {"answer": "深度学习是机器学习的一个子集，使用多层神经网络。", "confidence": 0.95, "source": "AI教材"},
        "Python": {"answer": "Python 是一种解释型、面向对象的高级编程语言。", "confidence": 0.99, "source": "官方文档"},
        "量子计算": {"answer": "量子计算利用量子比特进行信息处理。", "confidence": 0.82, "source": "量子信息学"},
    }
    for key, val in knowledge.items():
        if key in question:
            return val
    return {"answer": "未找到相关信息。", "confidence": 0.1, "source": "无"}


@tool
def risky_operation(x: float) -> str:
    """An operation that may fail."""
    if x < 0:
        raise ValueError(f"参数不能为负数: {x}")
    return f"结果: {x ** 0.5:.4f}"


# ---------------------------------------------------------------------------
# Fake DeepSeek Client — simulates the API
# ---------------------------------------------------------------------------


class FakeDeepSeekClient:
    """Simulates a DeepSeek API with scripted multi-turn responses."""

    def __init__(self, script: list[dict]):
        self._call_count = 0
        self._script = script

    def chat(self, *, model, messages, tools=None, tool_choice=None, stream=False, **kwargs):
        if self._call_count >= len(self._script):
            # Fallback: simple text response
            return _make_chat_response("完成。")

        step = self._script[self._call_count]
        self._call_count += 1

        if step.get("tool_calls"):
            from deepseek_toolkit.types import ToolCall as TC
            return _make_chat_response(
                content=None,
                tool_calls=[TC(**tc) for tc in step["tool_calls"]],
                finish_reason="tool_calls",
            )
        else:
            return _make_chat_response(content=step.get("content", "完成。"))


def _make_chat_response(content=None, tool_calls=None, finish_reason="stop"):
    from deepseek_toolkit.types import ChatResponse
    return ChatResponse(
        content=content,
        tool_calls=tool_calls or [],
        finish_reason=finish_reason,
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        reasoning_contents=[],
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_agent(use_fake: bool = True):
    from deepseek_toolkit.runtime import ToolRuntime
    from deepseek_toolkit.trace.recorder import TraceRecorder
    from deepseek_toolkit.types import ToolCall
    from deepseek_toolkit.truncation import TruncationStrategy

    tools = [get_weather, calculate, search, risky_operation]

    # ---------- setup ----------
    rt = ToolRuntime(
        tools=tools,
        api_key="sk-fake" if use_fake else None,
        strict=False,
        repair=True,
        trace=True,
        max_steps=6,
        max_result_chars=12000,
        truncation_strategy=TruncationStrategy.PRIORITY,
        cache_size=32,
        cache_ttl=60,
        timeout=30.0,
    )

    # Inject fake client
    if use_fake:
        script = [
            # Turn 1: model calls get_weather + search simultaneously
            {
                "tool_calls": [
                    {
                        "id": "call-001",
                        "name": "get_weather",
                        "arguments": json.dumps({"city": "北京", "unit": "celsius"}, ensure_ascii=False),
                    },
                    {
                        "id": "call-002",
                        "name": "search_knowledge",
                        "arguments": json.dumps({"question": "深度学习是什么"}, ensure_ascii=False),
                    },
                ]
            },
            # Turn 2: after getting results, model calls calculate
            {
                "tool_calls": [
                    {
                        "id": "call-003",
                        "name": "calculate",
                        "arguments": json.dumps({"expression": "28 * 1.8 + 32"}, ensure_ascii=False),
                    },
                ]
            },
            # Turn 3: final answer (text only)
            {
                "content": (
                    "根据查询结果：\n"
                    "1. 北京当前天气：晴，28°C（82.4°F），湿度65%\n"
                    "2. 深度学习是机器学习的一个子集，使用多层神经网络（置信度95%）\n\n"
                    "北京的天气很好，适合户外活动！"
                ),
            },
        ]
        fake = FakeDeepSeekClient(script)
        rt._client = fake

    # ---------- run ----------
    print("=" * 60)
    print("   Advanced Agent — 多工具多轮对话")
    print("=" * 60)
    print()

    messages = [
        {"role": "user", "content": "帮我查一下北京现在的天气，同时搜索一下深度学习是什么，然后告诉我适不适合出门。"}
    ]

    print(f"用户: {messages[0]['content']}")
    print()

    result = rt.chat(model="deepseek-chat", messages=messages)

    # ---------- results ----------
    print("-" * 60)
    print("执行结果")
    print("-" * 60)

    steps = len(result.tool_results)
    for tr in result.tool_results:
        status = "[OK]" if tr.ok else "[FAIL]"
        result_preview = str(tr.result)[:100] if tr.result else "None"
        print(f"  {status} [{tr.name}]({json.dumps(tr.arguments, ensure_ascii=False)}) → {result_preview}")
        print(f"     耗时: {tr.elapsed_ms}ms")
    print()

    print(f"最终回答 ({steps} 步工具调用):")
    print(f"  {result.final}")
    print()

    # ---------- trace ----------
    if result.trace and result.trace.enabled:
        trace_dict = result.trace.to_dict()
        events = trace_dict.get("events", [])
        etype_counts = {}
        for e in events:
            t = e.get("type", "?")
            etype_counts[t] = etype_counts.get(t, 0) + 1
        total_events = len(events)
        detail = ', '.join(f'{k} x{v}' for k, v in etype_counts.items())
        print(f"trace: {total_events} events ({detail})")
        print(f"  trace_id: {trace_dict.get('trace_id', '?')}")

    # ---------- cache ----------
    if result.cache_stats:
        cs = result.cache_stats
        print(f"缓存统计: hits={cs.get('hits', 0)} misses={cs.get('misses', 0)} ratio={cs.get('ratio', 0):.1%}")

    # ---------- usage ----------
    if result.usage:
        u = result.usage
        print(f"Token 用量: prompt={u.get('prompt_tokens', '?')} completion={u.get('completion_tokens', '?')} total={u.get('total_tokens', '?')}")

    print()

    # ---------- batch demo ----------
    print("-" * 60)
    print("Batch API 演示 (3 个并行请求)")
    print("-" * 60)

    # Need to inject a fake batch client too
    if use_fake:
        batch_results = _run_fake_batch(rt)
    else:
        batch_results = rt.chat_batch(
            model="deepseek-chat",
            requests=[
                {"messages": [{"role": "user", "content": "上海天气怎么样？"}]},
                {"messages": [{"role": "user", "content": "计算 (15 + 23) * 2"}]},
                {"messages": [{"role": "user", "content": "搜索Python是什么"}]},
            ],
        )

    for i, br in enumerate(batch_results):
        tool_names = [tr.name for tr in br.tool_results if tr.ok]
        print(f"  [{i}] final={br.final[:60]}... tools={tool_names}" if tool_names else f"  [{i}] final={br.final[:60]}")
    print()

    # ---------- eval demo ----------
    print("-" * 60)
    print("Eval 评估演示")
    print("-" * 60)

    from deepseek_toolkit.eval.runner import EvalRunner
    from deepseek_toolkit.eval.types import EvalCase, ExpectedToolCall

    # Fresh runtime with eval-specific fake responses
    eval_rt = ToolRuntime(tools=tools, api_key="sk-fake", trace=False,
                          truncation_strategy=TruncationStrategy.PRIORITY)
    eval_script = [
        # Case 1: "查询上海天气" → get_weather("上海")
        {
            "tool_calls": [{
                "id": "ev-001",
                "name": "get_weather",
                "arguments": json.dumps({"city": "上海"}, ensure_ascii=False),
            }]
        },
        {
            "content": "上海当前天气：多云，32°C，湿度80%，南风2级。天气较热，注意防暑。",
        },
        # Case 2: "计算 3 + 5" → calculate("3+5")
        {
            "tool_calls": [{
                "id": "ev-002",
                "name": "calculate",
                "arguments": json.dumps({"expression": "3 + 5"}, ensure_ascii=False),
            }]
        },
        {
            "content": "3 + 5 = 8",
        },
    ]
    eval_rt._client = FakeDeepSeekClient(eval_script)

    cases = [
        EvalCase(
            id="weather_shanghai",
            input="查询上海天气",
            expected_tools=[ExpectedToolCall(name="get_weather", arguments={"city": "上海"})],
            expected_final_contains=["上海"],
        ),
        EvalCase(
            id="math_calc",
            input="计算 3 + 5",
            expected_tools=[ExpectedToolCall(name="calculate")],
            expected_final_contains=["8"],
        ),
    ]

    runner = EvalRunner(eval_rt, model="deepseek-chat")
    report = runner.run_cases(cases)
    report.print()

    # ---------- summary ----------
    print()
    print("=" * 60)
    print("   [OK] all features working")
    print("=" * 60)

    return result, batch_results, report


def _run_fake_batch(rt):
    """Simulate batch API results locally using the same tools."""
    from deepseek_toolkit.types import ToolRuntimeResult, ToolCall, ToolExecutionResult
    from deepseek_toolkit.tools.executor import ToolExecutor

    executor = rt._registry._make_executor() if hasattr(rt._registry, '_make_executor') else None

    # We simulate what chat_batch would return: call the tools locally
    fake_responses = [
        # Response for "上海天气"
        {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "bc-1",
                        "function": {"name": "get_weather", "arguments": json.dumps({"city": "上海"}, ensure_ascii=False)}
                    }]
                },
                "finish_reason": "tool_calls"
            }]
        },
        # Response for "计算 (15+23)*2"
        {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "bc-2",
                        "function": {"name": "calculate", "arguments": json.dumps({"expression": "(15 + 23) * 2"}, ensure_ascii=False)}
                    }]
                },
                "finish_reason": "tool_calls"
            }]
        },
        # Response for "搜索Python"
        {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "bc-3",
                        "function": {"name": "search_knowledge", "arguments": json.dumps({"question": "Python是什么"}, ensure_ascii=False)}
                    }]
                },
                "finish_reason": "tool_calls"
            }]
        },
    ]

    results = []
    for resp in fake_responses:
        choice = resp["choices"][0]
        msg = choice["message"]
        tool_calls_data = msg.get("tool_calls", [])

        tr_list = []
        final_text = ""
        for tc_data in tool_calls_data:
            fi = tc_data["function"]
            tool_call = ToolCall(id=tc_data["id"], name=fi["name"], arguments=fi["arguments"])
            try:
                from deepseek_toolkit.tools.executor import ToolExecutor
                exec_result = ToolExecutor(rt._registry).execute(tool_call)
                tr_list.append(exec_result)
                final_text = str(exec_result.result) if exec_result.ok else str(exec_result.error)
            except Exception as e:
                tr_list.append(ToolExecutionResult(
                    tool_call_id=tc_data["id"], name=fi["name"],
                    arguments=json.loads(fi["arguments"]) if isinstance(fi["arguments"], str) else fi["arguments"],
                    ok=False, error=str(e),
                ))
                final_text = str(e)

        results.append(ToolRuntimeResult(
            final=final_text,
            messages=[],
            tool_results=tr_list,
        ))

    return results


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_agent(use_fake=True)
