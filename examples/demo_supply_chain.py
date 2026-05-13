"""Demo 2: Supply Chain Risk Assessment — 4 frameworks, 1 task, 1 judge.

One-click: python examples/demo_supply_chain.py

Evaluates DTK Fast, DTK Stable, LangChain, CrewAI on a global supply
chain risk analysis for an EV manufacturer facing geopolitical and
logistics challenges.
"""

import json, os, sys, time, re, urllib.request, urllib.parse, math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from examples._demo_utils import (
    API_KEY, MODEL, RunResult, judge_output,
    print_result, print_comparison, save_results,
)

# ═══════════════════════════════════════════════════════════════════════════
# SHARED TOOLS
# ═══════════════════════════════════════════════════════════════════════════

def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for information. Returns top results with snippets."""
    try:
        url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        req = urllib.request.Request(url, headers={"User-Agent": "SeekFlowDemo/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return json.dumps({"results": [], "error": "Search unavailable"})
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
    titles = re.findall(r'class="result__title"[^>]*>.*?<a[^>]*>(.*?)</a>', html, re.DOTALL)
    results = []
    for t, s in zip(titles[:max_results], snippets[:max_results]):
        title = re.sub(r'<[^>]+>', '', t).strip()
        snippet = re.sub(r'<[^>]+>', '', s).strip()
        if title: results.append({"rank": len(results) + 1, "title": title, "snippet": snippet[:300]})
    return json.dumps({"results": results, "query": query}, ensure_ascii=False)

def statistical_summary(values: str) -> dict:
    """Compute statistical summary of comma-separated numbers."""
    try:
        nums = [float(x.strip()) for x in values.split(",") if x.strip()]
        if not nums: return {"error": "No valid numbers"}
        n = len(nums); mean = sum(nums) / n; srt = sorted(nums)
        median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
        variance = sum((x - mean) ** 2 for x in nums) / n
        return {"count": n, "mean": round(mean, 2), "median": round(median, 2),
                "std_dev": round(math.sqrt(variance), 2), "min": min(nums), "max": max(nums)}
    except Exception as e:
        return {"error": str(e)}

def compound_growth(principal: float, rate_percent: float, years: int) -> dict:
    """Calculate compound growth over time."""
    rate = rate_percent / 100
    values = [round(principal * (1 + rate) ** y, 2) for y in range(years + 1)]
    return {"final_value": values[-1], "growth_pct": round((values[-1] / principal - 1) * 100, 2)}

def convert_currency(amount: float, from_cur: str, to_cur: str) -> dict:
    """Convert between currencies."""
    rates = {"USD": 1.0, "CNY": 7.25, "EUR": 0.92, "JPY": 156.0, "GBP": 0.79, "KRW": 1360.0}
    if from_cur not in rates or to_cur not in rates: return {"error": f"Unsupported. Options: {list(rates.keys())}"}
    result = amount / rates[from_cur] * rates[to_cur]
    return {"amount": amount, "from": from_cur, "to": to_cur, "result": round(result, 2)}

SHARED_TOOLS = [web_search, statistical_summary, compound_growth, convert_currency]

SYSTEM_PROMPT = """你是一名全球供应链风险管理专家(20年制造业咨询经验)。分析供应链场景并生成风险评估报告。

工作规则:
1. 先使用web_search搜索三个维度的风险,一次性全部发起
2. 使用statistical_summary分析成本趋势
3. 使用compound_growth预测关键指标增长
4. 所有数值用工具计算,不得估算
5. 多个独立工具可以并行调用,减少轮次
6. 输出格式:
   ## 执行摘要
   ## 风险矩阵 (按可能性x影响排序,至少4项)
   ## 成本影响分析
   ## 缓解策略 (每个风险至少1个具体措施)
   ## 建议行动计划 (短期/中期/长期)
7. 中文输出,专业简洁

工具降级规则:
- 如果web_search返回空结果或error,明确标注"搜索不可用",基于专业知识和给定数据继续分析,绝对不要反复重试同一搜索
- 数据不完整时也要给出最佳判断,不要以数据不足为由拒绝输出"""

TASK = """分析一家中国电动汽车制造商(年产50万辆)的供应链风险:

挑战:
- 电池原材料(锂钴镍)60%来自南美和非洲
- 芯片供应依赖台湾和韩国(45%)
- 欧洲市场增长35%,面临新碳关税
- 海运成本12个月: 3200,3400,3800,4100,3900,3600,3400,3100,3300,3600,4200,4500 (USD/40尺柜)
- 计划在欧洲建厂: 投资2亿欧元,年运营成本3500万欧元

要求:
- web_search搜索: "EV battery supply chain 2025", "semiconductor trade policy 2025", "EU carbon tariff 2025"
- statistical_summary分析海运成本趋势
- compound_growth预测3年原材料需求增长(年增18%)
- convert_currency计算欧洲投资的人民币金额
- 输出完整的风险评估报告"""


# ═══════════════════════════════════════════════════════════════════════════
# DTK Fast & Stable
# ═══════════════════════════════════════════════════════════════════════════

def run_dtk(mode: str) -> RunResult:
    from seekflow.agent.agent import DeepSeekAgent
    from seekflow.client import DeepSeekClient
    thinking = mode == "stable"
    rr = RunResult(framework=f"DTK {mode.title()}", scenario="supply_chain")
    api_log = []
    original = DeepSeekClient.chat
    def logged(self, **kw):
        r = original(self, **kw); u = r.usage or {}
        api_log.append({"p": u.get("prompt_tokens", 0), "c": u.get("completion_tokens", 0),
                        "cache": (u.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0)})
        return r
    DeepSeekClient.chat = logged
    try:
        agent = DeepSeekAgent(role="供应链风险专家", goal="分析风险并生成报告",
                              backstory="20年制造业咨询经验", api_key=API_KEY, model=MODEL,
                              thinking=thinking, temperature=0.0, max_steps=8, mode=mode)
        for t in SHARED_TOOLS: agent.add_tool(t)
        t0 = time.perf_counter(); result = agent.run(TASK)
        rr.latency_s = round(time.perf_counter() - t0, 2)
        rr.output = result.final_output; rr.output_len = len(result.final_output); rr.success = True
    except Exception as e:
        rr.success = False; rr.error = str(e)
    finally:
        DeepSeekClient.chat = original
    rr.api_calls = len(api_log)
    for a in api_log: rr.prompt_tokens += a["p"]; rr.completion_tokens += a["c"]; rr.cached_tokens += a["cache"]
    rr.total_tokens = rr.prompt_tokens + rr.completion_tokens; rr.calc_cost()
    if rr.success and rr.output: rr.scores = judge_output(TASK, rr.output)
    return rr


def run_langchain() -> RunResult:
    from langchain_openai import ChatOpenAI
    from langchain.agents import create_agent
    from langchain_core.tools import StructuredTool
    from langchain_core.callbacks import BaseCallbackHandler
    rr = RunResult(framework="LangChain", scenario="supply_chain")
    class TC(BaseCallbackHandler):
        def on_llm_end(self, resp, **kw):
            tu = (getattr(resp, 'llm_output', None) or {}).get('token_usage', {})
            rr.prompt_tokens += tu.get('prompt_tokens', 0); rr.completion_tokens += tu.get('completion_tokens', 0)
            rr.cached_tokens += (tu.get('prompt_tokens_details', {}) or {}).get('cached_tokens', 0); rr.api_calls += 1
    tc = TC()
    lc_tools = [StructuredTool.from_function(func=t, name=t.__name__, description=(t.__doc__ or t.__name__)) for t in SHARED_TOOLS]
    llm = ChatOpenAI(model=MODEL, api_key=API_KEY, base_url="https://api.deepseek.com/v1", temperature=0.0, request_timeout=120)
    try:
        agent = create_agent(model=llm, tools=lc_tools, system_prompt=SYSTEM_PROMPT)
        t0 = time.perf_counter()
        result = agent.invoke({"messages": [{"role": "user", "content": TASK}]}, config={"callbacks": [tc], "recursion_limit": 20})
        rr.latency_s = round(time.perf_counter() - t0, 2)
        msgs = result.get("messages", [])
        for m in reversed(msgs):
            c = getattr(m, "content", None)
            if isinstance(c, str) and len(c) > 100 and not getattr(m, "tool_calls", None): rr.output = c; break
        rr.output_len = len(rr.output); rr.success = True
    except Exception as e:
        rr.success = False; rr.error = str(e)
    rr.total_tokens = rr.prompt_tokens + rr.completion_tokens; rr.calc_cost()
    if rr.success and rr.output: rr.scores = judge_output(TASK, rr.output)
    return rr


def run_crewai() -> RunResult:
    from crewai import Agent as CA, Task as CT, Crew, Process, LLM
    from crewai.tools import tool as ca_tool
    rr = RunResult(framework="CrewAI", scenario="supply_chain")
    def wrap(fn):
        def w(**kw): return fn(**kw)
        w.__name__ = fn.__name__; w.__doc__ = fn.__doc__ or fn.__name__; w.__module__ = "__crewai__"
        wrapped = ca_tool(w); wrapped.name = fn.__name__; wrapped.description = fn.__doc__ or fn.__name__
        return wrapped
    try:
        ca_tools = [wrap(t) for t in SHARED_TOOLS]
        llm = LLM(model=f"deepseek/{MODEL}", api_key=API_KEY, temperature=0.0)
        agent = CA(role="供应链风险专家", goal="分析风险并生成报告", backstory="20年制造业咨询经验",
                   tools=ca_tools, llm=llm, verbose=False, allow_delegation=False, max_iter=8)
        task = CT(description=TASK, expected_output="完整风险评估报告", agent=agent)
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)
        t0 = time.perf_counter(); result = crew.kickoff()
        rr.latency_s = round(time.perf_counter() - t0, 2)
        rr.output = str(result) if result else ""; rr.output_len = len(rr.output); rr.success = True
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


if __name__ == "__main__":
    print("=" * 70)
    print("SeekFlow Demo — Supply Chain Risk Assessment")
    print("DTK Fast vs DTK Stable vs LangChain vs CrewAI")
    print(f"Model: {MODEL} | Judge: deepseek-v4-pro")
    print("=" * 70)
    results = []
    for fn, label in [(lambda: run_dtk("fast"), "DTK Fast"), (lambda: run_dtk("stable"), "DTK Stable"),
                       (run_langchain, "LangChain"), (run_crewai, "CrewAI")]:
        print(f"\n>>> Running {label}...")
        r = fn(); print_result(label, r); results.append(r)
    print_comparison("Supply Chain Risk Assessment — Comparison", results)
    save_results(results, "demo_supply_chain")
