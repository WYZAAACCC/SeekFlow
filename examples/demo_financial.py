"""Demo 1: Financial Portfolio Analysis — 4 frameworks, 1 task, 1 judge.

One-click: python examples/demo_financial.py

Compares DTK Fast, DTK Stable, LangChain, and CrewAI on a professional
investment analysis task. All frameworks use identical tools, prompts,
and model. Judge scores outputs blindly on 6 quality dimensions.
"""

import json, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from examples._demo_utils import (
    API_KEY, MODEL, RunResult, judge_output,
    print_result, print_comparison, save_results,
)

# ═══════════════════════════════════════════════════════════════════════════
# SHARED TOOLS — identical across all 4 frameworks
# ═══════════════════════════════════════════════════════════════════════════

def calculate_roi(investment: float, revenue: float) -> dict:
    """Calculate Return on Investment. investment=投入成本, revenue=总收入"""
    roi = ((revenue - investment) / investment) * 100
    return {"roi_percent": round(roi, 2), "net_profit": round(revenue - investment, 2),
            "profit_margin": round((revenue - investment) / revenue * 100, 2) if revenue else 0}

def compound_growth(principal: float, rate_percent: float, years: int) -> dict:
    """Calculate compound growth. principal=本金, rate_percent=年利率%, years=年数"""
    rate = rate_percent / 100
    values = [round(principal * (1 + rate) ** y, 2) for y in range(years + 1)]
    return {"final_value": values[-1], "growth_pct": round((values[-1] / principal - 1) * 100, 2), "by_year": values}

def risk_score_calc(volatility_pct: float, debt_ratio: float, market_cap_b: float) -> dict:
    """Composite risk score 1-10. volatility_pct=年化波动率, debt_ratio=负债率, market_cap_b=市值(十亿)"""
    v = min(10, volatility_pct / 5)
    d = min(10, debt_ratio * 10)
    m = max(0, 5 - market_cap_b / 50) if market_cap_b < 250 else 0
    cs = round(v * 0.4 + d * 0.35 + m * 0.25, 1)
    return {"risk_score": cs, "rating": "LOW" if cs < 3 else "MEDIUM" if cs < 6 else "HIGH" if cs < 8 else "CRITICAL",
            "components": {"volatility": round(v, 1), "debt": round(d, 1), "size": round(m, 1)}}

def convert_currency(amount: float, from_cur: str, to_cur: str) -> dict:
    """Convert currencies. Supported: USD, CNY, EUR, JPY, GBP"""
    rates = {"USD": 1.0, "CNY": 7.25, "EUR": 0.92, "JPY": 156.0, "GBP": 0.79}
    if from_cur not in rates or to_cur not in rates:
        return {"error": f"Unsupported. Options: {list(rates.keys())}"}
    result = amount / rates[from_cur] * rates[to_cur]
    return {"amount": amount, "from": from_cur, "to": to_cur, "result": round(result, 2)}

SHARED_TOOLS = [calculate_roi, compound_growth, risk_score_calc, convert_currency]

SYSTEM_PROMPT = """你是一名资深金融分析师(CFA持证,15年华尔街经验)。分析投资标的并生成专业备忘录。

工作规则:
1. 收到任务后,列出所有需要的数据点,一次性调用工具获取
2. 所有数值必须用工具计算,不得心算或估算
3. 多个独立工具可以在一次回复中同时调用(并行),减少轮次
4. 输出格式(严格遵循):
   ## 执行摘要 (3-5句)
   ## 关键指标对比 (ROI,风险评分,增长率)
   ## 逐公司深度分析 (风险→回报→行业位置→建议)
   ## 投资组合建议
   ## 风险警告
5. 金额使用USD和CNY双币标注
6. 使用中文输出,数字和英文术语保留原样

分析深度要求:
- 每个投资建议都要说明"为什么"(支撑数据)和"所以呢"(对投资者的实际意义)
- 不仅列出数字,要解释数字背后的业务含义"""

TASK = """分析三家公司的投资价值,生成完整投资备忘录:

1. TECH公司: 波动率32%,负债率0.15,市值850亿,投入$5M,预期年收入$8.7M
2. CONSUMER公司: 波动率18%,负债率0.42,市值120亿,投入$3M,预期年收入$4.1M
3. ENERGY公司: 波动率45%,负债率0.28,市值35亿,投入$8M,预期年收入$12.5M

要求:
- 使用calculate_roi计算每家公司ROI
- 使用risk_score_calc评估每家公司风险
- 使用compound_growth计算5年复合增长(A:15%, B:8%, C:25%)
- 使用convert_currency将投资额转为CNY和EUR
- 输出完整的中文投资备忘录"""


# ═══════════════════════════════════════════════════════════════════════════
# DTK Fast & Stable
# ═══════════════════════════════════════════════════════════════════════════

def run_dtk(mode: str) -> RunResult:
    from seekflow.agent.agent import DeepSeekAgent
    from seekflow.client import DeepSeekClient

    thinking = mode == "stable"
    rr = RunResult(framework=f"DTK {mode.title()}", scenario="financial")
    api_log = []

    original = DeepSeekClient.chat
    def logged(self, **kw):
        r = original(self, **kw)
        u = r.usage or {}
        api_log.append({"p": u.get("prompt_tokens", 0), "c": u.get("completion_tokens", 0),
                        "cache": (u.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0)})
        return r
    DeepSeekClient.chat = logged

    try:
        agent = DeepSeekAgent(
            role="资深金融分析师", goal="分析投资标的并生成备忘录",
            backstory="15年华尔街经验,CFA持证人", api_key=API_KEY, model=MODEL,
            thinking=thinking, temperature=0.0, max_steps=6, mode=mode,
        )
        for t in SHARED_TOOLS: agent.add_tool(t)
        t0 = time.perf_counter()
        result = agent.run(TASK)
        rr.latency_s = round(time.perf_counter() - t0, 2)
        rr.output = result.final_output; rr.output_len = len(result.final_output)
        rr.success = True
    except Exception as e:
        rr.success = False; rr.error = str(e)
    finally:
        DeepSeekClient.chat = original

    rr.api_calls = len(api_log)
    for a in api_log:
        rr.prompt_tokens += a["p"]; rr.completion_tokens += a["c"]; rr.cached_tokens += a["cache"]
    rr.total_tokens = rr.prompt_tokens + rr.completion_tokens; rr.calc_cost()
    if rr.success and rr.output: rr.scores = judge_output(TASK, rr.output)
    return rr


# ═══════════════════════════════════════════════════════════════════════════
# LangChain
# ═══════════════════════════════════════════════════════════════════════════

def run_langchain() -> RunResult:
    from langchain_openai import ChatOpenAI
    from langchain.agents import create_agent
    from langchain_core.tools import StructuredTool
    from langchain_core.callbacks import BaseCallbackHandler

    rr = RunResult(framework="LangChain", scenario="financial")

    class TC(BaseCallbackHandler):
        def on_llm_end(self, resp, **kw):
            tu = (getattr(resp, 'llm_output', None) or {}).get('token_usage', {})
            rr.prompt_tokens += tu.get('prompt_tokens', 0)
            rr.completion_tokens += tu.get('completion_tokens', 0)
            details = tu.get('prompt_tokens_details', {}) or {}
            rr.cached_tokens += details.get('cached_tokens', 0)
            rr.api_calls += 1

    tc = TC()
    lc_tools = [StructuredTool.from_function(func=t, name=t.__name__, description=(t.__doc__ or t.__name__))
                for t in SHARED_TOOLS]
    llm = ChatOpenAI(model=MODEL, api_key=API_KEY, base_url="https://api.deepseek.com/v1",
                     temperature=0.0, request_timeout=120)

    try:
        agent = create_agent(model=llm, tools=lc_tools, system_prompt=SYSTEM_PROMPT)
        t0 = time.perf_counter()
        result = agent.invoke({"messages": [{"role": "user", "content": TASK}]},
                              config={"callbacks": [tc], "recursion_limit": 15})
        rr.latency_s = round(time.perf_counter() - t0, 2)
        msgs = result.get("messages", [])
        for m in reversed(msgs):
            c = getattr(m, "content", None)
            if isinstance(c, str) and len(c) > 100 and not getattr(m, "tool_calls", None):
                rr.output = c; break
        rr.output_len = len(rr.output); rr.success = True
    except Exception as e:
        rr.success = False; rr.error = str(e)

    rr.total_tokens = rr.prompt_tokens + rr.completion_tokens; rr.calc_cost()
    if rr.success and rr.output: rr.scores = judge_output(TASK, rr.output)
    return rr


# ═══════════════════════════════════════════════════════════════════════════
# CrewAI
# ═══════════════════════════════════════════════════════════════════════════

def run_crewai() -> RunResult:
    from crewai import Agent as CA, Task as CT, Crew, Process, LLM
    from crewai.tools import tool as ca_tool

    rr = RunResult(framework="CrewAI", scenario="financial")

    def wrap(fn):
        def w(**kw): return fn(**kw)
        w.__name__ = fn.__name__; w.__doc__ = fn.__doc__ or fn.__name__; w.__module__ = "__crewai__"
        wrapped = ca_tool(w); wrapped.name = fn.__name__; wrapped.description = fn.__doc__ or fn.__name__
        return wrapped

    try:
        ca_tools = [wrap(t) for t in SHARED_TOOLS]
        llm = LLM(model=f"deepseek/{MODEL}", api_key=API_KEY, temperature=0.0)
        agent = CA(role="资深金融分析师", goal="分析投资标的并生成备忘录",
                   backstory="15年华尔街经验,CFA持证人", tools=ca_tools, llm=llm,
                   verbose=False, allow_delegation=False, max_iter=6)
        task = CT(description=TASK, expected_output="完整的中文投资备忘录", agent=agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)

        t0 = time.perf_counter()
        result = crew.kickoff()
        rr.latency_s = round(time.perf_counter() - t0, 2)
        rr.output = str(result) if result else ""; rr.output_len = len(rr.output)
        rr.success = True

        tu = getattr(result, "token_usage", None)
        if tu:
            rr.prompt_tokens = getattr(tu, "prompt_tokens", 0) or 0
            rr.completion_tokens = getattr(tu, "completion_tokens", 0) or 0
            rr.total_tokens = getattr(tu, "total_tokens", 0) or (rr.prompt_tokens + rr.completion_tokens)
            rr.cached_tokens = getattr(tu, "cached_prompt_tokens", 0) or 0
    except Exception as e:
        rr.success = False; rr.error = str(e)

    rr.calc_cost()
    if rr.success and rr.output: rr.scores = judge_output(TASK, rr.output)
    return rr


# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("SeekFlow Demo — Financial Portfolio Analysis")
    print("DTK Fast vs DTK Stable vs LangChain vs CrewAI")
    print(f"Model: {MODEL} | Judge: deepseek-v4-pro")
    print("=" * 70)

    results = []
    for fn, label in [(lambda: run_dtk("fast"), "DTK Fast"),
                       (lambda: run_dtk("stable"), "DTK Stable"),
                       (run_langchain, "LangChain"),
                       (run_crewai, "CrewAI")]:
        print(f"\n>>> Running {label}...")
        r = fn()
        print_result(label, r)
        results.append(r)

    print_comparison("Financial Portfolio Analysis — Comparison", results)
    save_results(results, "demo_financial")
