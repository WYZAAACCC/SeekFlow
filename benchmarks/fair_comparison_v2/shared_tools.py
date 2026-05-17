"""Shared tools, prompts, and tasks — IDENTICAL across ALL frameworks.

Core principle: every framework runs the exact same Python functions with the
exact same system prompts and task descriptions. The only difference is how
each framework orchestrates tool calling.

v2.1: structured tool contracts (input_echo/formula/data_quality/warnings),
      search robustness (semaphore/cache/retry/fixture), tool event logging,
      supply_risk_score, parse_system_prompt helper.
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import random
import re
import threading
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

_SEARCH_BACKEND = os.getenv("BENCH_SEARCH_BACKEND", "fixture")


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def parse_system_prompt(sys_prompt: str) -> tuple[str, str, str]:
    """Parse a 2-line system prompt into (role, goal, backstory).

    Uses removeprefix for correctness — strip('你是一名') is a character-set
    strip, not a prefix removal, and would mangle the role string.
    """
    lines = [x.strip() for x in sys_prompt.splitlines() if x.strip()]
    role_line = lines[0] if lines else "通用分析师"
    goal_line = lines[1] if len(lines) > 1 else "完成任务"

    role = role_line
    if role.startswith("你是一名"):
        role = role.removeprefix("你是一名").strip("。 ")
    goal = goal_line.strip("。 ")
    backstory = role_line
    return role, goal, backstory


# ═══════════════════════════════════════════════════════════════════════════
# Tool 1: Financial calculator — ROI
# ═══════════════════════════════════════════════════════════════════════════


def calculate_roi(investment: float, revenue: float) -> dict:
    """Calculate Return on Investment. investment=investment cost, revenue=total revenue"""
    roi = ((revenue - investment) / investment) * 100
    return {
        "roi_percent": round(roi, 2),
        "net_profit": round(revenue - investment, 2),
        "profit_margin_percent": round((revenue - investment) / revenue * 100, 2) if revenue else 0,
        "input_echo": {"investment": investment, "revenue": revenue},
        "formula": "roi=(revenue-investment)/investment*100",
        "data_quality": "tool_calculated",
    }


def compound_growth(principal: float, rate_percent: float, years: int) -> dict:
    """Calculate compound growth. principal=starting amount, rate_percent=annual rate %, years=number of years"""
    rate = rate_percent / 100
    values = [round(principal * (1 + rate) ** y, 2) for y in range(years + 1)]
    return {
        "final_value": values[-1],
        "total_growth_percent": round((values[-1] / principal - 1) * 100, 2),
        "year_by_year": values,
        "input_echo": {"principal": principal, "rate_percent": rate_percent, "years": years},
        "formula": "principal*(1+rate)^year",
        "data_quality": "tool_calculated",
    }


def risk_score(volatility_percent: float, debt_ratio: float, market_cap_billions: float) -> dict:
    """Calculate composite financial risk score (1-10, lower=safer).

    market_cap_billions is in BILLION USD.  Example: 850亿美元 = 85.0 billion USD.
    """
    warnings_list = []

    if market_cap_billions <= 0:
        warnings_list.append("market_cap_billions must be positive.")
    if market_cap_billions > 250:
        warnings_list.append(
            "market_cap_billions unusually large. "
            "If the source value is 亿美元, convert 850亿美元 -> 85.0 billion USD."
        )
    if debt_ratio > 1:
        warnings_list.append(
            "debt_ratio is usually 0-1. Check whether percent was passed accidentally."
        )

    v_score = min(10, volatility_percent / 5)
    d_score = min(10, debt_ratio * 10)
    m_score = max(0, 5 - market_cap_billions / 50) if market_cap_billions < 250 else 0
    composite = round((v_score * 0.4 + d_score * 0.35 + m_score * 0.25), 1)

    return {
        "risk_score": composite,
        "rating": "LOW" if composite < 3 else "MEDIUM" if composite < 6 else "HIGH" if composite < 8 else "CRITICAL",
        "breakdown": {
            "volatility_component": round(v_score, 1),
            "debt_component": round(d_score, 1),
            "size_component": round(m_score, 1),
        },
        "input_echo": {
            "volatility_percent": volatility_percent,
            "debt_ratio": debt_ratio,
            "market_cap_billions": market_cap_billions,
        },
        "unit_note": "market_cap_billions is billion USD; 850亿美元 = 85.0",
        "formula": "0.4*volatility_component + 0.35*debt_component + 0.25*size_component",
        "warnings": warnings_list,
        "data_quality": "tool_calculated",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 1b: Supply-chain risk score
# ═══════════════════════════════════════════════════════════════════════════


def supply_risk_score(
    probability_percent: float,
    impact_score: float,
    exposure_percent: float,
) -> dict:
    """Calculate supply-chain risk score.

    probability_percent: likelihood of disruption, 0-100
    impact_score: business impact, 1-10
    exposure_percent: share of supply/revenue/cost exposed, 0-100
    """
    p = max(0, min(100, probability_percent)) / 100
    i = max(1, min(10, impact_score)) / 10
    e = max(0, min(100, exposure_percent)) / 100

    score = round((p * 0.4 + i * 0.35 + e * 0.25) * 10, 1)
    return {
        "risk_score": score,
        "rating": "LOW" if score < 3 else "MEDIUM" if score < 6 else "HIGH" if score < 8 else "CRITICAL",
        "input_echo": {
            "probability_percent": probability_percent,
            "impact_score": impact_score,
            "exposure_percent": exposure_percent,
        },
        "formula": "risk_score=(probability*0.4 + impact*0.35 + exposure*0.25)*10",
        "data_quality": "scenario_inputs_or_explicit_proxy",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 2: Web search
# ═══════════════════════════════════════════════════════════════════════════

_SEARCH_SEM = threading.Semaphore(2)
_SEARCH_CACHE: dict[tuple[str, int], dict[str, Any]] = {}
_SEARCH_CACHE_LOCK = threading.Lock()

_SEARCH_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Safari/605.1.15",
]

# Pre-canned search results for fixture mode — reproducible, offline-safe.
_FIXTURE_SEARCH: dict[str, list[dict[str, str]]] = {
    "科技行业趋势": [
        {"title": "AI 基础设施投资持续增长", "snippet": "云计算、AI 芯片和企业智能化仍是科技行业主要增长方向。"},
        {"title": "软件订阅和算力需求推动科技企业收入", "snippet": "企业数字化预算继续向 AI、数据平台和自动化工具倾斜。"},
    ],
    "消费品行业趋势": [
        {"title": "消费品行业关注品牌韧性和渠道效率", "snippet": "高端化、健康化和线上线下融合成为消费品企业竞争重点。"},
    ],
    "新能源行业趋势": [
        {"title": "新能源需求受电动车和储能市场拉动", "snippet": "电动车、储能、电池材料和电网升级继续支撑新能源产业链增长。"},
    ],
    "台海芯片供应风险": [
        {"title": "芯片供应链高度集中带来地缘风险", "snippet": "先进制程和封装产能集中在东亚，地缘扰动可能影响汽车芯片供应稳定性。"},
    ],
    "南美锂矿供应风险": [
        {"title": "锂资源供应受政策、环保和基础设施影响", "snippet": "南美锂矿开发周期长，政策调整和社区环保要求可能影响供应节奏。"},
    ],
    "欧洲碳关税政策": [
        {"title": "欧洲碳边境调节机制提高出口企业合规成本", "snippet": "高碳排产品进入欧洲市场需要更严格的碳排放核算和成本管理。"},
    ],
}


def _search_trace_id(query: str) -> str:
    return hashlib.sha1(query.encode("utf-8")).hexdigest()[:10]


def _fixture_search(query: str, max_results: int) -> str:
    """Offline search: match against pre-canned fixture data."""
    hits: list[dict[str, Any]] = []
    for key, rows in _FIXTURE_SEARCH.items():
        if key in query or query in key:
            hits = [{"rank": i + 1, **row} for i, row in enumerate(rows[:max_results])]
            break

    if not hits:
        hits = [{
            "rank": 1,
            "title": f"Fixture fallback for: {query}",
            "snippet": "No exact fixture key matched. This is a controlled fallback, not live web evidence.",
        }]

    return _json_result({
        "status": "ok",
        "backend": "fixture",
        "query": query,
        "trace_id": _search_trace_id(query),
        "results": hits,
        "data_quality": "fixture_verified",
        "instruction": "Use only these fixture snippets as benchmark evidence. Do not invent additional facts, dates, or sources.",
    })


def _live_web_search(query: str, max_results: int) -> str:
    """Live search via 360 Search (so.com) with concurrency control and retry."""
    trace_id = _search_trace_id(query)
    cache_key = (query.strip(), max_results)

    with _SEARCH_CACHE_LOCK:
        cached = _SEARCH_CACHE.get(cache_key)
        if cached:
            payload = dict(cached)
            payload["cached"] = True
            return _json_result(payload)

    last_error = ""

    acquired = _SEARCH_SEM.acquire(timeout=15)
    if not acquired:
        return _json_result({
            "status": "unavailable",
            "query": query,
            "trace_id": trace_id,
            "cached": False,
            "results": [],
            "error": "search_congested",
            "data_quality": "search_unavailable",
            "instruction": (
                "搜索请求过多暂时无法执行。"
                "请在报告中写明「web_search 对该主题不可用，未获得可验证搜索结果」，不得编造搜索发现。"
            ),
        })

    try:
        for attempt in range(3):
            try:
                if attempt > 0:
                    time.sleep(0.8 * (2 ** (attempt - 1)) + random.uniform(0.1, 0.4))

                url = "https://www.so.com/s?q=" + urllib.parse.quote(query)
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": random.choice(_SEARCH_USER_AGENTS),
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    },
                )

                with urllib.request.urlopen(req, timeout=8) as resp:
                    html = resp.read().decode("utf-8", errors="replace")

                results: list[dict[str, Any]] = []
                for m in re.finditer(
                    r'<h3[^>]*class="res-title"[^>]*>(.*?)</h3>',
                    html,
                    re.DOTALL,
                ):
                    if len(results) >= max_results:
                        break
                    raw_title = m.group(1)
                    title = re.sub(r"<[^>]+>", "", raw_title).strip()
                    title = re.sub(r"\s+", " ", title)
                    if not title:
                        continue

                    tail = html[m.end(): m.end() + 1000]
                    desc_m = re.search(
                        r'class="res-list-summary"[^>]*>(.*?)</[^>]+>',
                        tail,
                        re.DOTALL,
                    )
                    snippet = ""
                    if desc_m:
                        snippet = re.sub(r"<[^>]+>", "", desc_m.group(1)).strip()
                        snippet = re.sub(r"\s+", " ", snippet)[:240]

                    results.append({
                        "rank": len(results) + 1,
                        "title": title[:150],
                        "snippet": snippet,
                    })

                if results:
                    payload = {
                        "status": "ok",
                        "backend": "live",
                        "query": query,
                        "trace_id": trace_id,
                        "cached": False,
                        "results": results,
                        "data_quality": "live_search_verified",
                        "instruction": (
                            "Use only these returned titles/snippets as external-search evidence. "
                            "Do not invent additional facts, dates, sources, or numeric values."
                        ),
                    }
                    with _SEARCH_CACHE_LOCK:
                        _SEARCH_CACHE[cache_key] = payload
                    return _json_result(payload)

                last_error = "empty_or_parse_failed"

            except Exception as e:
                last_error = f"{type(e).__name__}: {str(e)[:120]}"

        return _json_result({
            "status": "unavailable",
            "query": query,
            "trace_id": trace_id,
            "cached": False,
            "results": [],
            "error": last_error,
            "data_quality": "search_unavailable",
            "instruction": (
                "搜索失败，未获得可验证结果。"
                "请在报告中写明「web_search 对该主题不可用，未获得可验证搜索结果」，不得编造搜索发现。"
            ),
        })
    finally:
        _SEARCH_SEM.release()


def web_search(query: str, max_results: int = 4) -> str:
    """Search the web. Backend selected via BENCH_SEARCH_BACKEND env var.

    Returns JSON string with status/query/results/instruction/data_quality.
    """
    max_results = max(1, min(int(max_results), 6))
    backend = _SEARCH_BACKEND.lower()
    if backend == "live":
        return _live_web_search(query, max_results)
    return _fixture_search(query, max_results)


# ═══════════════════════════════════════════════════════════════════════════
# Tool 3: Statistical summary
# ═══════════════════════════════════════════════════════════════════════════


def statistical_summary(values: str) -> dict:
    """Compute statistical summary of comma-separated numbers. Example: statistical_summary('10, 20, 30, 40, 50')"""
    try:
        nums = [float(x.strip()) for x in values.split(",") if x.strip()]
        if not nums:
            return {"error": "No valid numbers provided", "data_quality": "invalid_input"}
        n = len(nums)
        mean = sum(nums) / n
        sorted_nums = sorted(nums)
        median = sorted_nums[n // 2] if n % 2 else (sorted_nums[n // 2 - 1] + sorted_nums[n // 2]) / 2
        variance = sum((x - mean) ** 2 for x in nums) / n
        return {
            "count": n, "mean": round(mean, 4), "median": round(median, 4),
            "std_dev": round(math.sqrt(variance), 4),
            "min": min(nums), "max": max(nums), "range": max(nums) - min(nums),
            "input_echo": {"values": values},
            "formula": "population_std",
            "data_quality": "tool_calculated",
        }
    except Exception as e:
        return {"error": str(e), "data_quality": "invalid_input"}


# ═══════════════════════════════════════════════════════════════════════════
# Tool 4: File reader
# ═══════════════════════════════════════════════════════════════════════════


def read_file(path: str, max_chars: int = 5000) -> str:
    """Read content from a file path. Returns first max_chars characters."""
    try:
        p = Path(path)
        if not p.exists():
            return json.dumps({"error": f"File not found: {path}", "data_quality": "file_not_found"}, ensure_ascii=False)
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n...[truncated, {len(content)} total chars]"
        return content
    except Exception as e:
        return json.dumps({"error": str(e), "data_quality": "file_read_error"}, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════
# Tool 5: Currency converter
# ═══════════════════════════════════════════════════════════════════════════


def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    """Convert between currencies using approximate exchange rates. Supported: USD, CNY, EUR, JPY, GBP, KRW, INR"""
    rates = {"USD": 1.0, "CNY": 7.25, "EUR": 0.92, "JPY": 156.0, "GBP": 0.79, "KRW": 1360.0, "INR": 83.5}
    if from_currency not in rates or to_currency not in rates:
        return {"error": f"Unsupported currency. Supported: {list(rates.keys())}", "data_quality": "invalid_input"}
    usd = amount / rates[from_currency]
    result = usd * rates[to_currency]
    return {
        "amount": amount, "from": from_currency, "to": to_currency,
        "result": round(result, 2),
        "rate": round(rates[to_currency] / rates[from_currency], 4),
        "input_echo": {"amount": amount, "from_currency": from_currency, "to_currency": to_currency},
        "formula": "amount / from_rate * to_rate",
        "data_quality": "tool_calculated",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 6: Text keyword extractor
# ═══════════════════════════════════════════════════════════════════════════


def extract_keywords(text: str, top_k: int = 10) -> dict:
    """Extract key terms and their frequency from text."""
    words = re.findall(r'\b[a-zA-Z一-鿿]{2,}\b', text.lower())
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return {
        "total_words": len(words), "unique_words": len(freq),
        "top_keywords": [{"word": w, "count": c} for w, c in sorted_words[:top_k]],
        "input_echo": {"text_length": len(text), "top_k": top_k},
        "data_quality": "tool_calculated",
    }


# ═══════════════════════════════════════════════════════════════════════════
# Tool event instrumentation — framework-agnostic call logging
# ═══════════════════════════════════════════════════════════════════════════

_TOOL_EVENTS_LOCK = threading.Lock()
_TOOL_EVENTS: list[dict[str, Any]] = []


def reset_tool_events() -> None:
    """Clear accumulated tool events. Call at start of each agent run."""
    with _TOOL_EVENTS_LOCK:
        _TOOL_EVENTS.clear()


def get_tool_events() -> list[dict[str, Any]]:
    """Return a copy of all accumulated tool events."""
    with _TOOL_EVENTS_LOCK:
        return list(_TOOL_EVENTS)


def _safe_preview(obj: Any, max_chars: int = 800) -> str:
    try:
        text = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        text = str(obj)
    return text[:max_chars]


def instrument_tool(fn: Callable) -> Callable:
    """Wrap a tool function to log every call (args, result, latency, errors).

    Does NOT use functools.wraps because that sets __wrapped__, which
    inspect.unwrap() follows — some frameworks (SeekFlow) use unwrap to
    get the "real" function, bypassing our event logging.
    """

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        event: dict[str, Any] = {
            "tool": fn.__name__,
            "args": args,
            "kwargs": kwargs,
            "started_at_perf": started,
            "success": False,
            "latency_seconds": None,
            "result_preview": "",
            "error": "",
        }
        try:
            result = fn(*args, **kwargs)
            event["success"] = True
            event["result_preview"] = _safe_preview(result)
            return result
        except Exception as e:
            event["error"] = f"{type(e).__name__}: {str(e)}"
            event["traceback"] = traceback.format_exc()[-1000:]
            raise
        finally:
            event["latency_seconds"] = round(time.perf_counter() - started, 3)
            with _TOOL_EVENTS_LOCK:
                _TOOL_EVENTS.append(event)

    wrapper.__name__ = fn.__name__
    wrapper.__qualname__ = fn.__qualname__
    wrapper.__doc__ = fn.__doc__
    wrapper.__module__ = fn.__module__
    # Do NOT set __wrapped__ — prevents inspect.unwrap() from bypassing us
    return wrapper


# ═══════════════════════════════════════════════════════════════════════════
# SHARED: All tools as a flat list (raw → instrumented)
# ═══════════════════════════════════════════════════════════════════════════

_RAW_TOOLS = [
    calculate_roi,
    compound_growth,
    risk_score,
    supply_risk_score,
    web_search,
    statistical_summary,
    read_file,
    convert_currency,
    extract_keywords,
]

SHARED_TOOLS = [instrument_tool(t) for t in _RAW_TOOLS]

# Replace module-level names with instrumented versions so ALL import paths
# (including framework-internal references) hit the event-logging wrappers.
for _raw, _inst in zip(_RAW_TOOLS, SHARED_TOOLS):
    globals()[_raw.__name__] = _inst


# ═══════════════════════════════════════════════════════════════════════════
# SHARED: System prompts (IDENTICAL for ALL frameworks)
# ═══════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPTS = {
    "financial_analyst": (
        "你是一名资深金融分析师，拥有15年华尔街经验。\n"
        "完成投资分析任务。"
    ),
    "supply_chain_analyst": (
        "你是一名全球供应链风险管理专家，拥有20年制造业咨询经验。\n"
        "完成供应链风险评估任务。"
    ),
}

# ═══════════════════════════════════════════════════════════════════════════
# SHARED: Common task rules — prepended to every task
# ═══════════════════════════════════════════════════════════════════════════

_COMMON_TASK_RULES = """## 执行规则

1. 数值计算必须调用工具。工具成功返回后，报告必须引用工具返回值，并标注「工具：tool_name」。
2. 搜索类工具若返回 status=ok，只能使用返回的 title/snippet 作为外部证据。
3. 搜索类工具若返回 status=unavailable 或 results=[]，必须写明「未获得可验证搜索结果」，不得编造搜索结论、来源、日期或数字。
4. 报告必须包含一个「工具调用摘要」小节，列出工具名、关键输入、关键返回值。
5. 不强制并行调用；可以并行，但不得超过工具限流。所有必需工具完成或明确失败后，再写最终报告。
6. 最终报告控制在 4500 中文字符以内，优先保留结论、关键数值、工具来源和建议。
"""

# ═══════════════════════════════════════════════════════════════════════════
# SHARED: Task descriptions (IDENTICAL for ALL frameworks)
# ═══════════════════════════════════════════════════════════════════════════

_FINANCIAL_TASK = """请分析以下三家公司的投资价值，生成中文投资备忘录。

**公司数据（所有参数必须严格使用，不得自行修改）：**

| 参数 | 科技A | 消费品B | 新能源C |
|------|:-----:|:------:|:------:|
| volatility_percent | 32 | 18 | 45 |
| debt_ratio | 0.15 | 0.42 | 0.28 |
| market_cap_billions | **85.0** | **12.0** | **3.5** |
| investment (万美元) | 500 | 300 | 800 |
| revenue (万美元) | 870 | 410 | 1250 |
| growth_rate_percent | 15 | 8 | 25 |

> 单位注意：market_cap_billions 单位是十亿美元。850亿美元 = 85.0 billion USD，不是 850 或 8.5。

**必须执行的工具调用清单：**
- web_search：「科技行业趋势」「消费品行业趋势」「新能源行业趋势」
- calculate_roi：A/B/C 各一次
- compound_growth：A/B/C 各一次，principal=revenue, rate_percent=growth_rate_percent, years=5
- risk_score：A/B/C 各一次，严格使用上表 volatility/debt_ratio/market_cap_billions 参数
- statistical_summary：输入 "85.0,12.0,3.5"
- convert_currency：将 A/B/C 的 investment 从 USD 分别转 CNY、EUR（共6次）

**输出结构：**
1. 执行摘要
2. 工具调用摘要
3. 三家公司关键指标对比
4. 风险与增长分析
5. 投资建议"""

_SUPPLY_TASK = """请分析中国电动汽车制造商供应链风险，生成中文风险评估报告。

**场景数据：**
- 年产量：50万辆
- 电池原材料60%来自南美和非洲
- 芯片供应45%依赖台湾和韩国
- 欧洲市场需求增长35%，面临碳关税
- 海运成本12个月数据（美元/40尺柜）：3200,3400,3800,4100,3900,3600,3400,3100,3300,3600,4200,4500
- 欧洲建厂投资：2亿欧元；年运营成本：3500万欧元

**必须执行的工具调用清单：**
- web_search：「台海芯片供应风险」「南美锂矿供应风险」「欧洲碳关税政策」
- statistical_summary：分析海运成本数据（输入上列12个数值，逗号分隔）
- compound_growth：principal=500000, rate_percent=18, years=3（估算产量/需求增长）
- convert_currency：amount=200000000, from_currency=EUR, to_currency=CNY
- extract_keywords：输入三个 web_search 返回的 snippet 拼接文本；若搜索失败则输入失败声明文本
- supply_risk_score：按以下固定参数调用，不得自行修改参数：
  1. 台海芯片 risk：probability_percent=35, impact_score=9, exposure_percent=45
  2. 南美/非洲电池原材料 risk：probability_percent=30, impact_score=8, exposure_percent=60
  3. 欧洲碳关税 risk：probability_percent=70, impact_score=6, exposure_percent=35

**输出结构：**
1. 执行摘要
2. 工具调用摘要
3. 风险矩阵
4. 海运成本趋势
5. 原材料/产量需求增长
6. 欧洲建厂成本影响
7. 缓解策略
8. 总结建议"""

TASKS = {
    "financial_analyst": _COMMON_TASK_RULES + "\n\n" + _FINANCIAL_TASK,
    "supply_chain_analyst": _COMMON_TASK_RULES + "\n\n" + _SUPPLY_TASK,
}
