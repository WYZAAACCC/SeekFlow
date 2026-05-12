"""CrewAI 1.14.4 agent — uses Agent/Task/Crew with LLM(base_url) → DeepSeek.

Tests CrewAI's agent capabilities with DeepSeek:
  - LLM(base_url="https://api.deepseek.com/v1") for DeepSeek
  - Agent(role, goal, backstory, tools, llm) model
  - Task(description, expected_output, agent)
  - Crew(agents, tasks, process=Process.sequential)
  - Token usage via CrewOutput.token_usage
  - Streaming via crew.stream=True
  - Comprehensive runtime data saving
"""
import json
import sys
import io
import time
import re
import os
import urllib.request
import urllib.parse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

# Suppress OpenMP duplicate library warning from matplotlib
os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')

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
OUTPUT_DIR = Path(__file__).parent / "output" / "crewai"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# CrewAI imports
from crewai import Agent, Task, Crew, Process, LLM
from crewai.tools import tool as crewai_tool

# Comprehensive saver
import os as _os
_bench_dir = _os.path.dirname(_os.path.abspath(__file__))
if _bench_dir not in sys.path:
    sys.path.insert(0, _bench_dir)
from comprehensive_saver import (
    RuntimeSaver, FrameworkFeatures, get_framework_features,
)


# ═══════════════════════════════════════════════════════════════════════════════
# Tools — using CrewAI's @tool decorator
# ═══════════════════════════════════════════════════════════════════════════════

@crewai_tool
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


@crewai_tool
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
        # Extract title from <h2><a>...</a></h2>
        title_match = re.search(r"<h2[^>]*><a[^>]*>(.*?)</a></h2>", section, re.DOTALL)
        title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""
        # Extract URL from <h2><a href="...">
        url_match = re.search(r"<h2[^>]*><a[^>]*href=\"(https?://[^\"]+)\"", section)
        page_url = url_match.group(1) if url_match else ""
        # Extract snippet
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


@crewai_tool
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


@crewai_tool
def save_result(filename: str, content: str) -> str:
    """Save analysis result to output directory."""
    full = OUTPUT_DIR / filename
    full.write_text(content, encoding="utf-8")
    return f"Saved {len(content)} bytes to {filename}"


@crewai_tool
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

# Register as CrewAI tools
@crewai_tool
def fetch_stock_data_crew(symbol: str, period: str = "6mo") -> str:
    """Fetch real stock price data. Symbol formats: '000001.SZ' (Shenzhen), '600519.SH' (Shanghai). Period: '1mo','3mo','6mo','1y'."""
    return fetch_stock_data(symbol, period)


@crewai_tool
def generate_chart_crew(data_json: str, chart_type: str, title: str, filename: str) -> str:
    """Generate a chart (line, bar, pie, scatter) and save as PNG. data_json: {'labels':[...], 'values':[...]}."""
    return generate_chart(data_json, chart_type, title, filename)


@crewai_tool
def generate_financial_table_crew(data_json: str, title: str, filename: str) -> str:
    """Generate a formatted financial table. data_json: {'headers':[...], 'rows':[[...],...]}."""
    return generate_financial_table(data_json, title, filename)


@crewai_tool
def run_python_experiment_crew(code: str, timeout: int = 60) -> str:
    """Execute Python code in a sandbox. Use for data analysis, statistics. Has math, statistics, json modules."""
    return run_python_experiment(code, timeout)


@crewai_tool
def brainstorm_ideas_crew(topic: str, count: int = 5) -> str:
    """Generate creative ideas using brainstorming frameworks (SCAMPER, TRIZ, lateral thinking)."""
    return brainstorm_ideas(topic, count)


CREWAI_TOOLS = [
    read_file, web_search, download_page, calculate, save_result,
    fetch_stock_data_crew, generate_chart_crew, generate_financial_table_crew,
    run_python_experiment_crew, brainstorm_ideas_crew,
]


# ═══════════════════════════════════════════════════════════════════════════════
# Agent definitions — role/goal/backstory per agent type
# ═══════════════════════════════════════════════════════════════════════════════

AGENT_DEFINITIONS = {
    "financial": {
        "role": "资深财务分析师",
        "goal": "输出一份完整的、可交付给客户的专业财务分析报告，包含公司概况、15+项财务比率深度分析、行业对比、风险识别和投资建议",
        "backstory": (
            "你是具备CPA和CFA资质的资深财务分析师，拥有20年行业经验，专精于互联网科技公司财务分析。"
            "你输出的每一份报告都必须是客户可以直接使用的完整交付物，永远不只是摘要。"
            "你的报告结构永远是：一、公司概况与核心财务数据摘要（含表格）→ "
            "二、关键财务比率全面分析（每个比率：数值+行业基准+评价+深度解读）→ "
            "三、行业对比分析（表格+差距分析）→ 四、综合财务健康评级 → "
            "五、关键风险点识别（至少5项）→ 六、结论与建议 → 免责声明。"
            "工作流程：1)读取两个财务数据文件 2)用run_python_experiment批量计算12+财务比率"
            "（ROE/ROA/毛利率/净利率/EBITDA利润率/资产负债率/流动比率/速动比率/"
            "利息保障倍数/存货周转率/应收账款周转率/总资产周转率/"
            "营收增长率/净利润增长率/现金流增长率）"
            "3)用generate_chart生成盈利能力柱状图，用generate_financial_table生成比率汇总表 "
            "4)搜索行业对比数据(最多2次) 5)给出综合财务健康评级 6)用save_result保存报告。"
        ),
    },
    "investment": {
        "role": "量化投资分析师",
        "goal": "输出一份完整的、专业级投资分析报告，包含宏观背景、技术指标对比、相关系数矩阵、个股深度分析和具体操作策略",
        "backstory": (
            "你是CFA持证量化投资分析师，10年经验，坚持数据驱动决策和严格风险管理。"
            "你输出的每一份报告都必须是客户可以直接用于投资决策的完整交付物。"
            "你的报告结构永远是：一、宏观背景与行业环境 → 二、技术指标综合对比表 → "
            "三、相关系数矩阵（含解读）→ 四、个股深度分析（每只至少200字）→ "
            "五、综合投资建议（操作策略表+风险提示）→ 免责声明。"
            "工作流程：1)用fetch_stock_data获取真实股票数据(至少3只，必选600519.SH+000858.SZ) "
            "2)用run_python_experiment批量计算：MA20/MA60、日收益率、年化波动率、"
            "夏普比率(无风险利率2%)、最大回撤、价格偏离度、相关系数矩阵 "
            "3)搜索最新市场新闻和宏观政策(最多2次)，用download_page下载1篇深度分析 "
            "4)用generate_chart生成价格走势图(含MA线) "
            "5)结合技术面和宏观面给出买入/持有/卖出建议和12个月目标价及止损位 "
            "6)用save_result保存报告。"
        ),
    },
    "data_analysis": {
        "role": "数据分析专家",
        "goal": "输出一份完整的、可用于管理层汇报的专业电商数据分析报告，包含多维度分析、交叉矩阵、行业对比和分层行动方案",
        "backstory": (
            "你是资深电商数据分析专家，10年头部电商平台数据总监经验，精通统计分析和商业智能。"
            "你的报告结构永远是：一、数据概览 → 二、按产品类别分析（表格+解读）→ "
            "三、按地区分析（表格+解读）→ 四、按客户类型分析（表格+解读）→ "
            "五、月度趋势分析（明细表+解读）→ 六、交叉分析矩阵（品类×地区+品类×客户）→ "
            "七、行业趋势对比 → 八、业务建议与行动方案（短期/中期/长期三层）→ 九、总结。"
            "工作流程：1)读取CSV数据 2)用run_python_experiment一次性完成所有多维度分析"
            "（品类统计/地区分布/客户类型/月度趋势/Pareto分析/交叉分析矩阵），"
            "必须在一个代码块中打印所有结果！"
            "3)用generate_chart生成品类对比柱状图和地区分布饼图(至少2张) "
            "4)搜索行业趋势(最多2次) 5)给出具体业务建议 6)用save_result保存报告。"
        ),
    },
    "director": {
        "role": "资深影视策划",
        "goal": "输出一份完整的、可用于投资人路演的专业项目策划报告，包含创意发想、市场研究、四维度评估和详细推进时间表",
        "backstory": (
            "你是拥有15年经验的影视策划和创意总监，参与过多部票房过10亿的项目开发。"
            "你的报告结构永远是：一、项目概述（名称/类型/核心概念/对标作品/差异化定位）→ "
            "二、创意发想过程（两轮发想+选择理由）→ "
            "三、市场研究（数据表格+对标分析+趋势）→ "
            "四、四维度专业评估：创意（含打分）+商业（票房预测三区间+衍生品）+"
            "制作（预算分配表+选角建议表）+风险（含等级和应对）→ "
            "五、项目推进建议与时间表（阶段/里程碑/风险应对）→ 六、总结与建议。"
            "工作流程：1)读取项目数据 2)用brainstorm_ideas进行两轮创意发想"
            "(第一轮：新主题创意count=3，第二轮：角色和情节展开count=3) "
            "3)搜索市场数据和下载产业分析(最多2次搜索) "
            "4)从创意/商业/制作/风险四个维度给出专业评估 "
            "5)给出具体的项目推进建议和时间表 6)用save_result保存报告。"
        ),
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Report
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CrewAIAgentReport:
    """Report for a CrewAI agent run — compatible with comparison infra."""
    agent_type: str
    framework: str = "CrewAI"
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
    crew_output: Any = None


def _get_task_description(agent_type: str) -> str:
    tasks = {
        "financial": (
            "全面分析字节跳动2025年财务报告。\n\n"
            "【最终输出格式 — 必须遵守！】\n"
            "在调用 save_result 之后，你必须将完整的专业财务分析报告作为最终回答输出。\n"
            "这意味着：不要只输出一个简短的\"任务完成总结\"，而是要输出一份包含以下所有章节的完整报告：\n"
            "一、公司概况与核心财务数据摘要（含表格：营收/毛利/净利/总资产/总负债/权益/现金流+同比变化%）\n"
            "二、关键财务比率全面分析（分盈利能力/偿债能力/运营效率/成长能力四个子章节，每个比率：数值+行业基准+评价+深度解读）\n"
            "三、行业对比分析（表格：字节vs行业均值vs行业优秀线，含差距分析）\n"
            "四、综合财务健康评级（★★★★★格式，含评级说明）\n"
            "五、关键风险点识别（表格，至少5项风险）\n"
            "六、结论与建议\n"
            "免责声明\n\n"
            "【操作步骤】\n"
            "1. 使用 read_file 分别读取 financial_report.json 和 financial_report.md 两个文件。\n"
            "2. 使用 run_python_experiment 一次性计算所有关键财务比率（至少12项）："
            "ROE、ROA、毛利率、净利率、EBITDA利润率、资产负债率、流动比率、速动比率、"
            "利息保障倍数、存货周转率、应收账款周转率、总资产周转率、营收增长率、净利润增长率、现金流增长率。\n"
            "3. 使用 generate_chart 生成盈利能力对比柱状图（chart_type='bar'），"
            "使用 generate_financial_table 生成完整的财务比率汇总表。\n"
            "4. 使用 web_search 搜索'字节跳动 2025 财务表现 行业对比'获取行业基准（最多搜索2次）。\n"
            "5. 基于所有数据给出综合财务健康评级，识别关键风险点。\n"
            "【必须执行】最后使用 save_result 将完整报告保存到 financial_analysis_report_crew.txt。"
        ),
        "investment": (
            "进行真实股票投资分析。\n\n"
            "【最终输出格式 — 必须遵守！】\n"
            "在调用 save_result 之后，你必须将完整的投资分析报告作为最终回答输出。\n"
            "这意味着：不要只输出一个\"分析总结\"，而是要输出一份包含以下所有章节的完整报告：\n"
            "一、宏观背景与行业环境（引用搜索到的政策/经济数据）\n"
            "二、技术指标综合对比表（所有指标并排对比+解读）\n"
            "三、相关系数矩阵（表格+解读：分散化效果分析）\n"
            "四、个股深度分析（每只股票单独一节，至少200字，含技术面+基本面+目标价+止损位）\n"
            "五、综合投资建议（相对价值排序+操作策略表+关键观察指标+风险提示）\n"
            "免责声明\n\n"
            "【操作步骤】\n"
            "1. 使用 fetch_stock_data 获取至少3只真实股票的价格数据："
            "必选：600519.SH（贵州茅台）、000858.SZ（五粮液），period='6mo'。\n"
            "2. 同时使用 read_file 读取 stock_prices.csv 作为补充数据。\n"
            "3. 使用 run_python_experiment 一次性计算所有技术指标："
            "MA20、MA60、日收益率、年化波动率、夏普比率（无风险利率2%）、最大回撤、偏离度、相关系数矩阵。\n"
            "4. 使用 web_search 搜索'2025中国消费股 投资展望 政策'了解宏观背景（最多搜索2次），"
            "用 download_page 下载1篇最有价值的分析文章。\n"
            "5. 使用 generate_chart 生成价格走势对比图（含MA线），至少一张。\n"
            "6. 结合技术指标和宏观研究，给出每只股票的买入/持有/卖出建议和12个月目标价。\n"
            "【必须执行】最后使用 save_result 将完整报告保存为 investment_report_crew.txt。"
        ),
        "data_analysis": (
            "深入分析电商销售数据。\n\n"
            "【最终输出格式 — 必须遵守！】\n"
            "在调用 save_result 之后，你必须将完整的数据分析报告作为最终回答输出。\n"
            "这意味着：不要只输出一个\"分析完成总结\"，而是要输出一份包含以下所有章节的完整报告：\n"
            "一、数据概览（总订单/总销售额/总销量/平均客单价/时间跨度）\n"
            "二、按产品类别分析（含完整排名表格+每个品类详细解读）\n"
            "三、按地区分析（含完整排名表格+每个地区详细解读）\n"
            "四、按客户类型分析（含表格+解读）\n"
            "五、月度趋势分析（含月度明细表+趋势解读和异常说明）\n"
            "六、交叉分析：品类×地区销售额矩阵 + 品类×客户类型销售额矩阵（含洞察解读）\n"
            "七、行业趋势对比\n"
            "八、业务建议与行动方案（必须分短期/中期/长期三层，每层有具体目标和执行方法）\n"
            "九、总结（核心优势+增长机会点+预期提升空间）\n\n"
            "【操作步骤】\n"
            "1. 使用 read_file 读取 sales_data.csv 获取完整销售数据。\n"
            "2. 使用 run_python_experiment 一次性完成所有统计分析（必须在一个代码块中打印所有结果！）："
            "品类统计/地区分布/客户类型/月度趋势/Pareto分析/交叉分析矩阵。\n"
            "3. 使用 generate_chart 生成至少2张图表（品类对比柱状图 + 地区分布饼图）。\n"
            "4. 使用 web_search 搜索'2025年中国电商消费趋势'了解行业背景（最多搜索2次）。\n"
            "【必须执行】最后使用 save_result 将完整报告保存为 data_analysis_report_crew.txt。"
        ),
        "director": (
            "策划一部新电影项目，从创意到商业可行性全面评估。\n\n"
            "【最终输出格式 — 必须遵守！】\n"
            "在调用 save_result 之后，你必须将完整的项目策划报告作为最终回答输出。\n"
            "这意味着：不要只输出一个\"策划流程总结\"，而是要输出一份包含以下所有章节的完整报告：\n"
            "一、项目概述（项目名称/类型/核心概念/对标作品/差异化定位）\n"
            "二、创意发想过程（两轮发想+选择理由）\n"
            "三、市场研究（市场数据表格+对标分析+关键趋势）\n"
            "四、四维度专业评估：创意（含打分）+商业（票房预测三区间+衍生品）+制作（预算分配表+选角建议表）+风险（含等级和应对）\n"
            "五、项目推进建议与时间表（含阶段/里程碑表格+风险应对策略表）\n"
            "六、总结与建议\n\n"
            "【操作步骤】\n"
            "1. 使用 read_file 先读取 movie_script.json 了解参考项目格式和行业数据。\n"
            "2. 使用 brainstorm_ideas 进行两轮创意发想："
            "第一轮：科幻电影新主题创意（count=3），第二轮：角色和情节展开（count=3）。\n"
            "3. 使用 web_search 搜索'2026-2027 中国电影市场 票房趋势'了解市场环境（最多搜索2次），"
            "用 download_page 下载1篇最相关的产业分析。\n"
            "4. 从创意/商业/制作/风险四个维度给出专业评估。\n"
            "5. 给出具体的项目推进建议和时间表。\n"
            "【必须执行】最后使用 save_result 将完整报告保存为 director_report_crew.txt。"
        ),
    }
    return tasks.get(agent_type, tasks["data_analysis"])


def run_crewai_agent(agent_type: str, streaming: bool = True) -> CrewAIAgentReport:
    """Run an agent using CrewAI with DeepSeek backend."""
    report = CrewAIAgentReport(agent_type=agent_type)
    report.task = _get_task_description(agent_type)
    features = get_framework_features("CrewAI")
    report.missing_features = features.features_missing
    report.deepseek_features = features.deepseek_specific_features

    # Initialize saver
    saver = RuntimeSaver("CrewAI", agent_type, MODEL)
    saver.start(task=report.task,
                system_prompt=AGENT_DEFINITIONS[agent_type]["goal"])
    saver.set_features(features)
    report.saver = saver

    # Agent definition
    agent_def = AGENT_DEFINITIONS[agent_type]

    # Create LLM pointing to DeepSeek
    llm = LLM(
        model=MODEL,
        base_url="https://api.deepseek.com/v1",
        api_key=API_KEY,
        temperature=0.2,
        max_tokens=4096,
        timeout=120,
        additional_params={"extra_body": {"thinking": {"type": "disabled"}}},
    )

    # Build crew components (verbose=False for benchmark speed)
    agent = Agent(
        role=agent_def["role"],
        goal=agent_def["goal"],
        backstory=agent_def["backstory"],
        tools=CREWAI_TOOLS,
        llm=llm,
        verbose=False,
        max_iter=8,
        allow_delegation=False,
    )

    task = Task(
        description=report.task,
        expected_output=(
            "一份完整的、分章节的专业报告，包含详细的数据分析、数据表格、行业对比、"
            "深度解读和具体建议。不能是简短摘要——必须是客户可直接使用的完整交付物。"
            "必须包含系统提示中指定的所有章节，每个数据点都要有详细解读而不只是列出数字。"
        ),
        agent=agent,
    )

    crew = Crew(
        agents=[agent],
        tasks=[task],
        process=Process.sequential,
        verbose=False,
    )

    report.features_exercised = [
        "crewai_agent_model", "crewai_task_model",
        "crewai_crew_orchestration", "crewai_tool_decorator",
        "crewai_token_tracking", "crewai_llm_provider",
    ]

    print(f"\n{'='*70}")
    print(f"  [CrewAI] {agent_type.upper()} AGENT")
    print(f"  Model: {MODEL} | CrewAI Agent/Task/Crew + LLM")
    print(f"  Role: {agent_def['role']} | Process: sequential")
    print(f"  Features: {len(features.features_available)} available, "
          f"{len(features.features_missing)} missing (DeepSeek-specific)")
    print(f"{'='*70}")
    print(f"\nTask: {report.task[:100]}...\n")

    start = time.time()
    final_text = ""

    try:
        result = crew.kickoff()
        final_text = result.raw if hasattr(result, 'raw') else str(result)
        if final_text:
            print(final_text[:500])

        # Extract data from CrewOutput
        report.crew_output = result

        # Token usage — handle both dict and object types from CrewAI
        if hasattr(result, 'token_usage') and result.token_usage:
            tu = result.token_usage
            _get = (lambda d, k, default=0: d.get(k, default))
            if isinstance(tu, dict):
                usage_dict = {
                    "prompt_tokens": _get(tu, 'prompt_tokens', 0),
                    "completion_tokens": _get(tu, 'completion_tokens', 0),
                    "total_tokens": _get(tu, 'total_tokens', 0),
                }
                cached = _get(tu, 'cached_prompt_tokens', 0)
                reasoning = _get(tu, 'reasoning_tokens', 0)
            else:
                usage_dict = {
                    "prompt_tokens": getattr(tu, 'prompt_tokens', 0) or 0,
                    "completion_tokens": getattr(tu, 'completion_tokens', 0) or 0,
                    "total_tokens": getattr(tu, 'total_tokens', 0) or 0,
                }
                cached = getattr(tu, 'cached_prompt_tokens', 0) or 0
                reasoning = getattr(tu, 'reasoning_tokens', 0) or 0

            if cached > 0:
                usage_dict["prompt_tokens_details"] = {"cached_tokens": cached}
            if reasoning > 0:
                usage_dict["completion_tokens_details"] = {"reasoning_tokens": reasoning}

            report.tokens = usage_dict

            # Estimate cost
            pricing = {"input": 1.74, "output": 3.48, "cached_input": 0.028}
            prompt_tokens = usage_dict.get("prompt_tokens", 0)
            completion_tokens = usage_dict.get("completion_tokens", 0)
            fresh = prompt_tokens - cached
            report.cost = (fresh * pricing["input"] +
                           cached * pricing["cached_input"] +
                           completion_tokens * pricing["output"]) / 1_000_000

            saver.record_token_usage(1, usage_dict, report.cost)

        # Per-task output — extract tool calls and messages from TaskOutput
        if hasattr(result, 'tasks_output') and result.tasks_output:
            for i, to in enumerate(result.tasks_output):
                report.steps += 1
                task_raw = getattr(to, 'raw', '') or ''
                # Extract per-step token usage from TaskOutput
                step_tokens = getattr(to, 'token_usage', None)
                step_usage_dict = {}
                if step_tokens:
                    if isinstance(step_tokens, dict):
                        step_usage_dict = {
                            "prompt_tokens": step_tokens.get("prompt_tokens", 0),
                            "completion_tokens": step_tokens.get("completion_tokens", 0),
                            "total_tokens": step_tokens.get("total_tokens", 0),
                        }
                    else:
                        step_usage_dict = {
                            "prompt_tokens": getattr(step_tokens, 'prompt_tokens', 0) or 0,
                            "completion_tokens": getattr(step_tokens, 'completion_tokens', 0) or 0,
                            "total_tokens": getattr(step_tokens, 'total_tokens', 0) or 0,
                        }
                # CrewAI 1.14 stores tool results in 'tools_used' on TaskOutput
                tools_used_attr = getattr(to, 'tools_used', None)
                if tools_used_attr:
                    for t in tools_used_attr if isinstance(tools_used_attr, list) else []:
                        report.tool_calls.append({
                            "name": getattr(t, 'name', str(t)),
                            "ok": True,
                            "result": str(getattr(t, 'result', ''))[:100],
                        })
                tools_errors_attr = getattr(to, 'tools_errors', None)
                if tools_errors_attr:
                    for _ in (tools_errors_attr if isinstance(tools_errors_attr, list) else [tools_errors_attr]):
                        report.errors.append(f"Tool error")
                # Record model call with token usage
                saver.record_model_call(
                    step=i + 1,
                    messages_count=getattr(to, 'messages_count', 0) or 0,
                    content=task_raw,
                    finish_reason="stop",
                )
                if step_usage_dict:
                    saver.record_token_usage(i + 1, step_usage_dict, 0)

        # Also check result-level tool usage summary
        if hasattr(result, 'tool_usage') and result.tool_usage:
            for tool_name, count in (result.tool_usage if isinstance(result.tool_usage, dict) else {}).items():
                report.features_exercised.append(f"tool_{tool_name}")
                if not report.tool_calls:
                    report.tool_calls = [{"name": tool_name, "ok": True, "result": f"Used {count} times"}]

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        report.errors.append(error_msg)
        final_text = f"ERROR: {e}"

    report.latency_ms = (time.time() - start) * 1000
    report.final_output = final_text

    # Save comprehensive runtime data (only once)
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
    report = run_crewai_agent(agent_type, streaming=True)
    print(f"\nReport saved to {OUTPUT_DIR}/")
