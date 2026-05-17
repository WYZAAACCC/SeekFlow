"""Shared tools, prompts, and tasks — IDENTICAL across ALL frameworks.

Core principle: every framework runs the exact same Python functions with the
exact same system prompts and task descriptions. The only difference is how
each framework orchestrates tool calling.
"""
from __future__ import annotations

import json
import math
import re
import urllib.parse
import urllib.request
from pathlib import Path

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
    }


def compound_growth(principal: float, rate_percent: float, years: int) -> dict:
    """Calculate compound growth over time. principal=starting amount, rate_percent=annual growth rate %, years=number of years"""
    rate = rate_percent / 100
    values = []
    for y in range(years + 1):
        values.append(round(principal * (1 + rate) ** y, 2))
    return {
        "final_value": values[-1],
        "total_growth_percent": round((values[-1] / principal - 1) * 100, 2),
        "year_by_year": values,
    }


def risk_score(volatility_percent: float, debt_ratio: float, market_cap_billions: float) -> dict:
    """Calculate a composite risk score (1-10, lower is safer). volatility_percent=annualized volatility, debt_ratio=debt ratio, market_cap_billions=market cap in billions"""
    v_score = min(10, volatility_percent / 5)
    d_score = min(10, debt_ratio * 10)
    m_score = max(0, 5 - market_cap_billions / 50) if market_cap_billions < 250 else 0
    composite = round((v_score * 0.4 + d_score * 0.35 + m_score * 0.25), 1)
    return {
        "risk_score": composite,
        "rating": "LOW" if composite < 3 else "MEDIUM" if composite < 6 else "HIGH" if composite < 8 else "CRITICAL",
        "breakdown": {"volatility_component": round(v_score, 1), "debt_component": round(d_score, 1), "size_component": round(m_score, 1)},
    }


# ═══════════════════════════════════════════════════════════════════════════
# Tool 2: Web search
# ═══════════════════════════════════════════════════════════════════════════


def web_search(query: str, max_results: int = 4) -> str:
    """Search the web via 360 Search (so.com). Returns top results with snippets."""
    try:
        url = "https://www.so.com/s?q=" + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return json.dumps({"results": [], "error": "Search unavailable"}, ensure_ascii=False)

    results = []
    for m in re.finditer(r'<h3[^>]*class="res-title"[^>]*>(.*?)</h3>', html, re.DOTALL):
        if len(results) >= max_results:
            break
        title = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if not title:
            continue
        # Snippet in following res-desc div
        tail = html[m.end():m.end() + 800]
        desc_m = re.search(r'class="res-list-summary"[^>]*>(.*?)</div>', tail, re.DOTALL)
        snippet = ""
        if desc_m:
            snippet = re.sub(r'<[^>]+>', '', desc_m.group(1)).strip()[:200]
        results.append({"rank": len(results) + 1, "title": title[:150], "snippet": snippet})
    return json.dumps({"results": results, "query": query}, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════
# Tool 3: Statistical summary
# ═══════════════════════════════════════════════════════════════════════════


def statistical_summary(values: str) -> dict:
    """Compute statistical summary of comma-separated numbers. Example: statistical_summary('10, 20, 30, 40, 50')"""
    try:
        nums = [float(x.strip()) for x in values.split(",") if x.strip()]
        if not nums:
            return {"error": "No valid numbers provided"}
        n = len(nums)
        mean = sum(nums) / n
        sorted_nums = sorted(nums)
        median = sorted_nums[n // 2] if n % 2 else (sorted_nums[n // 2 - 1] + sorted_nums[n // 2]) / 2
        variance = sum((x - mean) ** 2 for x in nums) / n
        return {
            "count": n, "mean": round(mean, 4), "median": round(median, 4),
            "std_dev": round(math.sqrt(variance), 4),
            "min": min(nums), "max": max(nums), "range": max(nums) - min(nums),
        }
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════
# Tool 4: File reader
# ═══════════════════════════════════════════════════════════════════════════


def read_file(path: str, max_chars: int = 5000) -> str:
    """Read content from a file path. Returns first max_chars characters."""
    try:
        p = Path(path)
        if not p.exists():
            return json.dumps({"error": f"File not found: {path}"}, ensure_ascii=False)
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n...[truncated, {len(content)} total chars]"
        return content
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════════════════
# Tool 5: Currency converter
# ═══════════════════════════════════════════════════════════════════════════


def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    """Convert between currencies using approximate exchange rates. Supported: USD, CNY, EUR, JPY, GBP, KRW, INR"""
    rates = {"USD": 1.0, "CNY": 7.25, "EUR": 0.92, "JPY": 156.0, "GBP": 0.79, "KRW": 1360.0, "INR": 83.5}
    if from_currency not in rates or to_currency not in rates:
        return {"error": f"Unsupported currency. Supported: {list(rates.keys())}"}
    usd = amount / rates[from_currency]
    result = usd * rates[to_currency]
    return {"amount": amount, "from": from_currency, "to": to_currency, "result": round(result, 2), "rate": round(rates[to_currency] / rates[from_currency], 4)}


# ═══════════════════════════════════════════════════════════════════════════
# Tool 6: Text keyword extractor
# ═══════════════════════════════════════════════════════════════════════════


def extract_keywords(text: str, top_k: int = 10) -> dict:
    """Extract key terms and their frequency from text."""
    words = re.findall(r'\b[a-zA-Z一-鿿]{2,}\b', text.lower())
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return {"total_words": len(words), "unique_words": len(freq), "top_keywords": [{"word": w, "count": c} for w, c in sorted_words[:top_k]]}


# ═══════════════════════════════════════════════════════════════════════════
# SHARED: All tools as a flat list
# ═══════════════════════════════════════════════════════════════════════════

SHARED_TOOLS = [
    calculate_roi,
    compound_growth,
    risk_score,
    web_search,
    statistical_summary,
    read_file,
    convert_currency,
    extract_keywords,
]

# ═══════════════════════════════════════════════════════════════════════════
# SHARED: System prompts (IDENTICAL for ALL frameworks)
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# SHARED: System prompts (IDENTICAL for ALL frameworks)
#
# NOTE: Must have >=2 \n-separated lines — SeekFlow/CrewAI parse
#   split("\n")[0] as role and [1] as goal.  Instructions moved to TASKS.
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
# SHARED: Task instructions prefix — prepended to EVERY task, ALL frameworks
# receive this identically via the user message.  Previously these rules were
# only in SYSTEM_PROMPTS, which SeekFlow/CrewAI discarded during parsing.
# ═══════════════════════════════════════════════════════════════════════════

_TASK_INSTRUCTIONS = {
    "financial_analyst": (
        "## 执行指令（必须严格遵守）\n\n"
        "### 工具使用铁律\n"
        "- 所有数值计算必须使用工具完成，不得手动计算\n"
        "- 工具成功返回时，你必须在报告中引用工具返回的具体数值，并标注数据来源（如「工具：calculate_roi」）\n"
        "- 工具不可用时，明确标注「工具不可用，以下为专家估算」「搜索引擎不可用，以下基于专业知识」\n"
        "- 绝对禁止：伪造搜索结果、编造工具返回的数值、使用通用知识替代工具输出\n"
        "- 注意单位：market_cap_billions=85.0 表示 850亿美元，不是 8500亿。仔细核对每个参数的含义\n\n"
        "### 工具调用痕迹要求（评分关键）\n"
        "- 报告中必须展示工具调用痕迹：每个工具调用给出工具名+关键返回值\n"
        "- 格式示例：「>> web_search('科技行业趋势') -> 返回3条结果：...[此处引用摘要内容]」\n"
        "- 不展示工具调用痕迹的报告将被严重扣分\n\n"
        "### 报告结构\n"
        "1. 执行摘要\n"
        "2. 关键指标分析（ROI、增长率、风险评分，每项标注工具来源）\n"
        "3. 风险评估（明确标注「工具计算」或「专家估算」）\n"
        "4. 投资建议\n\n"
        "### 执行规则\n"
        "- 多个独立工具调用必须在一次回复中同时发起（并行），不要串行\n"
        "- 所有独立工具调用必须执行完毕后才开始撰写报告\n"
        "- 最终输出为中文，结构清晰，专业简洁\n"
    ),
    "supply_chain_analyst": (
        "## 执行指令（必须严格遵守）\n\n"
        "### 工具使用铁律\n"
        "- 工具返回的数值是你唯一的数据来源，你必须直接使用，不得用任何其他数字替代\n"
        "- 报告中绝不出现「手动计算」「基于经验」「凭借专业知识」——这会让你的结论失去可信度\n"
        "- 如果工具返回了某个数值，你的报告中必须出现该数值并标注来源（如「工具：statistical_summary」）\n"
        "- 绝对禁止：伪造搜索结果、编造工具返回值、跳过工具直接给结论\n"
        "- 注意单位：仔细检查工具参数名和返回值的实际含义，避免数量级错误\n\n"
        "### 工具调用痕迹要求（评分关键）\n"
        "- 报告中必须展示每个工具调用的痕迹：工具名 + 关键返回值\n"
        "- 格式示例：「>> web_search('台海芯片供应风险') -> 返回3条结果：...[此处引用摘要内容]」\n"
        "- 格式示例：「>> statistical_summary(海运成本数据) -> 均值=3658, 中位数=3550, 标准差=428」\n"
        "- 不展示工具调用痕迹的报告将被严重扣分\n\n"
        "### 报告结构\n"
        "1. 执行摘要（3-5句话）\n"
        "2. 地缘政治风险分析（引用web_search返回的具体信息，标注搜索词和结果摘要）\n"
        "3. 关键风险识别（按严重程度排序，至少3个，引用risk_score工具返回的评分）\n"
        "4. 海运成本趋势分析（引用statistical_summary工具返回的均值、中位数、标准差）\n"
        "5. 原材料需求增长预测（引用compound_growth工具返回的逐年数据）\n"
        "6. 成本影响估算（引用convert_currency工具返回的换算结果）\n"
        "7. 风险缓解策略（每个风险至少1个具体措施）\n"
        "8. 总结建议\n\n"
        "### 执行规则\n"
        "- 多个独立工具调用必须在一次回复中同时发起（并行），不要串行\n"
        "- 所有独立工具调用必须执行完毕后才开始撰写报告\n"
        "- 最终输出为中文，结构清晰，专业简洁\n"
    ),
}

# ═══════════════════════════════════════════════════════════════════════════
# SHARED: Task descriptions (IDENTICAL for ALL frameworks)
# ═══════════════════════════════════════════════════════════════════════════

TASKS = {
    "financial_analyst": (
        _TASK_INSTRUCTIONS["financial_analyst"] + "\n\n"
        "---\n\n"
        "请分析以下三家公司的投资价值，生成一份完整的投资备忘录：\n\n"
        "**标的公司：**\n"
        "1. 科技公司A：年化波动率32%，负债比率0.15，市值850亿美元，投入成本500万美元，预期年收入870万美元\n"
        "2. 消费品公司B：年化波动率18%，负债比率0.42，市值120亿美元，投入成本300万美元，预期年收入410万美元\n"
        "3. 新能源公司C：年化波动率45%，负债比率0.28，市值35亿美元，投入成本800万美元，预期年收入1250万美元\n\n"
        "**必须执行的工具调用清单：**\n"
        "- web_search：搜索每家公司所在行业的最新趋势（至少3次搜索）\n"
        "- compound_growth：计算5年复合增长预测（A=15%, B=8%, C=25%）\n"
        "- statistical_summary：分析三家公司的市值分布\n"
        "- convert_currency：将投资金额转换为CNY和EUR\n"
        "- risk_score：计算每家公司的综合风险评分\n"
        "- calculate_roi：计算每家公司的ROI\n\n"
        "**输出格式：** 一份结构化的投资备忘录，包含上述所有分析。每个工具调用必须展示痕迹。"
    ),
    "supply_chain_analyst": (
        _TASK_INSTRUCTIONS["supply_chain_analyst"] + "\n\n"
        "---\n\n"
        "请分析以下制造业供应链场景，生成一份完整的风险评估报告：\n\n"
        "**场景：**\n"
        "一家中国电动汽车制造商（年产量50万辆）面临以下供应链挑战：\n"
        "- 关键电池原材料（锂、钴、镍）60%来自南美和非洲\n"
        "- 芯片供应依赖台湾和韩国（占比45%）\n"
        "- 欧洲市场需求增长35%，但面临新的碳关税政策\n"
        "- 海运成本过去12个月的月度波动数据：3200,3400,3800,4100,3900,3600,3400,3100,3300,3600,4200,4500（美元/40尺柜）\n"
        "- 公司计划在欧洲建厂，预计投资2亿欧元，年运营成本3500万欧元\n\n"
        "**必须执行的工具调用清单：**\n"
        "- web_search：搜索地缘政治风险（至少3个不同主题：台海芯片、南美锂矿、欧洲碳关税）\n"
        "- statistical_summary：分析海运成本趋势\n"
        "- compound_growth：预测未来3年电池原材料需求增长（年增长18%）\n"
        "- convert_currency：计算欧洲建厂投资的人民币金额\n"
        "- extract_keywords：分析搜索结果的文本特征\n"
        "- risk_score：评估不同风险维度的综合评分\n\n"
        "**输出格式：** 一份结构化的供应链风险评估报告，包含风险矩阵、缓解策略和成本影响。每个工具调用必须展示痕迹。"
    ),
}

