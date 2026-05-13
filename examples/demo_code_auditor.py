"""Demo 3: Code Review & Security Audit — 4 frameworks, 1 task, 1 judge.

One-click: python examples/demo_code_auditor.py

A professional code auditor reviews a Python module for security vulnerabilities,
performance issues, and code quality problems. All 4 frameworks use the same tools
and prompts. Tests a completely new scenario: code analysis.
"""

import json, os, sys, time, re, urllib.request, urllib.parse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from examples._demo_utils import (
    API_KEY, MODEL, RunResult, judge_output,
    print_result, print_comparison, save_results,
)

# ═══════════════════════════════════════════════════════════════════════════
# SHARED TOOLS
# ═══════════════════════════════════════════════════════════════════════════

def read_file(path: str, max_chars: int = 8000) -> str:
    """Read content from a file path. Returns first max_chars characters."""
    try:
        p = Path(path)
        if not p.exists(): return json.dumps({"error": f"File not found: {path}"})
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars: content = content[:max_chars] + f"\n...[truncated {len(content)} total chars]"
        return content
    except Exception as e:
        return json.dumps({"error": str(e)})

def web_search(query: str, max_results: int = 5) -> str:
    """Search the web for security advisories, CVE info, or best practices."""
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
    return json.dumps({"results": results}, ensure_ascii=False)

SHARED_TOOLS = [read_file, web_search]

SYSTEM_PROMPT = """你是一名高级代码审查员(10年安全审计经验,OWASP贡献者)。审查代码并生成专业报告。

审查维度:
1. 安全漏洞 (OWASP Top 10,注入风险,敏感信息泄露,不安全的反序列化)
2. 性能问题 (时间复杂度,内存泄漏,不必要的I/O,死锁风险)
3. 代码质量 (可读性,命名规范,SOLID原则,DRY,错误处理)
4. 测试覆盖 (哪些路径缺少测试,边界条件遗漏)

工作规则:
- 使用read_file阅读目标代码文件
- 对可疑的库或模式,使用web_search查询最新CVE或安全建议
- 每个问题标注严重程度: [严重]/[中等]/[建议]
- 多个独立工具可以并行调用
- 输出格式:
  ## 审查摘要
  ## 安全问题 (按严重程度排序)
  ## 性能问题
  ## 代码质量
  ## 测试建议
  ## 优先修复清单 (按严重程度排序,至少5项)
- 对严重问题给出修复代码(before/after)

深度分析要求:
- 每个问题都要说明"为什么是问题"和"可能造成什么后果"
- 不仅要指出问题,还要分析根本原因
- 优先修复清单要综合考虑严重程度和修复成本

工具降级规则:
- 如果web_search返回空结果,标注"搜索不可用",基于代码本身继续审查
- 如果read_file返回空或被截断,标注"文件读取受限",基于可见部分审查
- 不要反复重试同一工具超过2次,数据不完整时也要给出最佳判断"""

TASK = """请审查以下Python代码文件的安全性和代码质量:

审查文件: src/seekflow/tools/executor.py

注意: 这个文件是工具执行器,负责:
- 执行Agent的工具调用
- 缓存工具结果
- 截断过长的输出
- 过滤prompt注入模式
- 并行执行多个工具

请从安全、性能、代码质量、测试覆盖四个维度进行审查,生成完整的代码审查报告。"""


# ═══════════════════════════════════════════════════════════════════════════
# DTK
# ═══════════════════════════════════════════════════════════════════════════

def run_dtk(mode: str) -> RunResult:
    from seekflow.agent.agent import DeepSeekAgent
    from seekflow.client import DeepSeekClient
    thinking = mode == "stable"
    rr = RunResult(framework=f"DTK {mode.title()}", scenario="code_auditor")
    api_log = []
    original = DeepSeekClient.chat
    def logged(self, **kw):
        r = original(self, **kw); u = r.usage or {}
        api_log.append({"p": u.get("prompt_tokens", 0), "c": u.get("completion_tokens", 0),
                        "cache": (u.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0)})
        return r
    DeepSeekClient.chat = logged
    try:
        agent = DeepSeekAgent(role="高级代码审查员", goal="审查代码安全性和质量",
                              backstory="10年安全审计经验,OWASP贡献者", api_key=API_KEY, model=MODEL,
                              thinking=thinking, temperature=0.0, max_steps=6, mode=mode)
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
    rr = RunResult(framework="LangChain", scenario="code_auditor")
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
        result = agent.invoke({"messages": [{"role": "user", "content": TASK}]}, config={"callbacks": [tc], "recursion_limit": 15})
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
    rr = RunResult(framework="CrewAI", scenario="code_auditor")
    def wrap(fn):
        def w(**kw): return fn(**kw)
        w.__name__ = fn.__name__; w.__doc__ = fn.__doc__ or fn.__name__; w.__module__ = "__crewai__"
        wrapped = ca_tool(w); wrapped.name = fn.__name__; wrapped.description = fn.__doc__ or fn.__name__
        return wrapped
    try:
        ca_tools = [wrap(t) for t in SHARED_TOOLS]
        llm = LLM(model=f"deepseek/{MODEL}", api_key=API_KEY, temperature=0.0)
        agent = CA(role="高级代码审查员", goal="审查代码安全性和质量", backstory="10年安全审计经验",
                   tools=ca_tools, llm=llm, verbose=False, allow_delegation=False, max_iter=6)
        task = CT(description=TASK, expected_output="完整代码审查报告", agent=agent)
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
    print("SeekFlow Demo — Code Review & Security Audit")
    print("DTK Fast vs DTK Stable vs LangChain vs CrewAI")
    print(f"Model: {MODEL} | Judge: deepseek-v4-pro")
    print("=" * 70)
    results = []
    for fn, label in [(lambda: run_dtk("fast"), "DTK Fast"), (lambda: run_dtk("stable"), "DTK Stable"),
                       (run_langchain, "LangChain"), (run_crewai, "CrewAI")]:
        print(f"\n>>> Running {label}...")
        r = fn(); print_result(label, r); results.append(r)
    print_comparison("Code Review & Security Audit — Comparison", results)
    save_results(results, "demo_code_auditor")
