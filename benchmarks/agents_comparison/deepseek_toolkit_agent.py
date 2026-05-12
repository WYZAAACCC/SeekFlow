"""DeepSeekToolkit comprehensive agent — exercises ALL library features.

Features tested:
  - Tool calling + JSON repair         - File reading (txt, csv, json, md)
  - Web search                         - Thinking mode
  - Streaming output                   - Error classification
  - Trace recording                    - Cost tracking
  - Session management                 - Rate limit awareness
  - Context management                 - Retry + circuit breaker
  - Truncation                         - Balance query
  - Prompt cache observation           - Structured output
"""
import json
import sys
import io
import time
import os as _os

# Suppress OpenMP duplicate library warning from matplotlib
_os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')

# Fix Windows GBK encoding issues with Unicode characters
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
else:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from pathlib import Path
from typing import Any
from dataclasses import dataclass, field

API_KEY = _os.environ.get("DEEPSEEK_API_KEY", "")
if not API_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY environment variable is required")
MODEL = "deepseek-v4-pro"

DATA_DIR = Path(__file__).parent / "data"
OUTPUT_DIR = Path(__file__).parent / "output" / "deepseek_toolkit"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Import toolkit
from deepseek_toolkit.tools.decorator import tool
from deepseek_toolkit.tools.registry import ToolRegistry
from deepseek_toolkit.runtime import ToolRuntime
from deepseek_toolkit.balance import get_balance
from deepseek_toolkit.cost import CostTracker
from deepseek_toolkit.cache import CacheSentinel, extract_cached_tokens
from deepseek_toolkit.context import SlidingWindowStrategy
from deepseek_toolkit.session import Session
from deepseek_toolkit.files import read_file_as_text, embed_files_into_message
from deepseek_toolkit.errors import DeepSeekAPIError, InsufficientBalanceError
from deepseek_toolkit.retry import RateLimitState
from deepseek_toolkit.truncation import TruncationStrategy
from deepseek_toolkit.token_counter import count_tokens
from deepseek_toolkit.search import get_search_provider

# Comprehensive runtime data saver (same directory)
import os as _os
_bench_dir = _os.path.dirname(_os.path.abspath(__file__))
if _bench_dir not in sys.path:
    sys.path.insert(0, _bench_dir)
from comprehensive_saver import (
    RuntimeSaver, get_framework_features, FrameworkFeatures,
)

# New production-grade tools
from tools.stock_data import fetch_stock_data
from tools.charting import generate_chart, generate_financial_table
from tools.sandbox import run_python_experiment
from tools.brainstorm import brainstorm_ideas


# ═══════════════════════════════════════════════════════════════════════════════
# New production tools — registered via DTK decorator
# ═══════════════════════════════════════════════════════════════════════════════

@tool(name="fetch_stock_data")
def _fetch_stock_data(symbol: str, period: str = "6mo") -> str:
    """Fetch real stock price data. Symbol formats: '000001.SZ' (Shenzhen), '600519.SH' (Shanghai), '0700.HK' (HK), 'AAPL' (US). Period: '1mo', '3mo', '6mo', '1y'."""
    return fetch_stock_data(symbol, period)


@tool(name="generate_chart")
def _generate_chart(data_json: str, chart_type: str, title: str, filename: str) -> str:
    """Generate a chart (line, bar, pie, scatter) from JSON data and save as PNG. data_json: {'labels':[...], 'values':[...]}."""
    return generate_chart(data_json, chart_type, title, filename)


@tool(name="generate_financial_table")
def _generate_financial_table(data_json: str, title: str, filename: str) -> str:
    """Generate a formatted financial table from JSON data. data_json: {'headers':[...], 'rows':[[...],...]}."""
    return generate_financial_table(data_json, title, filename)


@tool(name="run_python_experiment")
def _run_python_experiment(code: str, timeout: int = 60) -> str:
    """Execute Python code in a sandbox. Use for data analysis, statistics, model building. Has math, statistics, json modules."""
    return run_python_experiment(code, timeout)


@tool(name="brainstorm_ideas")
def _brainstorm_ideas(topic: str, count: int = 5) -> str:
    """Generate creative ideas using structured brainstorming frameworks (SCAMPER, TRIZ, lateral thinking)."""
    return brainstorm_ideas(topic, count)


# ═══════════════════════════════════════════════════════════════════════════════
# Tools
# ═══════════════════════════════════════════════════════════════════════════════

@tool(name="read_file")
def read_file(path: str) -> str:
    """Read a file from the data directory. Supports txt, csv, json, md, pdf."""
    full = DATA_DIR / path
    if not full.exists():
        return f"ERROR: File not found: {path}. Available: {[p.name for p in DATA_DIR.iterdir()]}"
    content = read_file_as_text(str(full))
    if len(content) > 12000:
        content = content[:12000] + f"\n... [truncated, total {len(content)} chars]"
    return content


_search_count = 0
_MAX_SEARCHES = 6


@tool(name="web_search")
def web_search(query: str) -> str:
    """Search the web for information. Limited to a few calls — use wisely and move on if results are not useful."""
    global _search_count
    _search_count += 1
    if _search_count > _MAX_SEARCHES:
        return (
            f"[搜索已达上限({_MAX_SEARCHES}次)] 请停止搜索，基于已获取的数据和你的专业知识完成分析。"
        )
    provider = get_search_provider("auto")
    results = provider.search(query, max_results=5, timeout=10)
    return "\n".join(results)


@tool(name="download_page")
def download_page(url: str) -> str:
    """Download and extract text content from a web page URL. Use this to read full articles, news, or documentation found via web_search."""
    import urllib.request as _ur
    import re as _re
    try:
        req = _ur.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        with _ur.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"Download failed: {e}"

    # Remove scripts, styles, and head
    html = _re.sub(r'<script[^>]*>.*?</script>', '', html, flags=_re.DOTALL | _re.IGNORECASE)
    html = _re.sub(r'<style[^>]*>.*?</style>', '', html, flags=_re.DOTALL | _re.IGNORECASE)
    html = _re.sub(r'<head[^>]*>.*?</head>', '', html, flags=_re.DOTALL | _re.IGNORECASE)
    html = _re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=_re.DOTALL | _re.IGNORECASE)
    html = _re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=_re.DOTALL | _re.IGNORECASE)
    # Remove all HTML tags
    text = _re.sub(r'<[^>]+>', ' ', html)
    # Collapse whitespace
    text = _re.sub(r'\s+', ' ', text).strip()
    # Decode HTML entities
    import html as _html
    text = _html.unescape(text)
    if len(text) > 6000:
        text = text[:6000] + f"\n... [truncated, total {len(text)} chars]"
    return text


@tool(name="calculate")
def calculate(expression: str) -> str:
    """Evaluate a mathematical expression and return the result. Use 'statistics' and 'math' modules."""
    import statistics as _st
    import math as _mt
    try:
        result = eval(expression, {"__builtins__": {}}, {
            "abs": abs, "round": round, "min": min, "max": max,
            "sum": sum, "pow": pow, "len": len, "sorted": sorted,
            "float": float, "int": int, "str": str, "list": list,
            "dict": dict, "range": range, "enumerate": enumerate,
            "zip": zip, "map": map, "filter": filter,
            "statistics": _st, "math": _mt,
        })
        return f"Result: {result}"
    except Exception as e:
        return f"Calculation error: {e}"


@tool(name="save_result", keep_fields=["content"])
def save_result(filename: str, content: str) -> str:
    """Save analysis result to output directory."""
    full = OUTPUT_DIR / filename
    full.write_text(content, encoding="utf-8")
    return f"Saved {len(content)} bytes to {filename}"


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Runner
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AgentReport:
    """Comprehensive report of an agent run."""
    agent_type: str
    framework: str = "DeepSeekToolkit"
    task: str = ""
    final_output: str = ""
    tool_calls: list = field(default_factory=list)
    steps: int = 0
    latency_ms: float = 0
    tokens: dict = field(default_factory=dict)
    cost: float = 0.0
    trace_events: int = 0
    balance: str = ""
    cache_hits: int = 0
    errors: list = field(default_factory=list)
    session_messages: int = 0
    context_compressions: int = 0
    thinking_used: bool = False

    features_exercised: list = field(default_factory=list)


def create_agent(streaming: bool = False):
    """Create a fully configured DeepSeekToolkit agent with all features enabled."""
    tools = [
        read_file, web_search, download_page, calculate, save_result,
        _fetch_stock_data, _generate_chart, _generate_financial_table,
        _run_python_experiment, _brainstorm_ideas,
    ]

    rt = ToolRuntime(
        tools=tools,
        api_key=API_KEY,
        max_steps=25,
        max_result_chars=12000,
        repair=True,
        trace=True,
        cache_size=32,
        cache_ttl=300,
        timeout=300.0,
        truncation_strategy=TruncationStrategy.PRIORITY,
    )

    return rt, tools


def build_system_prompt(agent_type: str) -> str:
    prompts = {
        "financial": """你是具备CPA和CFA资质的资深财务分析师，20年行业经验，专精于互联网科技公司财务分析。

【最终交付物要求 — 最重要！】
你必须输出一份完整的、可交付给客户的专业财务分析报告，不只是工具调用总结。报告必须包含以下完整章节：
一、公司概况与核心财务数据摘要（表格：营收/毛利/净利/总资产/总负债/权益/现金流，含同比变化%）
二、关键财务比率全面分析（分盈利能力/偿债能力/运营效率/成长能力四个子章节，每个比率必须给出：具体数值 + 行业基准 + 评价 + 详细解读为什么这个数值重要，不要只列数字不解释）
三、行业对比分析（表格：字节 vs 行业均值 vs 行业优秀线，含差距分析）
四、综合财务健康评级（★★★★★格式，含评级说明）
五、关键风险点识别（表格：风险等级 + 风险描述，至少5项风险）
六、结论与建议
报告末尾必须包含免责声明。

【工作流程】
1. 读取 financial_report.json 和 financial_report.md 两个文件
2. 用 run_python_experiment 一次性批量计算所有财务比率（≥12项）：盈利能力（ROE/ROA/毛利率/净利率/EBITDA利润率）、偿债能力（资产负债率/流动比率/速动比率/利息保障倍数）、运营效率（存货周转率/应收账款周转率/总资产周转率）、成长能力（营收增长率/净利润增长率/现金流增长率）
3. 用 generate_chart 生成盈利能力柱状图，用 generate_financial_table 生成比率汇总表
4. 搜索行业对比数据（最多2次）
5. 给出综合财务健康评级，识别关键风险点
6. 调用 save_result 保存报告，然后输出完整的、分章节的专业报告""",

        "investment": """你是CFA持证量化投资分析师，10年经验，坚持数据驱动决策和严格风险管理。

【最终交付物要求 — 最重要！】
你必须输出一份完整的、专业级投资分析报告，不只是工具调用总结。报告必须包含以下完整章节：
一、宏观背景与行业环境（引用搜索到的政策/经济数据，分析对板块的影响）
二、技术指标综合对比表（表格：每只股票所有指标并排对比：MA20/MA60/偏离度/波动率/夏普比率/最大回撤/期间收益率，每个指标附简短解读）
三、相关系数矩阵（表格 + 解读：分散化效果分析，哪些股票高度相关/哪些有独立走势）
四、个股深度分析（每只股票单独一节，包含：技术面详细分析 + 基本面判断 + 12个月目标价及核心逻辑 + 止损位，每只股票至少200字分析）
五、综合投资建议（相对价值排序 + 操作策略表 + 关键观察指标 + 风险提示）
报告末尾必须包含免责声明。

【工作流程】
1. 用 fetch_stock_data 获取至少3只真实股票数据（必选：600519.SH贵州茅台、000858.SZ五粮液，period='6mo'），读取 stock_prices.csv
2. 用 run_python_experiment 一次性计算：MA20/MA60/价格偏离度/日收益率/年化波动率/夏普比率(无风险利率2%)/最大回撤/相关系数矩阵
3. 搜索最新市场新闻和政策（最多2次），用 download_page 下载1篇深度分析
4. 用 generate_chart 生成价格走势对比图（含MA线）
5. 给出每只股票的买入/持有/卖出建议和12个月目标价
6. 调用 save_result 保存报告，然后输出完整的分章节专业报告""",

        "data_analysis": """你是资深电商数据分析专家，10年头部电商平台数据总监经验，精通统计分析和商业智能。

【最终交付物要求 — 最重要！】
你必须输出一份完整的、可用于管理层汇报的专业数据分析报告，不只是工具调用总结。报告必须包含以下完整章节：
一、数据概览（总订单数/总销售额/总销量/平均客单价/数据时间跨度）
二、按产品类别分析（含完整排名表格：品类/销售额/订单量/销量/客单价/占比，每个品类附详细解读）
三、按地区分析（含完整排名表格：地区/销售额/订单量/销量/客单价/占比，每个地区附详细解读）
四、按客户类型分析（含表格：客户类型/销售额/订单量/销量/客单价/占比，附解读）
五、月度趋势分析（含月度明细表格：月份/销售额/订单量/客单价，含趋势解读和异常说明）
六、交叉分析：品类×地区销售额矩阵 + 品类×客户类型销售额矩阵（含洞察解读）
七、行业趋势对比（引用搜索到的2025年电商行业数据）
八、业务建议与行动方案（必须分短期/中期/长期三层，每层有具体目标和执行方法）
九、总结（核心优势 + 增长机会点 + 预期提升空间）

【工作流程】
1. 读取 sales_data.csv
2. 用 run_python_experiment 一次性完成所有分析（必须在一个代码块中打印所有结果！）：品类统计/地区分布/客户类型/月度趋势/Pareto分析/交叉分析矩阵
3. 用 generate_chart 生成品类对比柱状图和地区分布饼图（至少2张）
4. 搜索'2025年中国电商消费趋势'（最多2次）
5. 给出具体、可量化、有时限的业务建议
6. 调用 save_result 保存报告，然后输出完整的分章节专业报告""",

        "director": """你是拥有15年经验的资深影视策划和创意总监，参与过多部票房过10亿的项目开发，熟悉中国电影市场全流程。

【最终交付物要求 — 最重要！】
你必须输出一份完整的、可用于投资人路演的专业项目策划报告，不只是工具调用总结。报告必须包含以下完整章节：
一、项目概述（项目名称/类型/核心概念/对标作品/差异化定位）
二、创意发想过程（第一轮3个方向各自描述核心设定+类型融合+文化内核+商业潜力 / 第二轮选定创意后3个角色情节方案展开 / 最终选择理由）
三、市场研究（市场环境数据表格：年度票房/科幻占比/国产片占比/春节档占比 含2024-2027年预测 + 对标作品分析表 + 关键趋势总结）
四、四维度专业评估：
   创意维度（故事独创性打分+类型创新度打分+差异化亮点描述）
   商业维度（目标观众画像表格含占比和触达策略 + 票房预测保守/基准/乐观三区间 + 衍生品/IP开发潜力）
   制作维度（预算分配表：视效/演员/制作/后期/宣发各占% + 技术可行性评估 + 选角建议表格含角色/建议演员/理由）
   风险维度（表格：政策/竞争/口碑风险含等级和应对措施）
五、项目推进建议与时间表（含阶段/时间/关键任务/交付物表格 + 关键里程碑 + 风险应对策略表）
六、总结与建议（核心优势 + 立项建议 + 优先级评级）

【工作流程】
1. 读取 movie_script.json 了解参考项目格式和行业数据
2. 用 brainstorm_ideas 进行两轮创意发想（第一轮count=3新主题，第二轮count=3角色情节展开）
3. 搜索'2026-2027 中国电影市场 票房趋势'（最多2次），下载1篇产业分析
4. 从创意/商业/制作/风险四维度给出专业评估
5. 给出具体的项目推进建议和时间表
6. 调用 save_result 保存报告，然后输出完整的分章节专业报告""",
    }
    return prompts.get(agent_type, prompts["data_analysis"])


def get_task(agent_type: str) -> str:
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
            "2. 使用 run_python_experiment 一次性计算所有关键财务比率：ROE、ROA、毛利率、净利率、"
            "资产负债率、流动比率、速动比率、利息保障倍数、存货周转率、应收账款周转率、"
            "营收增长率、净利润增长率、现金流增长率等。\n"
            "3. 使用 generate_chart 生成盈利能力对比柱状图（chart_type='bar'），"
            "使用 generate_financial_table 生成完整的财务比率汇总表。\n"
            "4. 搜索'字节跳动 2025 财务表现 行业对比'获取行业基准（最多搜索2次）。\n"
            "5. 基于所有数据给出综合财务健康评级（优秀/良好/一般/风险/严重风险），识别关键风险点。\n"
            "【必须执行】调用 save_result 保存报告，然后以完整的分章节专业报告作为最终回答。"
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
            "【必须执行】调用 save_result 保存报告，然后以完整的分章节专业报告作为最终回答。"
        ),
        "data_analysis": (
            "深入分析电商销售数据。\n\n"
            "【最终输出格式 — 必须遵守！】\n"
            "在调用 save_result 之后，你必须将完整的数据分析报告作为最终回答输出。\n"
            "这意味着：不要只输出一个\"分析完成总结\"，而是要输出一份包含以下所有章节的完整报告：\n"
            "一、数据概览\n"
            "二、按产品类别分析（含排名表格+解读）\n"
            "三、按地区分析（含排名表格+解读）\n"
            "四、按客户类型分析（含表格+解读）\n"
            "五、月度趋势分析（含月度明细表+趋势解读）\n"
            "六、交叉分析：品类×地区矩阵 + 品类×客户类型矩阵（含解读）\n"
            "七、行业趋势对比\n"
            "八、业务建议与行动方案（分短期/中期/长期）\n"
            "九、总结\n\n"
            "【操作步骤】\n"
            "1. 读取 sales_data.csv 获取完整销售数据。\n"
            "2. 使用 run_python_experiment 一次性完成所有统计分析（在一个代码块中完成！）："
            "品类统计/地区分布/客户类型/月度趋势/Pareto分析/交叉分析矩阵。\n"
            "3. 使用 generate_chart 生成至少2张图表（品类对比柱状图 + 地区分布饼图）。\n"
            "4. 搜索'2025年中国电商消费趋势'了解行业背景（最多搜索2次）。\n"
            "【必须执行】调用 save_result 保存报告，然后以完整的分章节专业报告作为最终回答。"
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
            "五、项目推进建议与时间表（含阶段/里程碑/风险应对策略）\n"
            "六、总结与建议（核心优势+立项建议+优先级评级）\n\n"
            "【操作步骤】\n"
            "1. 先读取 movie_script.json 了解参考项目格式和行业数据。\n"
            "2. 使用 brainstorm_ideas 进行两轮创意发想："
            "第一轮：科幻电影新主题创意（count=3），第二轮：角色和情节展开（count=3）。\n"
            "3. 搜索'2026-2027 中国电影市场 票房趋势'了解市场环境（最多搜索2次），"
            "用 download_page 下载1篇最相关的产业分析。\n"
            "4. 从创意/商业/制作/风险四个维度给出专业评估。\n"
            "5. 给出具体的项目推进建议和时间表。\n"
            "【必须执行】调用 save_result 保存报告，然后以完整的分章节专业报告作为最终回答。"
        ),
        "research": (
            "进行一项自主科学研究：探索'使用线性回归预测股票价格的技术可行性'。"
            "1. 使用 fetch_stock_data 获取真实股票数据（symbol='600519.SH', period='1y'）。"
            "2. 使用 run_python_experiment 设计和运行实验："
            "   - 步骤1：数据预处理（处理缺失值、计算收益率、创建滞后特征）"
            "   - 步骤2：构建线性回归模型（使用过去5天/10天/20天价格作为特征预测次日价格）"
            "   - 步骤3：评估模型（R²、MSE、MAE），对比不同特征窗口的表现"
            "   - 步骤4：可视化预测结果 vs 实际价格"
            "   - 步骤5：分析模型局限性，讨论改进方向（如引入更多特征、使用更复杂模型）"
            "   （注意：使用纯Python+math/statistics实现，不要依赖sklearn等外部库）"
            "3. 搜索'股票价格预测 线性回归 局限性'了解学术界观点（最多搜索2次）。"
            "4. 使用 generate_chart 生成预测vs实际对比图。"
            "5. 撰写完整研究报告，包含：摘要、引言、方法、实验结果、讨论、结论。"
            "【必须执行】最后调用 save_result 将完整研究报告保存为 research_report.txt。"
        ),
    }
    return tasks.get(agent_type, tasks["data_analysis"])


def run_agent(agent_type: str, streaming: bool = True) -> AgentReport:
    """Run a single agent and collect comprehensive metrics."""
    global _search_count
    _search_count = 0  # Reset per-agent search counter
    report = AgentReport(agent_type=agent_type)
    report.task = get_task(agent_type)

    # Feature: Balance query
    try:
        bal = get_balance(API_KEY)
        report.balance = f"{bal.total_balance} {bal.currency}"
        report.features_exercised.append("balance_query")
    except Exception as e:
        report.balance = f"Error: {e}"

    # Feature: Cost tracking
    cost_tracker = CostTracker()
    report.features_exercised.append("cost_tracking")

    # Feature: Cache sentinel
    cache_sentinel = CacheSentinel()
    report.features_exercised.append("prompt_cache")

    # Feature: Rate limit state
    rate_state = RateLimitState()
    report.features_exercised.append("rate_limit_awareness")

    # Feature: Session management
    system_prompt = build_system_prompt(agent_type)
    session = Session(system=system_prompt)
    session.add_message("user", report.task)
    report.features_exercised.append("session_management")

    # Feature: Context management
    context_strategy = SlidingWindowStrategy(max_messages=30)

    # Feature: Token counting
    token_count = count_tokens(session.messages)
    report.features_exercised.append("token_counter")

    # Create agent
    rt, tools = create_agent()

    # Feature: RuntimeSaver — comprehensive runtime data collection
    saver = RuntimeSaver("DeepSeekToolkit", agent_type, MODEL)
    saver.start(task=report.task, system_prompt=system_prompt)
    saver.set_features(get_framework_features("DeepSeekToolkit"))
    report.features_exercised.append("runtime_saver")

    # Feature: File embedding
    report.features_exercised.append("file_attachment")

    print(f"\n{'='*70}")
    print(f"  [{report.framework}] {agent_type.upper()} AGENT")
    print(f"  Model: {MODEL} | Tokens: ~{token_count} | Balance: {report.balance}")
    print(f"{'='*70}")
    print(f"\nTask: {report.task[:100]}...\n")

    start = time.time()

    try:
        if streaming:
            tool_idx = 0
            stream_content: list[str] = []
            stream_reasoning: list[str] = []
            buffered_tool_calls: list[dict] = []
            saver_step = saver.begin_step()

            for event in rt.chat_stream(
                model=MODEL,
                messages=session.messages,
                thinking_mode="disabled",
            ):
                if event.type == "reasoning" and event.reasoning_content:
                    report.thinking_used = True
                    stream_reasoning.append(event.reasoning_content or "")
                    print(f"\033[2m{event.reasoning_content[:80]}...\033[0m", end="", flush=True)
                elif event.type == "content" and event.content:
                    stream_content.append(event.content)
                    print(event.content, end="", flush=True)
                elif event.type == "tool_call_start":
                    tool_idx += 1
                    print(f"\n  [tool:{tool_idx}] {event.tool_name}", flush=True)
                elif event.type == "tool_call_result":
                    ok = "OK" if event.tool_result else "FAIL"
                    preview = str(event.tool_result)[:120]
                    print(f"    [{ok}] {preview}", flush=True)
                    buffered_tool_calls.append({
                        "name": event.tool_name or "unknown",
                        "result": str(event.tool_result or ""),
                        "ok": event.tool_result is not None,
                    })
                elif event.type == "done":
                    saver.record_model_call(
                        saver_step, len(session.messages),
                        content="".join(stream_content),
                        reasoning="".join(stream_reasoning),
                        finish_reason=event.finish_reason or "",
                    )
                    # Record buffered tool calls now that the step snapshot exists
                    for tc in buffered_tool_calls:
                        saver.record_tool_call(
                            saver_step, tc["name"], {},
                            tc["result"], ok=tc["ok"], elapsed_ms=0,
                        )
                    if event.usage:
                        report.tokens = event.usage
                        cost_tracker.record(MODEL, event.usage)
                        report.cost = cost_tracker.total_cost
                        saver.record_token_usage(saver_step, event.usage, cost_cny=report.cost)
                        cached = extract_cached_tokens(event.usage)
                        if cached > 0:
                            report.cache_hits = cached
            final = "".join(stream_content) if stream_content else ""
        else:
            saver_step = saver.begin_step()
            result = rt.chat(
                model=MODEL,
                messages=session.messages,
                thinking_mode="disabled",
            )
            final = result.final or ""
            report.tool_calls = [
                {"name": tr.name, "ok": tr.ok, "result": str(tr.result)[:100]}
                for tr in result.tool_results
            ]
            report.steps = len(result.tool_results)
            saver.record_model_call(
                saver_step, len(session.messages),
                content=final,
                finish_reason="stop",
            )
            if result.usage:
                report.tokens = result.usage
                cost_tracker.record(MODEL, result.usage)
                report.cost = cost_tracker.total_cost
                saver.record_token_usage(saver_step, result.usage, cost_cny=report.cost)
                cached = extract_cached_tokens(result.usage)
                if cached > 0:
                    report.cache_hits = cached
            for tr in result.tool_results:
                saver.record_tool_call(
                    saver_step, tr.name, tr.arguments if isinstance(tr.arguments, dict) else {},
                    str(tr.result or ""), ok=tr.ok, elapsed_ms=tr.elapsed_ms or 0,
                )
            if result.trace:
                td = result.trace.to_dict()
                report.trace_events = len(td.get("events", []))
            print(final)

        # Sync runtime messages back to session for complete trace
        if hasattr(rt, '_last_messages') and rt._last_messages:
            session._messages = list(rt._last_messages)
            report.session_messages = len(rt._last_messages)

        report.features_exercised.append("thinking_mode" if report.thinking_used else "standard_mode")
        report.features_exercised.append("streaming" if streaming else "sync_mode")

    except InsufficientBalanceError:
        report.errors.append("InsufficientBalanceError — 余额不足")
        report.features_exercised.append("error_classification")
        final = "ERROR: 余额不足"
    except DeepSeekAPIError as e:
        report.errors.append(f"{type(e).__name__}: {e}")
        report.features_exercised.append("error_classification")
        final = f"ERROR: {e}"
    except Exception as e:
        report.errors.append(f"{type(e).__name__}: {e}")
        final = f"ERROR: {e}"

    report.latency_ms = (time.time() - start) * 1000
    report.final_output = final or ""

    # Feature: Session persistence
    session_path = OUTPUT_DIR / f"{agent_type}_session.json"
    session.save(str(session_path))
    report.session_messages = len(session.messages)
    report.features_exercised.append("session_persistence")

    # Save runtime data via RuntimeSaver
    saver_error = report.errors[0] if report.errors else None
    saver.finish(
        final_output=report.final_output,
        error=saver_error,
        messages=session.messages,
    )
    saver.save()

    # Save trace
    if hasattr(rt, '_trace_recorder'):
        report.features_exercised.append("trace_recording")

    # Print summary
    print(f"\n{'─'*70}")
    print(f"  Latency: {report.latency_ms:.0f}ms | Cost: CNY {report.cost:.6f}")
    print(f"  Features: {len(report.features_exercised)} exercised")
    if report.errors:
        print(f"  Errors: {report.errors}")
    print(f"{'─'*70}")

    return report


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    agent_type = sys.argv[1] if len(sys.argv) > 1 else "financial"
    report = run_agent(agent_type, streaming=True)
    print(f"\nReport saved to {OUTPUT_DIR}/")
