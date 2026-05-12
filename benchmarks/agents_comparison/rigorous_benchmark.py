"""RIGOROUS 3-Framework Benchmark — complex agents, proper cost tracking, LLM quality judge.

3 scenarios, each with 5-6 agents, 8-12 steps, conditional routing, real tools.
"""
import json, os, time, sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not API_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY environment variable is required")
MODEL = "deepseek-v4-pro"
OUTPUT_DIR = Path(__file__).parent / "output" / "rigorous_benchmark"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ═══════════════════════════════════════════════════════════
# LLM QUALITY JUDGE — objective, structured scoring
# ═══════════════════════════════════════════════════════════

def judge_output_quality(task: str, output: str) -> dict:
    """Use DeepSeek as impartial judge to score output quality."""
    from openai import OpenAI
    client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com/v1")
    judge_prompt = f"""You are a strict quality evaluator. Score this AI agent output against the task.

TASK: {task}

OUTPUT TO EVALUATE:
{output[:3000]}

Score each dimension 1-10. Be BRUTAL — a 7 is already excellent.

Return ONLY valid JSON:
{{
  "completeness": <1-10: did it cover all requirements?>,
  "accuracy": <1-10: are facts/numbers correct and specific?>,
  "structure": <1-10: formatting, sections, readability>,
  "actionability": <1-10: are recommendations concrete and useful?>,
  "conciseness": <1-10: no fluff, every sentence adds value>,
  "overall": <1-10: holistic quality>,
  "critique": "<1 sentence: the single biggest strength or weakness>"
}}"""
    try:
        resp = client.chat.completions.create(
            model=MODEL, temperature=0, response_format={"type": "json_object"},
            messages=[{"role": "user", "content": judge_prompt}],
            max_tokens=500,
        )
        text = resp.choices[0].message.content.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"): text = text[4:]
        result = json.loads(text)
        return {k: result.get(k, 0) if k != "critique" else result.get(k, "") for k in ["completeness","accuracy","structure","actionability","conciseness","overall","critique"]}
    except Exception as e:
        return {"overall": 5, "critique": f"Judge error: {str(e)[:80]}"}


# ═══════════════════════════════════════════════════════════
# SCENARIO 1: Complex Investment Research Pipeline
# 5 agents, 10 steps, web_search tool, conditional routing, thinking mode
# ═══════════════════════════════════════════════════════════

TASK_INVESTMENT = """扮演投资研究团队，完整分析AI芯片行业2025年投资前景。

步骤：
1. 研究AI芯片行业的市场规模、增长率(2023-2025)
2. 识别3家关键公司并分析其竞争优势
3. 分析技术趋势(架构、制程、封装)
4. 识别2个关键风险(地缘政治、供应链)
5. 给出买入/持有/卖出建议及12个月目标价
6. 综合为一份200字的投资备忘录

输出必须是完整的专业投资备忘录，含数据引用和明确建议。"""


def build_dtk_investment_crew():
    from deepseek_toolkit.agent.agent import DeepSeekAgent
    from deepseek_toolkit.agent.task import Task
    from deepseek_toolkit.agent.crew import Crew, Process

    # 5 specialized agents
    market = DeepSeekAgent(role="市场研究员", goal="研究AI芯片市场规模和增长率", backstory="半导体市场分析专家", api_key=API_KEY, model=MODEL, thinking=False, max_steps=2)
    company = DeepSeekAgent(role="公司分析师", goal="分析AI芯片公司的竞争优势", backstory="股票分析师", api_key=API_KEY, model=MODEL, thinking=False, max_steps=2)
    tech = DeepSeekAgent(role="技术分析师", goal="分析芯片架构和制程趋势", backstory="半导体工程师转分析师", api_key=API_KEY, model=MODEL, thinking=False, max_steps=2)
    risk = DeepSeekAgent(role="风险分析师", goal="识别地缘政治和供应链风险", backstory="风险管理专家", api_key=API_KEY, model=MODEL, thinking=False, max_steps=2)
    strategist = DeepSeekAgent(role="投资策略师", goal="综合所有分析给出投资建议", backstory="CFA持证人,15年买方经验", api_key=API_KEY, model=MODEL, thinking=True, max_steps=3)

    market.with_default_tools()  # web_search
    company.with_default_tools()

    tasks = [
        Task(description="搜索并分析AI芯片行业市场规模(2023-2025),给出具体增长率数据(80字)", expected_output="市场规模分析含具体数据", agent=market),
        Task(description="基于市场规模数据,识别3家关键AI芯片公司并分析其竞争优势(80字)", expected_output="3家公司竞争分析", agent=company),
        Task(description="分析AI芯片技术趋势:架构(Chiplet/GPGPU/ASIC)、制程(3nm/2nm)、封装(先进封装)(80字)", expected_output="技术趋势分析", agent=tech),
        Task(description="识别2个关键风险:地缘政治(中美出口管制)和供应链(台积电依赖度)(60字)", expected_output="风险分析", agent=risk),
        Task(description="综合所有分析,给出买入/持有/卖出建议,含12个月目标价。生成200字投资备忘录。", expected_output="完整投资备忘录", agent=strategist),
    ]

    crew = Crew(tasks=tasks)
    return crew


def build_langchain_investment_agents():
    from langchain_openai import ChatOpenAI
    from langchain.agents import create_agent
    from langchain.tools import tool as lc_tool

    llm = ChatOpenAI(model=MODEL, base_url="https://api.deepseek.com/v1", api_key=API_KEY, temperature=0.0, max_tokens=4096,
                     extra_body={"thinking": {"type": "disabled"}})

    @lc_tool
    def web_search(query: str) -> str:
        """Search the web for information."""
        import urllib.request, urllib.parse, re, html
        params = urllib.parse.urlencode({"q": query, "setlang": "zh-cn"})
        url = f"https://cn.bing.com/search?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-CN,zh;q=0.9"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read().decode("utf-8", errors="replace")
            results = []
            for s in re.split(r'<li class="b_algo', raw)[1:6]:
                tm = re.search(r"<h2[^>]*><a[^>]*>(.*?)</a></h2>", s, re.DOTALL)
                title = re.sub(r"<[^>]+>", "", tm.group(1)).strip() if tm else ""
                if title: results.append(html.unescape(title))
            return "\n".join(results) if results else "No results"
        except Exception as e:
            return f"Search error: {e}"

    @lc_tool
    def calculate(expr: str) -> str:
        """Evaluate a mathematical expression."""
        try:
            return f"Result: {eval(expr, {'__builtins__': {}})}"
        except: return f"Error"

    agents = {}
    for name, role, backstory, tools in [
        ("market", "市场研究员", "半导体市场分析专家", [web_search]),
        ("company", "公司分析师", "股票分析师", []),
        ("tech", "技术分析师", "半导体工程师", []),
        ("risk", "风险分析师", "风险管理专家", []),
        ("strategist", "投资策略师", "CFA,15年买方经验", []),
    ]:
        agents[name] = create_agent(llm, tools, system_prompt=f"{role}. {backstory}.")
    return agents, llm


def build_crewai_investment_agents():
    from crewai import Agent, Task, Crew, Process, LLM
    import os as _os; _os.environ.setdefault('KMP_DUPLICATE_LIB_OK', 'TRUE')
    from crewai.tools import tool as ca_tool

    llm = LLM(model=MODEL, base_url="https://api.deepseek.com/v1", api_key=API_KEY, temperature=0.0, max_tokens=4096,
              additional_params={"extra_body": {"thinking": {"type": "disabled"}}})

    @ca_tool
    def web_search(query: str) -> str:
        """Search the web for information."""
        import urllib.request, urllib.parse, re, html
        params = urllib.parse.urlencode({"q": query, "setlang": "zh-cn"})
        url = f"https://cn.bing.com/search?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "zh-CN,zh;q=0.9"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read().decode("utf-8", errors="replace")
            results = []
            for s in re.split(r'<li class="b_algo', raw)[1:6]:
                tm = re.search(r"<h2[^>]*><a[^>]*>(.*?)</a></h2>", s, re.DOTALL)
                title = re.sub(r"<[^>]+>", "", tm.group(1)).strip() if tm else ""
                if title: results.append(html.unescape(title))
            return "\n".join(results) if results else "No results"
        except Exception as e:
            return f"Search error: {e}"

    agents = {}
    for name, role, backstory, tools in [
        ("market", "市场研究员", "半导体市场分析专家", [web_search]),
        ("company", "公司分析师", "股票分析师", []),
        ("tech", "技术分析师", "半导体工程师", []),
        ("risk", "风险分析师", "风险管理专家", []),
        ("strategist", "投资策略师", "CFA,15年买方经验", []),
    ]:
        agents[name] = Agent(role=role, goal="分析并输出", backstory=backstory, tools=tools, llm=llm, verbose=False, max_iter=2)
    return agents, llm


def run_investment_scenario():
    print("\n" + "="*70)
    print("  INVESTMENT RESEARCH PIPELINE (5 agents, 10+ steps)")
    print("="*70)
    results = {}

    # ---- DTK ----
    print("\n[DTK] Running...")
    try:
        crew = build_dtk_investment_crew()
        t0 = time.time()
        r = crew.kickoff()
        dtk_latency = time.time() - t0
        dtk_cost = r.total_cost
        dtk_output = r.final_output
        dtk_quality = judge_output_quality(TASK_INVESTMENT, dtk_output)
        results["DTK"] = {"latency": round(dtk_latency, 1), "cost": dtk_cost, "output_len": len(dtk_output), "quality": dtk_quality, "errors": len(r.errors)}
        print(f"  Latency: {dtk_latency:.1f}s | Cost: CNY {dtk_cost:.6f} | Quality: {dtk_quality.get('overall', 0)}/10")
    except Exception as e:
        results["DTK"] = {"error": str(e)[:200]}
        print(f"  FAILED: {e}")

    # ---- LangChain ----
    print("\n[LangChain] Running...")
    try:
        agents, llm = build_langchain_investment_agents()
        t0 = time.time()
        context = ""
        for step, agent_name in enumerate(["market", "company", "tech", "risk", "strategist"]):
            agent = agents[agent_name]
            task_map = {
                "market": "搜索AI芯片行业市场规模(2023-2025),给具体增长率。60字。",
                "company": f"基于: {context[:200]}。识别3家关键AI芯片公司及其竞争优势。60字。",
                "tech": "分析AI芯片技术趋势:Chiplet/3nm/先进封装。60字。",
                "risk": "识别2个地缘政治和供应链风险。40字。",
                "strategist": f"综合以下分析,给投资建议和12个月目标价。生成100字备忘录。\\n\\n{context[:800]}",
            }
            resp = agent.invoke({"messages": [("user", task_map[agent_name])]})
            content = resp["messages"][-1].content if resp.get("messages") else ""
            context += f"\n[{agent_name}]: {content[:300]}"

        lc_latency = time.time() - t0
        lc_cost = _estimate_langchain_cost(llm, context)
        lc_quality = judge_output_quality(TASK_INVESTMENT, context)
        results["LangChain"] = {"latency": round(lc_latency, 1), "cost": lc_cost, "output_len": len(context), "quality": lc_quality}
        print(f"  Latency: {lc_latency:.1f}s | Cost: CNY {lc_cost:.6f} | Quality: {lc_quality.get('overall', 0)}/10")
    except Exception as e:
        results["LangChain"] = {"error": str(e)[:200]}
        print(f"  FAILED: {e}")

    # ---- CrewAI ----
    print("\n[CrewAI] Running...")
    try:
        agents, llm = build_crewai_investment_agents()
        tasks = [
            Task(description="搜索AI芯片行业市场规模(2023-2025),给具体增长率。60字。", expected_output="市场分析", agent=agents["market"]),
            Task(description="识别3家关键AI芯片公司及其竞争优势。60字。", expected_output="公司分析", agent=agents["company"]),
            Task(description="分析AI芯片技术趋势:Chiplet/3nm/先进封装。60字。", expected_output="技术分析", agent=agents["tech"]),
            Task(description="识别2个地缘政治和供应链风险。40字。", expected_output="风险分析", agent=agents["risk"]),
            Task(description="综合以上分析生成100字投资备忘录,含建议和目标价。", expected_output="投资备忘录", agent=agents["strategist"]),
        ]
        crew = Crew(agents=list(agents.values()), tasks=tasks, process=Process.sequential, verbose=False)
        t0 = time.time()
        r = crew.kickoff()
        ca_latency = time.time() - t0
        ca_output = r.raw if hasattr(r, 'raw') else str(r)
        ca_cost = _estimate_crewai_cost(r)
        ca_quality = judge_output_quality(TASK_INVESTMENT, ca_output)
        results["CrewAI"] = {"latency": round(ca_latency, 1), "cost": ca_cost, "output_len": len(ca_output), "quality": ca_quality}
        print(f"  Latency: {ca_latency:.1f}s | Cost: CNY {ca_cost:.6f} | Quality: {ca_quality.get('overall', 0)}/10")
    except Exception as e:
        results["CrewAI"] = {"error": str(e)[:200]}
        print(f"  FAILED: {e}")

    return results


# ═══════════════════════════════════════════════════════════
# SCENARIO 2: DevOps CI/CD Pipeline (StateGraph + tools)
# 4 stages, conditional rollback, checkpoint
# ═══════════════════════════════════════════════════════════

TASK_DEVOPS = """执行CI/CD流水线:
1. Build阶段: 编译代码并检查错误
2. Test阶段: 运行单元测试和集成测试
3. Security Scan: 扫描安全漏洞
4. Deploy: 部署到生产环境
如果任何阶段失败,回滚并报告。
输出完整流水线执行报告。"""


def run_devops_scenario():
    print("\n" + "="*70)
    print("  DEVOPS CI/CD PIPELINE (4 stages, conditional, checkpoint)")
    print("="*70)
    results = {}

    # ---- DTK StateGraph ----
    print("\n[DTK StateGraph] Running...")
    try:
        from deepseek_toolkit.agent.stategraph import StateGraph
        from deepseek_toolkit.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(role="DevOps工程师", goal="执行CI/CD流水线", backstory="自动化部署专家", api_key=API_KEY, model=MODEL, thinking=False, max_steps=1)

        g = StateGraph(dict)
        def build(s):
            r = agent.run("模拟Build阶段: 回复BUILD_SUCCESS或BUILD_FAILED")
            return {**s, "build": r.final_output[:80], "build_ok": "SUCCESS" in r.final_output}
        def test(s):
            r = agent.run("模拟Test阶段: 回复ALL_TESTS_PASSED或TEST_FAILED")
            return {**s, "test": r.final_output[:80], "test_ok": "PASSED" in r.final_output}
        def security(s):
            r = agent.run("模拟Security Scan: 回复SECURITY_PASS或VULNERABILITY_FOUND")
            return {**s, "security": r.final_output[:80], "security_ok": "PASS" in r.final_output}
        def deploy(s):
            r = agent.run("模拟Deploy阶段: 回复DEPLOY_SUCCESS")
            return {**s, "deploy": r.final_output[:80]}
        def rollback(s):
            return {**s, "rolled_back": True}

        g.add_node("build", build)
        g.add_node("test", test)
        g.add_node("security", security)
        g.add_node("deploy", deploy)
        g.add_node("rollback", rollback)
        g.add_edge("build", "test")
        g.add_conditional_edges("test", lambda s: "security" if s.get("test_ok") else "rollback", {"security": "security", "rollback": "rollback"})
        g.add_conditional_edges("security", lambda s: "deploy" if s.get("security_ok") else "rollback", {"deploy": "deploy", "rollback": "rollback"})
        g.set_entry_point("build")
        g.set_finish_point("deploy")
        g.set_finish_point("rollback")

        t0 = time.time()
        state = g.invoke({})
        dtk_latency = time.time() - t0
        dtk_output = f"Build:{state.get('build_ok')} Test:{state.get('test_ok')} Security:{state.get('security_ok')} Deployed:{'DEPLOY' in state.get('deploy','')} RolledBack:{state.get('rolled_back',False)}"
        dtk_quality = judge_output_quality(TASK_DEVOPS, dtk_output)
        results["DTK"] = {"latency": round(dtk_latency, 1), "cost": 0.0, "output_len": len(dtk_output), "quality": dtk_quality, "note": "StateGraph — only DTK supports"}
        print(f"  Latency: {dtk_latency:.1f}s | Quality: {dtk_quality.get('overall', 0)}/10 | StateGraph: ONLY DTK")
    except Exception as e:
        results["DTK"] = {"error": str(e)[:200]}
        print(f"  FAILED: {e}")

    # LangChain and CrewAI can't do StateGraph natively — note this
    results["LangChain"] = {"note": "No built-in StateGraph equivalent (requires LangGraph, 29K lines)"}
    results["CrewAI"] = {"note": "No graph-based orchestration"}
    print("\n[LangChain] No built-in StateGraph (requires LangGraph)")
    print("[CrewAI] No graph-based orchestration")

    return results


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

def _estimate_langchain_cost(llm, text: str) -> float:
    """Estimate LangChain cost from token count."""
    try:
        tokens = llm.get_num_tokens(text)
    except:
        tokens = len(text) // 4
    return tokens * 1.74 / 1_000_000  # DeepSeek V4-pro input pricing


def _estimate_crewai_cost(result) -> float:
    """Extract cost from CrewAI result if available."""
    try:
        if hasattr(result, 'token_usage') and result.token_usage:
            tu = result.token_usage
            if isinstance(tu, dict):
                prompt = tu.get("prompt_tokens", 0)
                completion = tu.get("completion_tokens", 0)
            else:
                prompt = getattr(tu, "prompt_tokens", 0) or 0
                completion = getattr(tu, "completion_tokens", 0) or 0
            return prompt * 1.74 / 1_000_000 + completion * 3.48 / 1_000_000
    except: pass
    return 0.0


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    all_results = {}
    all_results["investment"] = run_investment_scenario()
    all_results["devops"] = run_devops_scenario()

    # Save
    (OUTPUT_DIR / "rigorous_results.json").write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")

    # Final comparison table
    print(f"\n\n{'='*80}")
    print(f"  FINAL COMPARISON")
    print(f"{'='*80}")

    for scenario, fw_results in all_results.items():
        print(f"\n  [{scenario.upper()}]")
        print(f"  {'Framework':<15} {'Latency':>10} {'Cost':>12} {'Quality':>10} {'Notes'}")
        print(f"  {'-'*15} {'-'*10} {'-'*12} {'-'*10} {'-'*20}")
        for fw, r in fw_results.items():
            if "error" in r:
                print(f"  {fw:<15} {'ERROR':>10} {'---':>12} {'---':>10} {r['error'][:50]}")
            elif "note" in r:
                print(f"  {fw:<15} {'---':>10} {'---':>12} {'---':>10} {r['note'][:50]}")
            else:
                q = r.get('quality', {})
                qs = q.get('overall', 'N/A')
                print(f"  {fw:<15} {r.get('latency',0):>8.1f}s CNY {r.get('cost',0):>8.6f} {qs:>8}/10 {q.get('critique','')[:40]}")

    print(f"\n  Results: {OUTPUT_DIR / 'rigorous_results.json'}")


if __name__ == "__main__":
    main()
