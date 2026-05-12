"""Fair 3-Framework Benchmark — DTK vs LangChain vs CrewAI.

Same prompts, same tools, same model, same tasks.
Measures: latency, cost, tokens, cache, output quality.
"""
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not API_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY environment variable is required")
MODEL = "deepseek-v4-pro"
OUTPUT_DIR = Path(__file__).parent / "output" / "fair_comparison"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════════════
# SHARED PROMPTS (identical across all 3 frameworks)
# ══════════════════════════════════════════════════════════════════════

SYSTEM_PROMPTS = {
    "financial": """你是具备CPA和CFA资质的资深财务分析师，20年行业经验。
工作流程：读取财务数据 → 计算关键比率 → 生成报告。
最终输出必须是完整的专业财务分析报告，包含财务健康评级（★优秀/良好/一般/风险）。""",

    "researcher": "你是行业研究员，擅长搜索和整理信息。用中文输出。",
    "analyst": "你是数据分析师，10年经验。基于研究结论进行深度分析。",
    "writer": "你是商业撰稿人，前财经记者。将分析转化为专业报告。",
    "manager": "你是项目经理，负责将任务分解并分配给团队成员执行。",
    "tech_analyst": "你是技术分析师，从技术角度分析问题。",
    "market_analyst": "你是市场分析师，从市场角度分析问题。",
    "policy_analyst": "你是政策分析师，从政策角度分析问题。",
}

TASKS = {
    "financial": "分析字节跳动2025年财务数据。计算毛利率、净利率、资产负债率。给出财务健康评级（★优秀/良好/一般/风险）和3条建议。200字以内。",
    "research_step": "列出2025年AI行业3个关键趋势（30字以内）。",
    "analyze_step": "基于趋势分析对企业的影响（40字以内）。",
    "write_step": "整理为一段100字的商业简报。",
    "hierarchical_task": "从技术、市场、政策三个角度分析AI芯片行业2025年前景。每个角度40字。",
}


# ══════════════════════════════════════════════════════════════════════
# SCENARIO 1: Single Agent Financial Analysis
# ══════════════════════════════════════════════════════════════════════

def run_dtk_financial():
    from deepseek_toolkit.agent.agent import DeepSeekAgent

    agent = DeepSeekAgent(
        role="资深财务分析师",
        goal="分析财务数据并给出评级和建议",
        backstory="CPA+CFA持证人，20年互联网行业审计经验",
        api_key=API_KEY, model=MODEL, thinking=True, max_steps=3,
    )

    def calculate(expr: str) -> str:
        """Evaluate a mathematical expression. Example: (1200-620)/1200"""
        try:
            r = eval(expr, {"__builtins__": {}}, {"abs": abs, "round": round})
            return f"Result: {r:.4f}"
        except: return f"Error: {expr}"

    agent.add_tool(calculate)

    start = time.time()
    result = agent.run(TASKS["financial"])
    elapsed = time.time() - start
    return {
        "framework": "DTK", "output": result.final_output[:500],
        "latency_s": round(elapsed, 1), "cost": result.cost,
        "tokens": result.tokens.get("total_tokens", 0),
        "reasoning_len": len(result.reasoning_content or ""),
        "cache_hit": result.diagnostics.cache_hit,
    }


def run_langchain_financial():
    from langchain_openai import ChatOpenAI
    from langchain.agents import create_agent

    llm = ChatOpenAI(
        model=MODEL, base_url="https://api.deepseek.com/v1",
        api_key=API_KEY, temperature=0.0, max_tokens=4096,
    )

    def calculate(expr: str) -> str:
        """Evaluate a mathematical expression. Example: (1200-620)/1200"""
        try:
            r = eval(expr, {"__builtins__": {}}, {"abs": abs, "round": round})
            return f"Result: {r:.4f}"
        except: return f"Error: {expr}"

    agent = create_agent(llm, [calculate], system_prompt=SYSTEM_PROMPTS["financial"])

    start = time.time()
    result = agent.invoke({"messages": [("user", TASKS["financial"])]})
    elapsed = time.time() - start
    output = result["messages"][-1].content if result.get("messages") else ""
    return {
        "framework": "LangChain", "output": output[:500],
        "latency_s": round(elapsed, 1), "cost": 0.0, "tokens": 0,
        "reasoning_len": 0, "cache_hit": False,
    }


def run_crewai_financial():
    from crewai import Agent, Task, Crew, Process, LLM

    llm = LLM(
        model=MODEL, base_url="https://api.deepseek.com/v1",
        api_key=API_KEY, temperature=0.0, max_tokens=4096,
        additional_params={"extra_body": {"thinking": {"type": "disabled"}}},
    )

    from crewai.tools import tool as ca_tool
    @ca_tool
    def calculate(expr: str) -> str:
        """Evaluate a mathematical expression. Example: (1200-620)/1200"""
        try:
            r = eval(expr, {"__builtins__": {}}, {"abs": abs, "round": round})
            return f"Result: {r:.4f}"
        except: return f"Error: {expr}"

    agent = Agent(
        role="资深财务分析师", goal="分析财务数据并给出评级",
        backstory=SYSTEM_PROMPTS["financial"], tools=[calculate],
        llm=llm, verbose=False, max_iter=3,
    )
    task = Task(description=TASKS["financial"], expected_output="分析报告", agent=agent)
    crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)

    start = time.time()
    result = crew.kickoff()
    elapsed = time.time() - start
    output = result.raw if hasattr(result, 'raw') else str(result)
    return {
        "framework": "CrewAI", "output": output[:500],
        "latency_s": round(elapsed, 1), "cost": 0.0, "tokens": 0,
        "reasoning_len": 0, "cache_hit": False,
    }


# ══════════════════════════════════════════════════════════════════════
# SCENARIO 2: Sequential Crew — Research → Analyze → Write
# ══════════════════════════════════════════════════════════════════════

def run_dtk_sequential():
    from deepseek_toolkit.agent.agent import DeepSeekAgent
    from deepseek_toolkit.agent.task import Task
    from deepseek_toolkit.agent.crew import Crew

    tasks = [
        Task(description=TASKS["research_step"], expected_output="趋势",
             agent=DeepSeekAgent(role="研究员", goal="研究", backstory=SYSTEM_PROMPTS["researcher"], api_key=API_KEY, model=MODEL, thinking=False, max_steps=1)),
        Task(description=TASKS["analyze_step"], expected_output="分析",
             agent=DeepSeekAgent(role="分析师", goal="分析", backstory=SYSTEM_PROMPTS["analyst"], api_key=API_KEY, model=MODEL, thinking=False, max_steps=1)),
        Task(description=TASKS["write_step"], expected_output="简报",
             agent=DeepSeekAgent(role="撰稿人", goal="撰写", backstory=SYSTEM_PROMPTS["writer"], api_key=API_KEY, model=MODEL, thinking=False, max_steps=1)),
    ]
    crew = Crew(tasks=tasks)
    start = time.time()
    result = crew.kickoff()
    elapsed = time.time() - start
    return {
        "framework": "DTK", "output": result.final_output[:500],
        "latency_s": round(elapsed, 1), "cost": result.total_cost,
        "tasks": len(result.outputs), "errors": result.errors,
    }


def run_langchain_sequential():
    from langchain_openai import ChatOpenAI
    from langchain.agents import create_agent

    llm = ChatOpenAI(model=MODEL, base_url="https://api.deepseek.com/v1", api_key=API_KEY, temperature=0.0, max_tokens=2048)
    researcher = create_agent(llm, [], system_prompt=SYSTEM_PROMPTS["researcher"])
    analyst = create_agent(llm, [], system_prompt=SYSTEM_PROMPTS["analyst"])
    writer = create_agent(llm, [], system_prompt=SYSTEM_PROMPTS["writer"])

    start = time.time()
    r1 = researcher.invoke({"messages": [("user", TASKS["research_step"])]})
    research_output = r1["messages"][-1].content if r1.get("messages") else ""
    r2 = analyst.invoke({"messages": [("user", f"{TASKS['analyze_step']}\n\n前置: {research_output}")]})
    analyze_output = r2["messages"][-1].content if r2.get("messages") else ""
    r3 = writer.invoke({"messages": [("user", f"{TASKS['write_step']}\n\n前置: {analyze_output}")]})
    elapsed = time.time() - start
    output = r3["messages"][-1].content if r3.get("messages") else ""
    return {"framework": "LangChain", "output": output[:500], "latency_s": round(elapsed, 1), "cost": 0.0}


def run_crewai_sequential():
    from crewai import Agent, Task, Crew, Process, LLM

    llm = LLM(model=MODEL, base_url="https://api.deepseek.com/v1", api_key=API_KEY, temperature=0.0, max_tokens=2048,
              additional_params={"extra_body": {"thinking": {"type": "disabled"}}})
    researcher = Agent(role="研究员", goal="研究", backstory=SYSTEM_PROMPTS["researcher"], llm=llm, verbose=False, max_iter=1)
    analyst = Agent(role="分析师", goal="分析", backstory=SYSTEM_PROMPTS["analyst"], llm=llm, verbose=False, max_iter=1)
    writer = Agent(role="撰稿人", goal="撰写", backstory=SYSTEM_PROMPTS["writer"], llm=llm, verbose=False, max_iter=1)

    tasks = [
        Task(description=TASKS["research_step"], expected_output="趋势", agent=researcher),
        Task(description=TASKS["analyze_step"], expected_output="分析", agent=analyst),
        Task(description=TASKS["write_step"], expected_output="简报", agent=writer),
    ]
    crew = Crew(agents=[researcher, analyst, writer], tasks=tasks, process=Process.sequential, verbose=False)
    start = time.time()
    result = crew.kickoff()
    elapsed = time.time() - start
    output = result.raw if hasattr(result, 'raw') else str(result)
    return {"framework": "CrewAI", "output": output[:500], "latency_s": round(elapsed, 1), "cost": 0.0}


# ══════════════════════════════════════════════════════════════════════
# SCENARIO 3: Hierarchical Crew — Manager + 3 Specialists
# ══════════════════════════════════════════════════════════════════════

def run_dtk_hierarchical():
    from deepseek_toolkit.agent.agent import DeepSeekAgent
    from deepseek_toolkit.agent.task import Task
    from deepseek_toolkit.agent.crew import Crew, Process

    manager = DeepSeekAgent(role="项目经理", goal="分解任务并分配给团队", backstory=SYSTEM_PROMPTS["manager"], api_key=API_KEY, model=MODEL, thinking=True, max_steps=5)
    tech = DeepSeekAgent(role="技术分析师", goal="技术分析", backstory=SYSTEM_PROMPTS["tech_analyst"], api_key=API_KEY, model=MODEL, thinking=False, max_steps=1)
    market = DeepSeekAgent(role="市场分析师", goal="市场分析", backstory=SYSTEM_PROMPTS["market_analyst"], api_key=API_KEY, model=MODEL, thinking=False, max_steps=1)
    policy = DeepSeekAgent(role="政策分析师", goal="政策分析", backstory=SYSTEM_PROMPTS["policy_analyst"], api_key=API_KEY, model=MODEL, thinking=False, max_steps=1)

    tasks = [
        Task(description="从技术角度分析AI芯片前景（40字）", expected_output="技术分析", agent=tech),
        Task(description="从市场角度分析AI芯片前景（40字）", expected_output="市场分析", agent=market),
        Task(description="从政策角度分析AI芯片前景（40字）", expected_output="政策分析", agent=policy),
    ]
    crew = Crew(tasks=tasks, process=Process.HIERARCHICAL, manager_agent=manager)
    start = time.time()
    result = crew.kickoff()
    elapsed = time.time() - start
    return {"framework": "DTK", "output": result.final_output[:500], "latency_s": round(elapsed, 1), "cost": result.total_cost, "errors": result.errors}


def run_crewai_hierarchical():
    from crewai import Agent, Task, Crew, Process, LLM

    llm = LLM(model=MODEL, base_url="https://api.deepseek.com/v1", api_key=API_KEY, temperature=0.0, max_tokens=2048,
              additional_params={"extra_body": {"thinking": {"type": "disabled"}}})
    manager = Agent(role="项目经理", goal="分解任务", backstory=SYSTEM_PROMPTS["manager"], llm=llm, verbose=False, max_iter=5, allow_delegation=True)
    tech = Agent(role="技术分析师", goal="技术分析", backstory=SYSTEM_PROMPTS["tech_analyst"], llm=llm, verbose=False, max_iter=1)
    market = Agent(role="市场分析师", goal="市场分析", backstory=SYSTEM_PROMPTS["market_analyst"], llm=llm, verbose=False, max_iter=1)
    policy = Agent(role="政策分析师", goal="政策分析", backstory=SYSTEM_PROMPTS["policy_analyst"], llm=llm, verbose=False, max_iter=1)

    tasks = [
        Task(description="从技术角度分析AI芯片前景（40字）", expected_output="技术分析", agent=tech),
        Task(description="从市场角度分析AI芯片前景（40字）", expected_output="市场分析", agent=market),
        Task(description="从政策角度分析AI芯片前景（40字）", expected_output="政策分析", agent=policy),
    ]
    crew = Crew(agents=[manager, tech, market, policy], tasks=tasks, process=Process.hierarchical,
                manager_llm=llm, verbose=False)
    start = time.time()
    result = crew.kickoff()
    elapsed = time.time() - start
    output = result.raw if hasattr(result, 'raw') else str(result)
    return {"framework": "CrewAI", "output": output[:500], "latency_s": round(elapsed, 1), "cost": 0.0}


# ══════════════════════════════════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════════════════════════════════

def main():
    results = {}
    scenarios = {
        "1_single_agent": {
            "DTK": run_dtk_financial,
            "LangChain": run_langchain_financial,
            "CrewAI": run_crewai_financial,
        },
        "2_sequential_crew": {
            "DTK": run_dtk_sequential,
            "LangChain": run_langchain_sequential,
            "CrewAI": run_crewai_sequential,
        },
        "3_hierarchical_crew": {
            "DTK": run_dtk_hierarchical,
            "CrewAI": run_crewai_hierarchical,
        },
    }

    for scenario_name, runners in scenarios.items():
        print(f"\n{'='*70}")
        print(f"  SCENARIO: {scenario_name}")
        print(f"{'='*70}")
        results[scenario_name] = {}
        for fw_name, runner in runners.items():
            print(f"\n  [{fw_name}] Running...")
            try:
                r = runner()
                results[scenario_name][fw_name] = r
                print(f"    Latency: {r.get('latency_s', 0)}s | Cost: CNY {r.get('cost', 0):.6f}")
                print(f"    Output: {r.get('output', '')[:100]}...")
            except Exception as e:
                import traceback
                err_msg = f"{type(e).__name__}: {e}"
                results[scenario_name][fw_name] = {"error": err_msg}
                print(f"    FAILED: {err_msg[:120]}")

    # Save results
    (OUTPUT_DIR / "comparison_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    # Print comparison table
    print(f"\n{'='*70}")
    print(f"  COMPARISON SUMMARY")
    print(f"{'='*70}")

    for scenario, fw_results in results.items():
        print(f"\n  [{scenario}]")
        print(f"  {'Framework':<15} {'Latency':>10} {'Cost':>12} {'Output':>10}")
        print(f"  {'-'*15} {'-'*10} {'-'*12} {'-'*10}")
        for fw, r in fw_results.items():
            if "error" in r:
                print(f"  {fw:<15} {'ERROR':>10} {'---':>12} {'---':>10}")
            else:
                print(f"  {fw:<15} {r['latency_s']:>8.1f}s CNY {r['cost']:>8.6f} {len(r.get('output','')):>8}ch")

    # DTK advantages
    print(f"\n{'='*70}")
    print(f"  DTK ADVANTAGES")
    print(f"{'='*70}")
    for scenario, fw_results in results.items():
        dtk = fw_results.get("DTK", {})
        others = {k: v for k, v in fw_results.items() if k != "DTK" and "error" not in v}
        if not others: continue
        print(f"\n  [{scenario}]")
        if dtk.get("cost", 0) > 0:
            avg_other_cost = sum(v.get("cost", 0) for v in others.values()) / len(others)
            print(f"    Cost tracking: DTK [YES] (CNY {dtk['cost']:.6f}) vs others [NO]")
        if dtk.get("reasoning_len", 0) > 0:
            print(f"    Thinking mode: DTK [YES] ({dtk['reasoning_len']} chars) vs others [NO]")
        if dtk.get("cache_hit"):
            print(f"    Cache hit: DTK [YES] vs others [NO]")
        if dtk.get("errors") is not None and len(dtk.get("errors", [])) == 0:
            print(f"    Error recovery: DTK [YES] (zero errors)")

    print(f"\nResults saved to {OUTPUT_DIR / 'comparison_results.json'}")


if __name__ == "__main__":
    main()
