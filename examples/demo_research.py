"""Demo 4: Multi-Topic Research Synthesis — 4 frameworks, 1 task, 1 judge.

One-click: python examples/demo_research.py

Tests each framework's ability to research multiple topics, cross-reference
findings, and produce a synthesized report. Uses web_search + text analysis.
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
        if title: results.append({"rank": len(results) + 1, "title": title, "snippet": re.sub(r'<[^>]+>', '', s).strip()[:300]})
    return json.dumps({"results": results, "query": query}, ensure_ascii=False)

def extract_keywords(text: str, top_k: int = 10) -> dict:
    """Extract key terms and their frequency from text."""
    words = re.findall(r'\b[a-zA-Z一-鿿]{2,}\b', text.lower())
    freq = {}
    for w in words: freq[w] = freq.get(w, 0) + 1
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return {"total_words": len(words), "unique_words": len(freq),
            "top_keywords": [{"word": w, "count": c} for w, c in sorted_words[:top_k]]}

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

SHARED_TOOLS = [web_search, extract_keywords, statistical_summary]

SYSTEM_PROMPT = """你是一名资深行业研究员(前麦肯锡和Gartner分析师)。研究多个主题并生成综合分析报告。

工作规则:
1. 收到任务后,列出所有需要搜索的主题,一次性全部发起web_search
2. 使用extract_keywords分析搜索结果的关键词分布
3. 对搜索结果进行交叉验证:不同来源的信息矛盾时标注
4. 多个独立工具可以并行调用,减少轮次
5. 输出格式:
   ## 研究摘要 (每个主题1-2句)
   ## 主题深度分析 (每个主题:背景→现状→趋势→影响)
   ## 交叉洞察 (主题间的关联和矛盾)
   ## 信息来源 (列出所有搜索主题,标注结果数量)
   ## 不确定性说明 (哪些结论基于有限信息)
6. 中文输出,引用来源时保留原始英文

分析深度要求:
- 每个结论都要说明"为什么"和"所以呢"(business impact)
- 不仅要总结搜索内容,更要提出独立见解和趋势判断

工具降级规则:
- 如果web_search返回空结果,明确标注"搜索不可用",基于专业知识继续分析
- 不要反复重试同一搜索超过2次,数据不完整时也要给出最佳判断"""

TASK = """研究以下三个主题并生成综合分析报告:

主题1: "AI agent frameworks comparison 2025" — AI Agent框架的最新发展趋势
主题2: "DeepSeek API enterprise adoption 2025" — DeepSeek在企业中的采用情况
主题3: "LLM cost optimization prompt caching 2025" — 大模型成本优化和缓存技术

要求:
- 每个主题使用独立的web_search
- 使用extract_keywords分析每个搜索结果的文本特征
- 使用statistical_summary对比三个主题的关键词统计差异
- 交叉分析:这三个主题之间有什么关联?
- 输出完整的行业研究报告"""


# ═══════════════════════════════════════════════════════════════════════════
# SeekFlow
# ═══════════════════════════════════════════════════════════════════════════

def run_dtk(mode: str) -> RunResult:
    from seekflow.agent.agent import DeepSeekAgent
    from seekflow.client import DeepSeekClient
    thinking = mode == "stable"
    rr = RunResult(framework=f"SeekFlow {mode.title()}", scenario="research")
    api_log = []
    original = DeepSeekClient.chat
    def logged(self, **kw):
        r = original(self, **kw); u = r.usage or {}
        api_log.append({"p": u.get("prompt_tokens", 0), "c": u.get("completion_tokens", 0),
                        "cache": (u.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0)})
        return r
    DeepSeekClient.chat = logged
    try:
        agent = DeepSeekAgent(role="行业研究员", goal="研究主题并生成综合分析",
                              backstory="前麦肯锡和Gartner分析师", api_key=API_KEY, model=MODEL,
                              thinking=thinking, temperature=0.0, max_steps=12, mode=mode)
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
    rr = RunResult(framework="LangChain", scenario="research")
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
    rr = RunResult(framework="CrewAI", scenario="research")
    def wrap(fn):
        def w(**kw): return fn(**kw)
        w.__name__ = fn.__name__; w.__doc__ = fn.__doc__ or fn.__name__; w.__module__ = "__crewai__"
        wrapped = ca_tool(w); wrapped.name = fn.__name__; wrapped.description = fn.__doc__ or fn.__name__
        return wrapped
    try:
        ca_tools = [wrap(t) for t in SHARED_TOOLS]
        llm = LLM(model=f"deepseek/{MODEL}", api_key=API_KEY, temperature=0.0)
        agent = CA(role="行业研究员", goal="研究主题并生成综合分析", backstory="前麦肯锡和Gartner分析师",
                   tools=ca_tools, llm=llm, verbose=False, allow_delegation=False, max_iter=8)
        task = CT(description=TASK, expected_output="完整行业研究报告", agent=agent)
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
    print("SeekFlow Demo — Multi-Topic Research Synthesis")
    print("SeekFlow Fast vs SeekFlow Stable vs LangChain vs CrewAI")
    print(f"Model: {MODEL} | Judge: deepseek-v4-pro")
    print("=" * 70)
    results = []
    for fn, label in [(lambda: run_dtk("fast"), "SeekFlow Fast"), (lambda: run_dtk("stable"), "SeekFlow Stable"),
                       (run_langchain, "LangChain"), (run_crewai, "CrewAI")]:
        print(f"\n>>> Running {label}...")
        r = fn(); print_result(label, r); results.append(r)
    print_comparison("Research Synthesis — Comparison", results)
    save_results(results, "demo_research")
