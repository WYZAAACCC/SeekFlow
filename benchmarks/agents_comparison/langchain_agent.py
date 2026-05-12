"""LangChain 1.2.18 agent — uses create_agent() with ChatOpenAI → DeepSeek.

Tests LangChain's agent capabilities with DeepSeek:
  - ChatOpenAI with DeepSeek base_url
  - @tool decorator from langchain_core.tools
  - create_agent() with custom middleware
  - Streaming via stream_mode="messages"
  - Token usage tracking via AIMessage.usage_metadata
  - Comprehensive runtime data saving
"""
import json
import sys
import io
import time
import os

# Suppress OpenMP duplicate library warning from matplotlib
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
import re
import urllib.request
import urllib.parse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

# Fix Windows GBK encoding
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not API_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY environment variable is required")
MODEL = "deepseek-v4-pro"

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "output" / "langchain"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# LangChain imports
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool as lc_tool
from langchain_core.messages import AIMessage, ToolMessage, HumanMessage, SystemMessage
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse

# Comprehensive saver
import os as _os
_bench_dir = _os.path.dirname(_os.path.abspath(__file__))
if _bench_dir not in sys.path:
    sys.path.insert(0, _bench_dir)
from comprehensive_saver import (
    RuntimeSaver, FrameworkFeatures, get_framework_features,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Tools — using LangChain's @tool decorator
# ═══════════════════════════════════════════════════════════════════════════════

@lc_tool
def read_file(path: str) -> str:
    """Read a file from the data directory. Supports txt, csv, json, md, pdf."""
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


@lc_tool
def web_search(query: str) -> str:
    """Search the web for information using Bing China (accessible in mainland China)."""
    import html as _html_lib
    params = urllib.parse.urlencode({"q": query, "setlang": "zh-cn"})
    url = f"https://cn.bing.com/search?{params}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"Search failed: {e}"

    results = []
    sections = re.split(r'<li class="b_algo', raw_html)
    for section in sections[1:]:
        if len(results) >= 5:
            break
        title_match = re.search(r"<h2[^>]*><a[^>]*>(.*?)</a></h2>", section, re.DOTALL)
        title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""
        url_match = re.search(r"<h2[^>]*><a[^>]*href=\"(https?://[^\"]+)\"", section)
        page_url = url_match.group(1) if url_match else ""
        snippet = ""
        p_match = re.search(r"<p[^>]*>(.*?)</p>", section, re.DOTALL)
        if p_match:
            snippet = re.sub(r"<[^>]+>", "", p_match.group(1)).strip()
        if not snippet:
            cap_match = re.search(r'class="b_caption[^"]*"[^>]*>(.*?)</div>', section, re.DOTALL)
            if cap_match:
                snippet = re.sub(r"<[^>]+>", "", cap_match.group(1)).strip()
        title = _html_lib.unescape(title)
        snippet = _html_lib.unescape(snippet)
        page_url = _html_lib.unescape(page_url)
        if title:
            entry = f"{len(results) + 1}. {title}"
            if snippet:
                entry += f"\n   {snippet}"
            if page_url:
                entry += f"\n   {page_url}"
            results.append(entry)
    return "\n".join(results) if results else "No results."


@lc_tool
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression and return the result."""
    try:
        result = eval(expression, {"__builtins__": {}}, {
            "abs": abs, "round": round, "min": min, "max": max,
            "sum": sum, "pow": pow,
        })
        return f"Result: {result}"
    except Exception as e:
        return f"Calculation error: {e}"


@lc_tool
def save_result(filename: str, content: str) -> str:
    """Save analysis result to output directory."""
    full = OUTPUT_DIR / filename
    full.write_text(content, encoding="utf-8")
    return f"Saved {len(content)} bytes to {filename}"


@lc_tool
def download_page(url: str) -> str:
    """Download and extract text content from a web page URL. Use this to read full articles found via web_search."""
    import html as _html
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"Download failed: {e}"
    raw = re.sub(r'<script[^>]*>.*?</script>', '', raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r'<style[^>]*>.*?</style>', '', raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r'<head[^>]*>.*?</head>', '', raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r'<nav[^>]*>.*?</nav>', '', raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r'<footer[^>]*>.*?</footer>', '', raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', raw)
    text = re.sub(r'\s+', ' ', text).strip()
    text = _html.unescape(text)
    if len(text) > 6000:
        text = text[:6000] + f"\n... [truncated, total {len(text)} chars]"
    return text


# Import new production tools
from tools.stock_data import fetch_stock_data
from tools.charting import generate_chart, generate_financial_table
from tools.sandbox import run_python_experiment
from tools.brainstorm import brainstorm_ideas

# Register as LangChain tools
@lc_tool
def fetch_stock_data_lc(symbol: str, period: str = "6mo") -> str:
    """Fetch real stock price data. Symbol formats: '000001.SZ' (Shenzhen), '600519.SH' (Shanghai). Period: '1mo','3mo','6mo','1y'."""
    return fetch_stock_data(symbol, period)


@lc_tool
def generate_chart_lc(data_json: str, chart_type: str, title: str, filename: str) -> str:
    """Generate a chart (line, bar, pie, scatter) and save as PNG. data_json: {'labels':[...], 'values':[...]}."""
    return generate_chart(data_json, chart_type, title, filename)


@lc_tool
def generate_financial_table_lc(data_json: str, title: str, filename: str) -> str:
    """Generate a formatted financial table. data_json: {'headers':[...], 'rows':[[...],...]}."""
    return generate_financial_table(data_json, title, filename)


@lc_tool
def run_python_experiment_lc(code: str, timeout: int = 60) -> str:
    """Execute Python code in a sandbox. Use for data analysis, statistics. Has math, statistics, json modules."""
    return run_python_experiment(code, timeout)


@lc_tool
def brainstorm_ideas_lc(topic: str, count: int = 5) -> str:
    """Generate creative ideas using brainstorming frameworks (SCAMPER, TRIZ, lateral thinking)."""
    return brainstorm_ideas(topic, count)


LANGCHAIN_TOOLS = [
    read_file, web_search, download_page, calculate, save_result,
    fetch_stock_data_lc, generate_chart_lc, generate_financial_table_lc,
    run_python_experiment_lc, brainstorm_ideas_lc,
]


# ═══════════════════════════════════════════════════════════════════════════════
# Timing Middleware — captures per-API-call latency and token usage
# ═══════════════════════════════════════════════════════════════════════════════

class TimingMiddleware(AgentMiddleware):
    """Middleware that records latency and token usage for every model call."""

    def __init__(self, saver: RuntimeSaver):
        super().__init__()
        self.saver = saver
        self.call_count = 0

    def wrap_model_call(self, request: ModelRequest, handler):
        self.call_count += 1
        step = self.saver.begin_step()
        t0 = time.perf_counter()

        # Record sent messages
        self.saver.set_extra(f"step_{step}_messages_sent", len(request.messages))

        try:
            response = handler(request)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            self.saver.record_model_call(step, len(request.messages),
                                         content=f"ERROR: {e}",
                                         finish_reason="error")
            self.saver.record_token_usage(step, {}, 0)
            raise

        elapsed = (time.perf_counter() - t0) * 1000

        # Extract content and token usage from response
        content = ""
        reasoning = ""
        finish_reason = "stop"
        usage_dict = {}

        for msg in response.result if hasattr(response, 'result') else []:
            if isinstance(msg, AIMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content or "")
                if hasattr(msg, 'reasoning_content') and msg.reasoning_content:
                    reasoning = msg.reasoning_content
                if msg.usage_metadata:
                    um = msg.usage_metadata
                    usage_dict = {
                        "prompt_tokens": um.get("input_tokens", 0),
                        "completion_tokens": um.get("output_tokens", 0),
                        "total_tokens": um.get("total_tokens", 0),
                    }
                    # Cache read tokens
                    if um.get("input_token_details", {}).get("cache_read", 0) > 0:
                        usage_dict["prompt_tokens_details"] = {
                            "cached_tokens": um["input_token_details"]["cache_read"]
                        }
                if msg.response_metadata:
                    finish_reason = msg.response_metadata.get("finish_reason", finish_reason)

        # Record tool calls
        if hasattr(response, 'result'):
            for msg in response.result:
                if isinstance(msg, AIMessage) and msg.tool_calls:
                    for tc in msg.tool_calls:
                        self.saver.record_tool_call(
                            step=step,
                            name=tc.get("name", "unknown"),
                            arguments=tc.get("args", {}),
                            result="",  # Results come later via ToolMessages
                            ok=True,
                        )

        self.saver.record_model_call(step, len(request.messages),
                                     content=content,
                                     reasoning=reasoning,
                                     finish_reason=finish_reason)

        # Estimate cost
        cost = 0.0
        if usage_dict:
            pricing = {"input": 1.74, "output": 3.48, "cached_input": 0.028}
            prompt_tokens = usage_dict.get("prompt_tokens", 0)
            completion_tokens = usage_dict.get("completion_tokens", 0)
            cached = (usage_dict.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0)
            fresh_prompt = prompt_tokens - cached
            cost = (fresh_prompt * pricing["input"] +
                    cached * pricing["cached_input"] +
                    completion_tokens * pricing["output"]) / 1_000_000

        self.saver.record_token_usage(step, usage_dict, cost)

        return response


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Report
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class LangChainAgentReport:
    """Report for a LangChain agent run — compatible with comparison infra."""
    agent_type: str
    framework: str = "LangChain"
    task: str = ""
    final_output: str = ""
    tool_calls: list = field(default_factory=list)
    steps: int = 0
    latency_ms: float = 0
    tokens: dict = field(default_factory=dict)
    cost: float = 0.0
    errors: list = field(default_factory=list)
    features_exercised: list = field(default_factory=list)

    missing_features: list = field(default_factory=list)
    deepseek_features: list = field(default_factory=list)

    # Extended data
    saver: Any = None


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Runner
# ═══════════════════════════════════════════════════════════════════════════════

def _build_system_prompt(agent_type: str) -> str:
    prompts = {
        "financial": (
            "你是具备CPA和CFA资质的资深财务分析师，20年行业经验，专精于互联网科技公司财务分析。\n\n"
            "【最终交付物要求 — 最重要！】\n"
            "你必须输出一份完整的、可交付给客户的专业财务分析报告，不只是工具调用总结。报告必须包含以下完整章节：\n"
            "一、公司概况与核心财务数据摘要（表格：营收/毛利/净利/总资产/总负债/权益/现金流，含同比变化%）\n"
            "二、关键财务比率全面分析（分盈利能力/偿债能力/运营效率/成长能力四个子章节，每个比率必须给出：具体数值 + 行业基准 + 评价 + 详细解读为什么这个数值重要，不要只列数字不解释）\n"
            "三、行业对比分析（表格：字节 vs 行业均值 vs 行业优秀线，含差距分析）\n"
            "四、综合财务健康评级（★★★★★格式，含评级说明）\n"
            "五、关键风险点识别（表格：风险等级 + 风险描述，至少5项风险）\n"
            "六、结论与建议\n"
            "报告末尾必须包含免责声明。\n\n"
            "【工作流程】\n"
            "1. 读取 financial_report.json 和 financial_report.md 两个文件\n"
            "2. 用 run_python_experiment 一次性批量计算所有财务比率（≥12项）\n"
            "3. 用 generate_chart 生成盈利能力柱状图，用 generate_financial_table 生成比率汇总表\n"
            "4. 搜索行业对比数据（最多2次）\n"
            "5. 给出综合财务健康评级，识别关键风险点\n"
            "6. 调用 save_result 保存报告，然后输出完整的分章节专业报告"
        ),
        "investment": (
            "你是CFA持证量化投资分析师，10年经验，坚持数据驱动决策和严格风险管理。\n\n"
            "【最终交付物要求 — 最重要！】\n"
            "你必须输出一份完整的、专业级投资分析报告，不只是工具调用总结。报告必须包含以下完整章节：\n"
            "一、宏观背景与行业环境（引用搜索到的政策/经济数据，分析对板块的影响）\n"
            "二、技术指标综合对比表（表格：每只股票所有指标并排对比，每个指标附解读）\n"
            "三、相关系数矩阵（表格 + 解读：分散化效果分析）\n"
            "四、个股深度分析（每只股票单独一节，至少200字分析，含技术面+基本面+目标价+止损位）\n"
            "五、综合投资建议（相对价值排序 + 操作策略表 + 关键观察指标 + 风险提示）\n"
            "报告末尾必须包含免责声明。\n\n"
            "【工作流程】\n"
            "1. 用 fetch_stock_data 获取至少3只真实股票数据（必选600519.SH+000858.SZ，period='6mo'），读取 stock_prices.csv\n"
            "2. 用 run_python_experiment 一次性计算：MA20/MA60/偏离度/波动率/夏普比率(无风险利率2%)/最大回撤/相关系数矩阵\n"
            "3. 搜索最新市场新闻和政策（最多2次），用 download_page 下载1篇深度分析\n"
            "4. 用 generate_chart 生成价格走势对比图（含MA线）\n"
            "5. 给出每只股票的买入/持有/卖出建议和12个月目标价\n"
            "6. 调用 save_result 保存报告，然后输出完整的分章节专业报告"
        ),
        "data_analysis": (
            "你是资深电商数据分析专家，10年头部电商平台数据总监经验，精通统计分析和商业智能。\n\n"
            "【最终交付物要求 — 最重要！】\n"
            "你必须输出一份完整的、可用于管理层汇报的专业数据分析报告，不只是工具调用总结。报告必须包含以下完整章节：\n"
            "一、数据概览（总订单数/总销售额/总销量/平均客单价/数据时间跨度）\n"
            "二、按产品类别分析（含完整排名表格+每个品类详细解读）\n"
            "三、按地区分析（含完整排名表格+每个地区详细解读）\n"
            "四、按客户类型分析（含表格+解读）\n"
            "五、月度趋势分析（含月度明细表格+趋势解读和异常说明）\n"
            "六、交叉分析：品类×地区销售额矩阵 + 品类×客户类型销售额矩阵（含洞察解读）\n"
            "七、行业趋势对比\n"
            "八、业务建议与行动方案（必须分短期/中期/长期三层，每层有具体目标和执行方法）\n"
            "九、总结（核心优势 + 增长机会点 + 预期提升空间）\n\n"
            "【工作流程】\n"
            "1. 读取 sales_data.csv\n"
            "2. 用 run_python_experiment 一次性完成所有分析（必须在一个代码块中打印所有结果！）\n"
            "3. 用 generate_chart 生成品类对比柱状图和地区分布饼图（至少2张）\n"
            "4. 搜索'2025年中国电商消费趋势'（最多2次）\n"
            "5. 给出具体、可量化、有时限的业务建议\n"
            "6. 调用 save_result 保存报告，然后输出完整的分章节专业报告"
        ),
        "director": (
            "你是拥有15年经验的资深影视策划和创意总监，参与过多部票房过10亿的项目开发，熟悉中国电影市场全流程。\n\n"
            "【最终交付物要求 — 最重要！】\n"
            "你必须输出一份完整的、可用于投资人路演的专业项目策划报告，不只是工具调用总结。报告必须包含以下完整章节：\n"
            "一、项目概述（项目名称/类型/核心概念/对标作品/差异化定位）\n"
            "二、创意发想过程（两轮发想+选择理由）\n"
            "三、市场研究（市场数据表格+对标分析+关键趋势）\n"
            "四、四维度专业评估：创意（含打分）+商业（含票房预测三区间+衍生品）+制作（预算分配表+选角建议表）+风险（含等级和应对）\n"
            "五、项目推进建议与时间表（含阶段/里程碑表格+风险应对策略表）\n"
            "六、总结与建议（核心优势+立项建议+优先级评级）\n\n"
            "【工作流程】\n"
            "1. 读取 movie_script.json 了解参考项目格式和行业数据\n"
            "2. 用 brainstorm_ideas 进行两轮创意发想（第一轮count=3新主题，第二轮count=3角色情节展开）\n"
            "3. 搜索'2026-2027 中国电影市场 票房趋势'（最多2次），下载1篇产业分析\n"
            "4. 从创意/商业/制作/风险四维度给出专业评估\n"
            "5. 给出具体的项目推进建议和时间表\n"
            "6. 调用 save_result 保存报告，然后输出完整的分章节专业报告"
        ),
    }
    return prompts.get(agent_type, prompts["data_analysis"])


def _get_task(agent_type: str) -> str:
    tasks = {
        "financial": (
            "全面分析字节跳动2025年财务报告。\n\n"
            "【最终输出格式 — 必须遵守！】\n"
            "在调用 save_result 之后，你必须将完整的专业财务分析报告作为最终回答输出。\n"
            "这意味着：不要只输出一个简短的\"任务完成总结\"，而是要输出一份包含以下所有章节的完整报告：\n"
            "一、公司概况与核心财务数据摘要（含表格）\n"
            "二、关键财务比率全面分析（每个比率：数值+行业基准+评价+解读）\n"
            "三、行业对比分析（表格：字节vs行业均值vs行业优秀线）\n"
            "四、综合财务健康评级\n"
            "五、关键风险点识别（表格，至少5项风险）\n"
            "六、结论与建议\n"
            "免责声明\n\n"
            "【操作步骤】\n"
            "1. 读取 financial_report.json 和 financial_report.md 两个文件获取完整财务数据。\n"
            "2. 使用 run_python_experiment 一次性计算所有关键财务比率（至少12项）："
            "ROE、ROA、毛利率、净利率、EBITDA利润率、资产负债率、流动比率、速动比率、"
            "利息保障倍数、存货周转率、应收账款周转率、总资产周转率、营收增长率、净利润增长率、现金流增长率。\n"
            "3. 使用 generate_chart 生成盈利能力对比柱状图（chart_type='bar'），"
            "使用 generate_financial_table 生成完整的财务比率汇总表。\n"
            "4. 搜索'字节跳动 2025 财务表现 行业对比'获取行业基准（最多搜索2次）。\n"
            "5. 基于所有数据给出综合财务健康评级（优秀/良好/一般/风险/严重风险），识别关键风险点。\n"
            "【必须执行】调用 save_result 保存报告到 financial_analysis_report_lc.txt，然后以完整的分章节专业报告作为最终回答。"
        ),
        "investment": (
            "进行真实股票投资分析。\n\n"
            "【最终输出格式 — 必须遵守！】\n"
            "在调用 save_result 之后，你必须将完整的投资分析报告作为最终回答输出。\n"
            "这意味着：不要只输出一个\"分析总结\"，而是要输出一份包含以下所有章节的完整报告：\n"
            "一、宏观背景与行业环境\n"
            "二、技术指标综合对比表（所有指标并排对比）\n"
            "三、相关系数矩阵（表格+解读）\n"
            "四、个股深度分析（每只股票至少200字分析，含目标价和止损位）\n"
            "五、综合投资建议（操作策略表+关键观察指标+风险提示）\n"
            "免责声明\n\n"
            "【操作步骤】\n"
            "1. 使用 fetch_stock_data 获取至少3只真实股票的价格数据："
            "必选：600519.SH（贵州茅台）、000858.SZ（五粮液），period='6mo'\n"
            "2. 同时读取 stock_prices.csv 作为补充数据。\n"
            "3. 使用 run_python_experiment 一次性计算所有技术指标："
            "MA20、MA60、日收益率、年化波动率、夏普比率（无风险利率2%）、最大回撤、偏离度、相关系数矩阵。\n"
            "4. 搜索'2025中国消费股 投资展望 政策'了解宏观背景（最多搜索2次），"
            "用 download_page 下载1篇最有价值的分析文章。\n"
            "5. 使用 generate_chart 生成价格走势对比图（含MA线），至少一张。\n"
            "6. 结合技术指标和宏观研究，给出每只股票的买入/持有/卖出建议和12个月目标价。\n"
            "【必须执行】调用 save_result 保存报告到 investment_report_lc.txt，然后以完整的分章节专业报告作为最终回答。"
        ),
        "data_analysis": (
            "深入分析电商销售数据。\n\n"
            "【最终输出格式 — 必须遵守！】\n"
            "在调用 save_result 之后，你必须将完整的数据分析报告作为最终回答输出。\n"
            "这意味着：不要只输出一个\"分析完成总结\"，而是要输出一份包含以下所有章节的完整报告：\n"
            "一、数据概览\n二、按产品类别分析（含排名表格+解读）\n"
            "三、按地区分析（含排名表格+解读）\n四、按客户类型分析（含表格+解读）\n"
            "五、月度趋势分析（含月度明细表+趋势解读）\n"
            "六、交叉分析：品类×地区矩阵 + 品类×客户类型矩阵（含解读）\n"
            "七、行业趋势对比\n八、业务建议与行动方案（分短期/中期/长期）\n九、总结\n\n"
            "【操作步骤】\n"
            "1. 读取 sales_data.csv 获取完整销售数据。\n"
            "2. 使用 run_python_experiment 一次性完成所有统计分析（在一个代码块中完成，不要分多次调用！）："
            "品类统计/地区分布/客户类型/月度趋势/Pareto分析/交叉分析矩阵。\n"
            "3. 使用 generate_chart 生成至少2张图表（品类对比柱状图 + 地区分布饼图）。\n"
            "4. 搜索'2025年中国电商消费趋势'了解行业背景（最多搜索2次）。\n"
            "【必须执行】调用 save_result 保存报告到 data_analysis_report_lc.txt，然后以完整的分章节专业报告作为最终回答。"
        ),
        "director": (
            "策划一部新电影项目，从创意到商业可行性全面评估。\n\n"
            "【最终输出格式 — 必须遵守！】\n"
            "在调用 save_result 之后，你必须将完整的项目策划报告作为最终回答输出。\n"
            "这意味着：不要只输出一个\"策划流程总结\"，而是要输出一份包含以下所有章节的完整报告：\n"
            "一、项目概述（项目名称/类型/核心概念/对标作品/差异化定位）\n"
            "二、创意发想过程（两轮发想+选择理由）\n"
            "三、市场研究（市场数据表格+对标分析+关键趋势）\n"
            "四、四维度专业评估（创意/商业/制作/风险，含打分和详细分析）\n"
            "五、项目推进建议与时间表（含阶段/里程碑表格+风险应对策略表）\n"
            "六、总结与建议（核心优势+立项建议+优先级评级）\n\n"
            "【操作步骤】\n"
            "1. 先读取 movie_script.json 了解参考项目格式和行业数据。\n"
            "2. 使用 brainstorm_ideas 进行两轮创意发想："
            "第一轮：科幻电影新主题创意（count=3），第二轮：角色和情节展开（count=3）。\n"
            "3. 搜索'2026-2027 中国电影市场 票房趋势'了解市场环境（最多搜索2次），"
            "用 download_page 下载1篇最相关的产业分析。\n"
            "4. 从创意/商业/制作/风险四个维度给出专业评估。\n"
            "5. 给出具体的项目推进建议和时间表。\n"
            "【必须执行】调用 save_result 保存报告到 director_report_lc.txt，然后以完整的分章节专业报告作为最终回答。"
        ),
    }
    return tasks.get(agent_type, tasks["data_analysis"])


def run_langchain_agent(agent_type: str, streaming: bool = True) -> LangChainAgentReport:
    """Run an agent using LangChain 1.x create_agent() with DeepSeek."""
    report = LangChainAgentReport(agent_type=agent_type)
    report.task = _get_task(agent_type)
    system_prompt = _build_system_prompt(agent_type)
    features = get_framework_features("LangChain")
    report.missing_features = features.features_missing
    report.deepseek_features = features.deepseek_specific_features

    # Initialize saver
    saver = RuntimeSaver("LangChain", agent_type, MODEL)
    saver.start(task=report.task, system_prompt=system_prompt)
    saver.set_features(features)
    report.saver = saver

    # Create model pointing to DeepSeek
    model = ChatOpenAI(
        model=MODEL,
        base_url="https://api.deepseek.com/v1",
        api_key=API_KEY,
        temperature=0.2,
        max_tokens=4096,
        timeout=120.0,
        extra_body={"thinking": {"type": "disabled"}},
        stream_usage=True,
    )

    # Build agent with timing middleware
    timing = TimingMiddleware(saver)
    agent = create_agent(
        model=model,
        tools=LANGCHAIN_TOOLS,
        system_prompt=system_prompt,
        middleware=[timing],
    )

    report.features_exercised = [
        "langchain_tool_decorator", "langchain_middleware",
        "langgraph_agent", "chatopenai_provider",
        "streaming" if streaming else "sync_mode",
    ]

    print(f"\n{'='*70}")
    print(f"  [LangChain] {agent_type.upper()} AGENT")
    print(f"  Model: {MODEL} | create_agent() + ChatOpenAI")
    print(f"  Features: {len(features.features_available)} available, "
          f"{len(features.features_missing)} missing (DeepSeek-specific)")
    print(f"{'='*70}")
    print(f"\nTask: {report.task[:100]}...\n")

    start = time.time()
    final_text = ""

    try:
        input_msg = {"messages": [{"role": "user", "content": report.task}]}

        if streaming:
            # Stream tokens in real-time
            content_parts: list[str] = []
            for chunk in agent.stream(input_msg, stream_mode="messages"):
                token, metadata = chunk
                if isinstance(token, AIMessage) and token.content:
                    c = token.content if isinstance(token.content, str) else str(token.content or "")
                    if c:
                        content_parts.append(c)
                        print(c, end="", flush=True)
            final_text = "".join(content_parts)
        else:
            result = agent.invoke(input_msg)
            messages = result.get("messages", result) if isinstance(result, dict) else result
            # Extract final AI message
            all_msgs = messages if isinstance(messages, list) else messages.get("messages", [])
            for msg in reversed(all_msgs):
                if isinstance(msg, AIMessage) and msg.content:
                    final_text = msg.content if isinstance(msg.content, str) else str(msg.content)
                    break
            print(final_text if final_text else "(no output)")

        # Count tool calls from result
        all_msgs = saver.dump.messages if saver.dump.messages else []
        tool_call_count = 0
        for msg in all_msgs:
            if isinstance(msg, dict):
                for tc in msg.get("tool_calls", []) or []:
                    tool_call_count += 1
                    report.tool_calls.append({
                        "name": tc.get("function", {}).get("name", "unknown"),
                        "ok": True,
                        "result": str(tc.get("function", {}).get("arguments", ""))[:100],
                    })

        report.steps = timing.call_count
        report.tokens = {
            "prompt_tokens": saver.dump.token_usage_total.prompt_tokens,
            "completion_tokens": saver.dump.token_usage_total.completion_tokens,
            "total_tokens": saver.dump.token_usage_total.total_tokens,
        }
        report.cost = saver.dump.total_cost_cny

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        report.errors.append(error_msg)
        final_text = f"ERROR: {e}"

    report.latency_ms = (time.time() - start) * 1000
    report.final_output = final_text

    # Save comprehensive runtime data (once, after all branches)
    saver.finish(final_output=final_text,
                 error=report.errors[0] if report.errors else None)
    saved_dir = saver.save()

    print(f"\n{'─'*70}")
    print(f"  Latency: {report.latency_ms:.0f}ms | Cost: CNY {report.cost:.6f}")
    print(f"  Steps: {report.steps} | Features: {len(report.features_exercised)} exercised")
    print(f"  DeepSeek-specific features available: {len(report.deepseek_features)}")
    if report.errors:
        print(f"  Errors: {report.errors}")
    print(f"  Runtime data: {saved_dir}")
    print(f"{'─'*70}")

    return report


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    agent_type = sys.argv[1] if len(sys.argv) > 1 else "financial"
    report = run_langchain_agent(agent_type, streaming=True)
    print(f"\nReport saved to {OUTPUT_DIR}/")
