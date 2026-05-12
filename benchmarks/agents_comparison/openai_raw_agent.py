"""Raw OpenAI SDK agent — minimal implementation WITHOUT DeepSeekToolkit.

This agent implements the same 4 agent types using only the openai library.
No DeepSeekToolkit features are used: no balance query, no cost tracking,
no cache, no rate limit awareness, no session management, no trace recording,
no JSON repair, no retry/circuit breaker, no context management, no token
counter, no error classification, no structured output helpers.

Purpose: show what you'd have to build yourself without DeepSeekToolkit.
"""
import json
import sys
import io
import time
import re
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Any

# Fix Windows GBK encoding issues with Unicode characters
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from dataclasses import dataclass, field
from collections.abc import Iterator

from openai import OpenAI

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not API_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY environment variable is required")
MODEL = "deepseek-v4-pro"

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "output" / "openai_raw"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Minimal tool definitions — raw dicts (no @tool decorator, no ToolRegistry)
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the data directory. Supports txt, csv, json, md, pdf.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to data directory"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a mathematical expression and return the result.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Math expression to evaluate"},
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_result",
            "description": "Save analysis result to output directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Output filename"},
                    "content": {"type": "string", "description": "Content to save"},
                },
                "required": ["filename", "content"],
            },
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Tool implementations — raw functions (no @tool decorator)
# ═══════════════════════════════════════════════════════════════════════════════

def _read_file(path: str) -> str:
    full = DATA_DIR / path
    if not full.exists():
        return f"ERROR: File not found: {path}. Available: {[p.name for p in DATA_DIR.iterdir()]}"
    try:
        content = full.read_text(encoding="utf-8")
    except Exception:
        content = full.read_bytes().decode("utf-8", errors="replace")
    if len(content) > 4000:
        content = content[:4000] + f"\n... [truncated, total {len(content)} chars]"
    return content


def _web_search(query: str) -> str:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(url, headers={"User-Agent": "RawOpenAI/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
        results = []
        for s in snippets[:5]:
            text = re.sub(r'<[^>]+>', '', s).strip()
            if text:
                results.append(text)
        return "\n".join(f"{i+1}. {r}" for i, r in enumerate(results)) if results else "No results."
    except Exception as e:
        return f"Search failed: {e}"


def _calculate(expression: str) -> str:
    try:
        result = eval(expression, {"__builtins__": {}}, {
            "abs": abs, "round": round, "min": min, "max": max,
            "sum": sum, "pow": pow,
        })
        return f"Result: {result}"
    except Exception as e:
        return f"Calculation error: {e}"


def _save_result(filename: str, content: str) -> str:
    full = OUTPUT_DIR / filename
    full.write_text(content, encoding="utf-8")
    return f"Saved {len(content)} bytes to {filename}"


TOOL_FUNCTIONS = {
    "read_file": _read_file,
    "web_search": _web_search,
    "calculate": _calculate,
    "save_result": _save_result,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Report
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RawAgentReport:
    agent_type: str
    framework: str = "OpenAI-Raw"
    task: str = ""
    final_output: str = ""
    tool_calls: list = field(default_factory=list)
    steps: int = 0
    latency_ms: float = 0
    tokens: dict = field(default_factory=dict)
    cost: float = 0.0
    errors: list = field(default_factory=list)
    features_exercised: list = field(default_factory=lambda: ["manual_tool_loop"])

    # These features are NOT available in raw OpenAI SDK:
    missing_features: list = field(default_factory=lambda: [
        "balance_query", "cost_tracking", "prompt_cache", "rate_limit_awareness",
        "session_management", "token_counter", "error_classification",
        "trace_recording", "session_persistence", "json_repair",
        "retry_executor", "circuit_breaker", "context_management",
        "structured_output", "thinking_mode_param", "response_format_param",
        "strict_tools", "truncation_strategy", "tool_cache",
    ])


# ═══════════════════════════════════════════════════════════════════════════════
# Manual tool calling loop — everything ToolRuntime does, but by hand
# ═══════════════════════════════════════════════════════════════════════════════

PRICING = {
    "deepseek-v4-pro": {"input": 1.74, "output": 3.48, "cached_input": 0.028},
    "deepseek-v4-flash": {"input": 0.14, "output": 0.28, "cached_input": 0.002},
}


def _estimate_cost(model: str, usage: dict) -> float:
    """Manual cost estimation (no CostTracker)."""
    pricing = PRICING.get(model, PRICING["deepseek-v4-pro"])
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    cached = (usage.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0)
    fresh_prompt = prompt_tokens - cached
    cost = (
        fresh_prompt * pricing["input"] +
        cached * pricing["cached_input"] +
        completion_tokens * pricing["output"]
    ) / 1_000_000
    return cost


def run_raw_agent(agent_type: str, streaming: bool = True) -> RawAgentReport:
    """Run an agent using raw OpenAI SDK — no DeepSeekToolkit at all."""
    report = RawAgentReport(agent_type=agent_type)
    report.task = _get_task(agent_type)

    system_prompt = _build_system_prompt(agent_type)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": report.task},
    ]

    client = OpenAI(
        api_key=API_KEY,
        base_url="https://api.deepseek.com",
        timeout=120.0,
    )

    print(f"\n{'='*70}")
    print(f"  [{report.framework}] {agent_type.upper()} AGENT")
    print(f"  Model: {MODEL} | No toolkit features — raw API calls only")
    print(f"{'='*70}")
    print(f"\nTask: {report.task[:100]}...\n")

    start = time.time()
    total_usage = {}
    final_text = ""
    tool_calls_log = []

    try:
        if streaming:
            final_text = _run_streaming_loop(client, messages, report, start, total_usage, tool_calls_log)
        else:
            final_text = _run_sync_loop(client, messages, report, start, total_usage, tool_calls_log)
    except Exception as e:
        report.errors.append(f"{type(e).__name__}: {e}")
        final_text = f"ERROR: {e}"

    report.latency_ms = (time.time() - start) * 1000
    report.final_output = final_text or ""
    report.tokens = total_usage
    if total_usage:
        report.cost = _estimate_cost(MODEL, total_usage)

    print(f"\n{'─'*70}")
    print(f"  Latency: {report.latency_ms:.0f}ms | Cost: CNY{report.cost:.6f}")
    print(f"  Missing features: {len(report.missing_features)} DeepSeekToolkit features unavailable")
    if report.errors:
        print(f"  Errors: {report.errors}")
    print(f"{'─'*70}")

    return report


def _run_sync_loop(
    client: OpenAI, messages: list[dict], report: RawAgentReport,
    start: float, total_usage: dict, tool_calls_log: list,
) -> str:
    """Manual synchronous tool calling loop."""
    max_steps = 8
    working = list(messages)

    for step in range(max_steps):
        response = client.chat.completions.create(
            model=MODEL,
            messages=working,
            tools=TOOLS_SCHEMA,
            extra_body={"thinking": {"type": "enabled"}},
        )
        choice = response.choices[0]
        msg = choice.message

        # Accumulate usage
        if response.usage:
            u = response.usage.model_dump() if hasattr(response.usage, 'model_dump') else dict(response.usage)
            total_usage["prompt_tokens"] = total_usage.get("prompt_tokens", 0) + u.get("prompt_tokens", 0)
            total_usage["completion_tokens"] = total_usage.get("completion_tokens", 0) + u.get("completion_tokens", 0)
            total_usage["total_tokens"] = total_usage.get("total_tokens", 0) + u.get("total_tokens", 0)

        if not msg.tool_calls:
            # Done
            final = msg.content or ""
            print(final)
            return final

        # Execute tool calls
        tool_calls_log.append(len(msg.tool_calls))
        report.steps += 1

        # Build assistant message
        assistant_msg: dict[str, Any] = {"role": "assistant", "content": msg.content}
        tc_list = []
        for tc in msg.tool_calls:
            tc_list.append({
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            })
        assistant_msg["tool_calls"] = tc_list
        working.append(assistant_msg)

        # Execute each tool
        for tc in msg.tool_calls:
            name = tc.function.name
            args_str = tc.function.arguments
            try:
                args = json.loads(args_str)
            except json.JSONDecodeError:
                # No JSON repair — just try with empty args
                args = {}

            fn = TOOL_FUNCTIONS.get(name)
            if fn:
                try:
                    result = fn(**args)
                except Exception as e:
                    result = f"Tool error: {e}"
            else:
                result = f"Unknown tool: {name}"

            print(f"  [tool] {name} -> {str(result)[:100]}")

            report.tool_calls.append({
                "name": name,
                "ok": not isinstance(result, str) or not result.startswith("Tool error"),
                "result": str(result)[:100],
            })

            working.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result,
            })

    return "Max steps reached"


def _run_streaming_loop(
    client: OpenAI, messages: list[dict], report: RawAgentReport,
    start: float, total_usage: dict, tool_calls_log: list,
) -> str:
    """Manual streaming tool calling loop."""
    max_steps = 8
    working = list(messages)
    accumulated: list[str] = []

    for step in range(max_steps):
        stream = client.chat.completions.create(
            model=MODEL,
            messages=working,
            tools=TOOLS_SCHEMA,
            stream=True,
            extra_body={"thinking": {"type": "enabled"}},
        )

        # Accumulate streaming chunks
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_call_buffers: dict[int, dict] = {}  # index -> {id, name, arguments}

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # Reasoning content
            if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                reasoning_parts.append(delta.reasoning_content)
                print(f"\033[2m{delta.reasoning_content[:80]}...\033[0m", end="", flush=True)

            # Content
            if delta.content:
                content_parts.append(delta.content)
                print(delta.content, end="", flush=True)

            # Tool calls
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_call_buffers:
                        tool_call_buffers[idx] = {
                            "id": tc_delta.id or "",
                            "name": tc_delta.function.name if tc_delta.function else "",
                            "arguments": "",
                        }
                    if tc_delta.id:
                        tool_call_buffers[idx]["id"] = tc_delta.id
                    if tc_delta.function and tc_delta.function.name:
                        tool_call_buffers[idx]["name"] = tc_delta.function.name
                    if tc_delta.function and tc_delta.function.arguments:
                        tool_call_buffers[idx]["arguments"] += tc_delta.function.arguments

            # Usage
            if hasattr(chunk, 'usage') and chunk.usage:
                u = chunk.usage.model_dump() if hasattr(chunk.usage, 'model_dump') else dict(chunk.usage)
                for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    total_usage[k] = total_usage.get(k, 0) + u.get(k, 0)

        # If no tool calls, done
        if not tool_call_buffers:
            final = "".join(content_parts)
            accumulated.append(final)
            return "".join(accumulated)

        # Execute tool calls
        report.steps += 1

        # Build assistant message
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": "".join(content_parts) if content_parts else None,
        }
        tc_list = []
        for idx in sorted(tool_call_buffers.keys()):
            buf = tool_call_buffers[idx]
            tc_list.append({
                "id": buf["id"],
                "type": "function",
                "function": {"name": buf["name"], "arguments": buf["arguments"]},
            })
        assistant_msg["tool_calls"] = tc_list
        working.append(assistant_msg)

        for idx in sorted(tool_call_buffers.keys()):
            buf = tool_call_buffers[idx]
            name = buf["name"]
            try:
                args = json.loads(buf["arguments"])
            except json.JSONDecodeError:
                args = {}

            fn = TOOL_FUNCTIONS.get(name)
            if fn:
                try:
                    result = fn(**args)
                except Exception as e:
                    result = f"Tool error: {e}"
            else:
                result = f"Unknown tool: {name}"

            print(f"\n  [tool] {name} -> {str(result)[:100]}")

            report.tool_calls.append({
                "name": name,
                "ok": not isinstance(result, str) or not result.startswith(("Tool error", "Unknown", "ERROR")),
                "result": str(result)[:100],
            })

            working.append({
                "role": "tool",
                "tool_call_id": buf["id"],
                "content": json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result,
            })

        tool_call_buffers.clear()

    return "Max steps reached"


# ═══════════════════════════════════════════════════════════════════════════════
# Agent prompts and tasks (same as DeepSeekToolkit agent)
# ═══════════════════════════════════════════════════════════════════════════════

def _build_system_prompt(agent_type: str) -> str:
    prompts = {
        "financial": """你是资深财务分析师。分析财务报告时：
1. 先读取财务数据文件
2. 计算关键财务比率（ROE、ROA、毛利率、净利率、资产负债率）
3. 搜索行业对比数据
4. 给出专业财务分析结论
5. 保存分析报告""",

        "investment": """你是量化投资分析师。分析股票数据时：
1. 读取股票价格CSV数据
2. 计算技术指标（移动平均线、波动率、趋势）
3. 搜索相关市场新闻
4. 评估投资风险和机会
5. 给出投资建议""",

        "data_analysis": """你是数据分析专家。分析销售数据时：
1. 读取CSV数据集
2. 进行统计分析（按类别、区域、时间维度）
3. 搜索行业趋势
4. 找出关键洞察
5. 生成数据报告""",

        "director": """你是资深影视策划。分析电影项目时：
1. 读取剧本和角色数据
2. 分析类型市场表现
3. 搜索当前票房和竞争情况
4. 评估项目可行性
5. 给出创意思路和商业建议""",
    }
    return prompts.get(agent_type, prompts["data_analysis"])


def _get_task(agent_type: str) -> str:
    tasks = {
        "financial": (
            "分析字节跳动2025年财务报告。读取 financial_report.json 和 financial_report.md 两个文件，"
            "计算关键财务比率，搜索'字节跳动 2025 财务表现'了解行业对比，"
            "判断公司财务健康状况，最后将分析结论保存到 financial_analysis_report.txt。"
            "用中文输出。"
        ),
        "investment": (
            "分析 stock_prices.csv 中的股票价格数据，计算20日和60日移动平均线，"
            "评估价格趋势和波动率。搜索'中国科技股 2025 市场展望'获取宏观背景，"
            "结合技术指标给出买入/持有/卖出建议，将报告保存为 investment_report.txt。"
        ),
        "data_analysis": (
            "分析 sales_data.csv 电商销售数据，按产品类别、地区和客户类型进行多维度分析，"
            "找出销售趋势、最高价值品类和区域、季节性规律。"
            "搜索'2025年中国电商消费趋势'获取行业背景，"
            "生成数据洞察报告并保存到 data_analysis_report.txt。"
        ),
        "director": (
            "分析 movie_script.json 中的《流浪地球3》项目数据，评估项目商业可行性。"
            "搜索'2027春节档电影'了解竞争环境，搜索'流浪地球3 最新消息'了解市场预期，"
            "从剧本、角色、市场三个维度给出专业评估，"
            "将完整项目评估报告保存到 director_report.txt。"
        ),
    }
    return tasks.get(agent_type, tasks["data_analysis"])


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    agent_type = sys.argv[1] if len(sys.argv) > 1 else "financial"
    report = run_raw_agent(agent_type, streaming=True)
    print(f"\nReport saved to {OUTPUT_DIR}/")
