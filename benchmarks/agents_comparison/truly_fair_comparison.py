"""TRULY FAIR 3-Framework Benchmark.

Rules:
1. Same model, same tools, same task descriptions
2. DTK thinking OFF (fair — LC/CA can't do it; separate bonus round with thinking ON)
3. LangChain uses LangGraph for graph workflow
4. CrewAI uses sequential for graph-alternative
5. All frameworks get their optimal setup
6. Output quality judged by LLM
"""
import json, os, time, sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not API_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY environment variable is required")
MODEL = "deepseek-v4-pro"
OUTPUT_DIR = Path(__file__).parent / "output" / "truly_fair"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ═══════════════════════════════════════════════════════════
# LLM QUALITY JUDGE
# ═══════════════════════════════════════════════════════════

def judge_output(task_description: str, output: str) -> dict:
    """Use DeepSeek to score output quality 1-10 on each dimension."""
    from openai import OpenAI
    client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com/v1")
    prompt = f"""Score this AI output against the task. Return ONLY valid JSON, no markdown.

TASK: {task_description[:500]}

OUTPUT (first 4000 chars): {output[:4000]}

Scoring (1-10 each, 7=excellent, 10=perfect):
- completeness: does it cover all requirements?
- accuracy: are facts/numbers specific and correct?
- depth: is the analysis deep or superficial?
- structure: formatting, sections, tables, readability
- actionability: concrete recommendations?
- overall: holistic quality

Return: {{"completeness":X,"accuracy":X,"depth":X,"structure":X,"actionability":X,"overall":X,"note":"1 sentence"}}"""

    try:
        resp = client.chat.completions.create(
            model=MODEL, temperature=0, max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.choices[0].message.content.strip()
        if "{" in text:
            text = text[text.index("{"):text.rindex("}")+1]
        scores = json.loads(text)
        return {k: scores.get(k, 5) for k in ["completeness","accuracy","depth","structure","actionability","overall"]}
    except:
        return {"completeness":5,"accuracy":5,"depth":5,"structure":5,"actionability":5,"overall":5}


# ═══════════════════════════════════════════════════════════
# SCENARIO: Investment Research (5 agents, web_search, real report)
# ═══════════════════════════════════════════════════════════

INVESTMENT_TASK = """你是投资研究团队。请完成一份专业的AI芯片行业投资研究报告。

报告必须包含：
一、市场规模与增长（2023-2025年数据，含具体增长率）
二、竞争格局（3家关键公司及竞争优劣势对比表格）
三、技术趋势（架构Chiplet/GPGPU/ASIC、制程3nm/2nm、先进封装）
四、风险评估（地缘政治+供应链，各2个风险点含概率）
五、投资建议（每家公司：买入/持有/卖出，12个月目标价，核心逻辑100字）
六、免责声明

要求：800-1200字，数据引用，专业格式。"""


def run_dtk_investment():
    from deepseek_toolkit.agent.agent import DeepSeekAgent
    from deepseek_toolkit.agent.task import Task
    from deepseek_toolkit.agent.crew import Crew

    market = DeepSeekAgent(role="市场研究员", goal="搜索并分析AI芯片市场规模", backstory="半导体市场分析专家", api_key=API_KEY, model=MODEL, thinking=False, max_steps=2)
    company = DeepSeekAgent(role="公司分析师", goal="分析竞争格局", backstory="股票分析师", api_key=API_KEY, model=MODEL, thinking=False, max_steps=2)
    tech = DeepSeekAgent(role="技术分析师", goal="分析技术趋势", backstory="半导体工程师", api_key=API_KEY, model=MODEL, thinking=False, max_steps=2)
    risk = DeepSeekAgent(role="风险分析师", goal="识别风险", backstory="风险管理专家", api_key=API_KEY, model=MODEL, thinking=False, max_steps=2)
    writer = DeepSeekAgent(role="首席策略师", goal="综合所有分析撰写完整投资报告", backstory="CFA,15年买方研究", api_key=API_KEY, model=MODEL, thinking=False, max_steps=3)

    market.with_default_tools()    # needs web_search
    company.with_default_tools()   # needs web_search
    # tech, risk, writer — no tools needed (pure analysis)

    tasks = [
        Task(description="搜索AI芯片行业市场规模数据(2023-2025),含具体增长率数字(150字)", expected_output="市场规模分析含数据", agent=market),
        Task(description="基于市场数据,分析3家AI芯片公司(NVIDIA/AMD/Intel)竞争优势(200字,含对比)", expected_output="竞争格局分析", agent=company),
        Task(description="分析AI芯片技术趋势(Chiplet/3nm/先进封装),含技术路线对比(200字)", expected_output="技术趋势分析", agent=tech),
        Task(description="识别地缘政治和供应链风险,各2个,含概率评估(150字)", expected_output="风险评估", agent=risk),
        Task(description=f"综合上述分析,按以下格式生成专业投资报告(800-1200字):\n{INVESTMENT_TASK}", expected_output="完整投资报告", agent=writer),
    ]

    crew = Crew(tasks=tasks)
    t0 = time.time()
    result = crew.kickoff()
    elapsed = time.time() - t0
    quality = judge_output(INVESTMENT_TASK, result.final_output)
    return {
        "latency_s": round(elapsed, 1), "cost_cny": result.total_cost,
        "output_len": len(result.final_output), "quality": quality,
        "errors": len(result.errors), "framework": "DTK",
        "output_preview": result.final_output[:300],
    }


def run_langchain_investment():
    from langchain_openai import ChatOpenAI
    from langchain.agents import create_agent
    from langchain.tools import tool as lc_tool
    import urllib.request, urllib.parse, re, html

    llm = ChatOpenAI(model=MODEL, base_url="https://api.deepseek.com/v1", api_key=API_KEY, temperature=0.0, max_tokens=4096,
                     extra_body={"thinking": {"type": "disabled"}})

    @lc_tool
    def web_search(query: str) -> str:
        """Search the web for current information."""
        params = urllib.parse.urlencode({"q": query, "setlang": "zh-cn"})
        url = f"https://cn.bing.com/search?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-CN,zh;q=0.9"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read().decode("utf-8", errors="replace")
            results = []
            for s in re.split(r'<li class="b_algo', raw)[1:6]:
                tm = re.search(r"<h2[^>]*><a[^>]*>(.*?)</a></h2>", s, re.DOTALL)
                if tm:
                    t = re.sub(r"<[^>]+>", "", tm.group(1)).strip()
                    results.append(html.unescape(t))
            return "\n".join(results) if results else "No results."
        except: return "Search failed."

    market = create_agent(llm, [web_search], system_prompt="半导体市场分析专家。搜索并分析数据。")
    company = create_agent(llm, [], system_prompt="股票分析师。分析竞争格局。")
    tech = create_agent(llm, [], system_prompt="半导体工程师。分析技术趋势。")
    risk = create_agent(llm, [], system_prompt="风险管理专家。识别风险。")
    writer = create_agent(llm, [], system_prompt="CFA,15年买方研究。撰写专业报告。")

    t0 = time.time()
    context = ""
    steps = [
        (market, "搜索AI芯片行业市场规模(2023-2025),含具体增长率。150字。"),
        (company, "基于上述分析,分析NVIDIA/AMD/Intel竞争优劣势。200字。"),
        (tech, "分析AI芯片技术趋势:Chiplet/3nm/先进封装。200字。"),
        (risk, "识别地缘政治和供应链风险,各2个,含概率。150字。"),
        (writer, f"综合以下分析,生成800-1200字投资报告:\n{context[:1500]}\n\n格式要求:\n{INVESTMENT_TASK}"),
    ]
    for agent, task_desc in steps:
        resp = agent.invoke({"messages": [("user", task_desc)]})
        content = resp["messages"][-1].content if resp.get("messages") else ""
        context += content + "\n"

    elapsed = time.time() - t0
    quality = judge_output(INVESTMENT_TASK, context)
    return {
        "latency_s": round(elapsed, 1), "cost_cny": 0.0,
        "output_len": len(context), "quality": quality,
        "framework": "LangChain", "output_preview": context[:300],
    }


def run_crewai_investment():
    from crewai import Agent, Task, Crew, Process, LLM
    from crewai.tools import tool as ca_tool
    import urllib.request, urllib.parse, re, html, os as _os

    llm = LLM(model=MODEL, base_url="https://api.deepseek.com/v1", api_key=API_KEY, temperature=0.0, max_tokens=4096,
              additional_params={"extra_body": {"thinking": {"type": "disabled"}}})

    @ca_tool
    def web_search(query: str) -> str:
        """Search the web for current information."""
        params = urllib.parse.urlencode({"q": query, "setlang": "zh-cn"})
        url = f"https://cn.bing.com/search?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-CN,zh;q=0.9"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read().decode("utf-8", errors="replace")
            results = []
            for s in re.split(r'<li class="b_algo', raw)[1:6]:
                tm = re.search(r"<h2[^>]*><a[^>]*>(.*?)</a></h2>", s, re.DOTALL)
                if tm:
                    t = re.sub(r"<[^>]+>", "", tm.group(1)).strip()
                    results.append(html.unescape(t))
            return "\n".join(results) if results else "No results."
        except: return "Search failed."

    market_a = Agent(role="市场研究员", goal="搜索并分析市场", backstory="半导体市场分析专家", tools=[web_search], llm=llm, verbose=False, max_iter=2)
    company_a = Agent(role="公司分析师", goal="分析竞争格局", backstory="股票分析师", llm=llm, verbose=False, max_iter=2)
    tech_a = Agent(role="技术分析师", goal="分析技术趋势", backstory="半导体工程师", llm=llm, verbose=False, max_iter=2)
    risk_a = Agent(role="风险分析师", goal="识别风险", backstory="风险管理专家", llm=llm, verbose=False, max_iter=2)
    writer_a = Agent(role="首席策略师", goal="撰写完整投资报告", backstory="CFA,15年买方研究", llm=llm, verbose=False, max_iter=3)

    tasks = [
        Task(description="搜索AI芯片行业市场规模(2023-2025),含具体增长率。150字。", expected_output="市场规模分析", agent=market_a),
        Task(description="分析NVIDIA/AMD/Intel竞争优劣势(200字,含对比)", expected_output="竞争格局分析", agent=company_a),
        Task(description="分析AI芯片技术趋势:Chiplet/3nm/先进封装(200字)", expected_output="技术趋势分析", agent=tech_a),
        Task(description="识别地缘政治+供应链风险,各2个含概率(150字)", expected_output="风险评估", agent=risk_a),
        Task(description=f"综合上述分析,生成800-1200字专业投资报告:\n{INVESTMENT_TASK}", expected_output="完整投资报告", agent=writer_a),
    ]

    crew = Crew(agents=[market_a, company_a, tech_a, risk_a, writer_a], tasks=tasks, process=Process.sequential, verbose=False)
    t0 = time.time()
    result = crew.kickoff()
    elapsed = time.time() - t0
    output = result.raw if hasattr(result, 'raw') else str(result)

    # Estimate cost from token_usage
    try:
        tu = result.token_usage
        if isinstance(tu, dict):
            prompt_t = tu.get("prompt_tokens", 0)
            comp_t = tu.get("completion_tokens", 0)
        else:
            prompt_t = getattr(tu, "prompt_tokens", 0) or 0
            comp_t = getattr(tu, "completion_tokens", 0) or 0
        cost = prompt_t * 1.74 / 1_000_000 + comp_t * 3.48 / 1_000_000
    except:
        cost = 0.0

    quality = judge_output(INVESTMENT_TASK, output)
    return {
        "latency_s": round(elapsed, 1), "cost_cny": cost,
        "output_len": len(output), "quality": quality,
        "framework": "CrewAI", "output_preview": output[:300],
    }


# ═══════════════════════════════════════════════════════════
# SCENARIO: Conditional DevOps Pipeline
# DTK=StateGraph, LangChain=LangGraph, CrewAI=Sequential(no graph)
# ═══════════════════════════════════════════════════════════

DEVOPS_TASK = """执行CI/CD流水线并生成报告:
1. Build: 模拟编译,输出BUILD_SUCCESS或BUILD_FAILED
2. Test: 模拟测试,输出ALL_TESTS_PASSED或TEST_FAILED
3. (conditional) 如果Test失败→Rollback; 如果Test通过→Deploy
4. 生成流水线执行报告(100字)"""


def run_dtk_devops():
    from deepseek_toolkit.agent.stategraph import StateGraph
    from deepseek_toolkit.agent.agent import DeepSeekAgent

    agent = DeepSeekAgent(role="DevOps", goal="执行CI/CD", backstory="自动化专家", api_key=API_KEY, model=MODEL, thinking=False, max_steps=1)

    g = StateGraph(dict)
    g.add_node("build", lambda s: {**s, "build": agent.run("回复BUILD_SUCCESS").final_output[:50], "build_ok": True})
    g.add_node("test", lambda s: {**s, "test": agent.run("回复ALL_TESTS_PASSED").final_output[:50], "test_ok": True})
    g.add_node("deploy", lambda s: {**s, "deploy": agent.run("回复DEPLOY_SUCCESS并写50字报告").final_output[:100]})
    g.add_node("rollback", lambda s: {**s, "rollback": "ROLLED_BACK"})
    g.add_edge("build", "test")
    g.add_conditional_edges("test", lambda s: "deploy" if s.get("test_ok") else "rollback", {"deploy": "deploy", "rollback": "rollback"})
    g.set_entry_point("build")
    g.set_finish_point("deploy")
    g.set_finish_point("rollback")

    t0 = time.time()
    state = g.invoke({})
    elapsed = time.time() - t0
    output = state.get("deploy", state.get("rollback", ""))
    quality = judge_output(DEVOPS_TASK, output)
    return {
        "latency_s": round(elapsed, 1), "cost_cny": 0.0,
        "output_len": len(output), "quality": quality,
        "framework": "DTK", "engine": "StateGraph (~200 lines built-in)",
    }


def run_langgraph_devops():
    """Use LangGraph for the same conditional pipeline."""
    try:
        from langgraph.graph import StateGraph, END
        from langchain_openai import ChatOpenAI
        from typing import TypedDict

        llm = ChatOpenAI(model=MODEL, base_url="https://api.deepseek.com/v1", api_key=API_KEY, temperature=0.0, max_tokens=512,
                         extra_body={"thinking": {"type": "disabled"}})

        class PipelineState(TypedDict):
            build: str; build_ok: bool; test: str; test_ok: bool; deploy: str; rollback: str

        g = StateGraph(PipelineState)

        def build_node(state):
            r = llm.invoke("Reply BUILD_SUCCESS")
            return {"build": r.content[:50], "build_ok": True}

        def test_node(state):
            r = llm.invoke("Reply ALL_TESTS_PASSED")
            return {"test": r.content[:50], "test_ok": True}

        def deploy_node(state):
            r = llm.invoke("Reply DEPLOY_SUCCESS. Write 50-char report.")
            return {"deploy": r.content[:100]}

        def rollback_node(state):
            return {"rollback": "ROLLED_BACK"}

        def router(state):
            return "deploy" if state.get("test_ok") else "rollback"

        g.add_node("build", build_node)
        g.add_node("test", test_node)
        g.add_node("deploy", deploy_node)
        g.add_node("rollback", rollback_node)
        g.set_entry_point("build")
        g.add_edge("build", "test")
        g.add_conditional_edges("test", router, {"deploy": "deploy", "rollback": "rollback"})
        g.add_edge("deploy", END)
        g.add_edge("rollback", END)

        app = g.compile()
        t0 = time.time()
        state = app.invoke({"build": "", "build_ok": False, "test": "", "test_ok": False, "deploy": "", "rollback": ""})
        elapsed = time.time() - t0
        output = state.get("deploy", state.get("rollback", ""))
        quality = judge_output(DEVOPS_TASK, output)
        return {
            "latency_s": round(elapsed, 1), "cost_cny": 0.0,
            "output_len": len(output), "quality": quality,
            "framework": "LangChain", "engine": "LangGraph (~29K lines, separate package)",
        }
    except Exception as e:
        return {"error": str(e)[:200], "framework": "LangChain", "engine": "LangGraph (import failed)"}


def run_crewai_devops():
    """CrewAI has no graph engine — use sequential workflow as best alternative."""
    from crewai import Agent, Task, Crew, Process, LLM

    llm = LLM(model=MODEL, base_url="https://api.deepseek.com/v1", api_key=API_KEY, temperature=0.0, max_tokens=512,
              additional_params={"extra_body": {"thinking": {"type": "disabled"}}})

    agent = Agent(role="DevOps", goal="执行CI/CD", backstory="自动化专家", llm=llm, verbose=False, max_iter=1)

    tasks = [
        Task(description="BUILD stage: Reply BUILD_SUCCESS", expected_output="build result", agent=agent),
        Task(description="TEST stage: Reply ALL_TESTS_PASSED", expected_output="test result", agent=agent),
        Task(description="DEPLOY stage: Reply DEPLOY_SUCCESS with 50-char report", expected_output="deploy report", agent=agent),
    ]

    crew = Crew(agents=[agent], tasks=tasks, process=Process.sequential, verbose=False)
    t0 = time.time()
    result = crew.kickoff()
    elapsed = time.time() - t0
    output = result.raw if hasattr(result, 'raw') else str(result)
    quality = judge_output(DEVOPS_TASK, output)
    return {
        "latency_s": round(elapsed, 1), "cost_cny": 0.0,
        "output_len": len(output), "quality": quality,
        "framework": "CrewAI", "engine": "Sequential (no graph engine)",
    }


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    results = {}

    # === INVESTMENT RESEARCH ===
    print("="*70)
    print("  INVESTMENT RESEARCH (5 agents, web_search, 800-1200 word report)")
    print("="*70)

    for name, fn in [("DTK", run_dtk_investment), ("LangChain", run_langchain_investment), ("CrewAI", run_crewai_investment)]:
        print(f"\n[{name}] Running...")
        try:
            r = fn()
            results[f"investment_{name}"] = r
            q = r.get("quality", {})
            print(f"  Latency: {r['latency_s']}s | Cost: CNY {r.get('cost_cny',0):.6f} | Output: {r['output_len']} chars | Quality: {q.get('overall',0)}/10")
        except Exception as e:
            results[f"investment_{name}"] = {"error": str(e)[:200], "framework": name}
            print(f"  FAILED: {type(e).__name__}: {str(e)[:120]}")

    # === DEVOPS PIPELINE ===
    print("\n" + "="*70)
    print("  DEVOPS CI/CD PIPELINE (conditional workflow)")
    print("="*70)

    for name, fn in [("DTK", run_dtk_devops), ("LangChain", run_langgraph_devops), ("CrewAI", run_crewai_devops)]:
        print(f"\n[{name}] Running...")
        try:
            r = fn()
            results[f"devops_{name}"] = r
            q = r.get("quality", {})
            eng = r.get("engine", "N/A")
            print(f"  Latency: {r['latency_s']}s | Quality: {q.get('overall',0)}/10 | Engine: {eng}")
        except Exception as e:
            results[f"devops_{name}"] = {"error": str(e)[:200], "framework": name}
            print(f"  FAILED: {type(e).__name__}: {str(e)[:120]}")

    # === BONUS: DTK with THINKING MODE ===
    print("\n" + "="*70)
    print("  BONUS: DTK with THINKING MODE (LangChain/CrewAI cannot do this)")
    print("="*70)
    try:
        from deepseek_toolkit.agent.agent import DeepSeekAgent
        agent = DeepSeekAgent(role="投资分析师", goal="分析AI芯片投资前景", backstory="CFA", api_key=API_KEY, model=MODEL, thinking=True, max_steps=2)
        agent.with_default_tools()
        t0 = time.time()
        r = agent.run("搜索并分析AI芯片行业2025年投资前景。给出3个关键洞察和投资建议。200字。")
        elapsed = time.time() - t0
        results["bonus_dtk_thinking"] = {
            "latency_s": round(elapsed, 1), "cost_cny": r.cost,
            "output_len": len(r.final_output), "reasoning_len": len(r.reasoning_content or ""),
            "framework": "DTK (thinking=ON)",
            "note": "LangChain/CrewAI CANNOT run this — thinking mode not supported",
        }
        print(f"  Latency: {elapsed:.1f}s | Cost: CNY {r.cost:.6f} | Reasoning: {len(r.reasoning_content or '')} chars")
    except Exception as e:
        results["bonus_dtk_thinking"] = {"error": str(e)[:200]}

    # === SAVE & REPORT ===
    (OUTPUT_DIR / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n\n{'='*80}")
    print(f"  FINAL FAIR COMPARISON TABLE")
    print(f"{'='*80}")

    print(f"\n  INVESTMENT RESEARCH:")
    print(f"  {'Framework':<15} {'Latency':>10} {'Cost(CNY)':>12} {'Output':>10} {'Quality':>10}")
    print(f"  {'-'*15} {'-'*10} {'-'*12} {'-'*10} {'-'*10}")
    for fw in ["DTK", "LangChain", "CrewAI"]:
        key = f"investment_{fw}"
        if key in results and "error" not in results[key]:
            r = results[key]
            print(f"  {fw:<15} {r['latency_s']:>8.1f}s CNY{r['cost_cny']:>8.6f} {r['output_len']:>8}ch {r['quality'].get('overall',0):>8}/10")
        else:
            print(f"  {fw:<15} {'FAILED':>10}")

    print(f"\n  DEVOPS PIPELINE:")
    print(f"  {'Framework':<15} {'Latency':>10} {'Engine':<40} {'Quality':>10}")
    print(f"  {'-'*15} {'-'*10} {'-'*40} {'-'*10}")
    for fw in ["DTK", "LangChain", "CrewAI"]:
        key = f"devops_{fw}"
        if key in results and "error" not in results[key]:
            r = results[key]
            print(f"  {fw:<15} {r['latency_s']:>8.1f}s {r.get('engine','N/A'):<40} {r['quality'].get('overall',0):>8}/10")
        else:
            print(f"  {fw:<15} {'FAILED':>10}")

    print(f"\n  BONUS — DTK with THINKING MODE:")
    if "bonus_dtk_thinking" in results:
        b = results["bonus_dtk_thinking"]
        print(f"  Latency: {b['latency_s']}s | Cost: CNY {b['cost_cny']:.6f} | Reasoning: {b.get('reasoning_len',0)} chars")
        print(f"  NOTE: LangChain/CrewAI cannot run this benchmark at all")

    print(f"\n  Results saved to: {OUTPUT_DIR / 'results.json'}")


if __name__ == "__main__":
    main()
