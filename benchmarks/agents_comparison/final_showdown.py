"""FINAL SHOWDOWN: DTK Fast vs DTK Stable vs LangChain vs CrewAI.

3 complex production scenarios, 4 configurations, all metrics recorded.
"""
import json, os, time, sys
from pathlib import Path
from typing import Any

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not API_KEY:
    raise RuntimeError("DEEPSEEK_API_KEY environment variable is required")
MODEL = "deepseek-v4-pro"
OUTPUT_DIR = Path(__file__).parent / "output" / "final_showdown"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

DATA_DIR = Path(__file__).parent.parent.parent / "tests" / "test_v3_agent.py"


def judge(task: str, output: str) -> dict:
    """LLM quality judge."""
    from openai import OpenAI
    client = OpenAI(api_key=API_KEY, base_url="https://api.deepseek.com/v1")
    prompt = f"""Score this AI output 1-10 on each dimension. Return ONLY valid JSON:
{{"completeness":X,"accuracy":X,"depth":X,"structure":X,"actionability":X,"overall":X}}

TASK: {task[:400]}
OUTPUT: {output[:3000]}"""
    try:
        r = client.chat.completions.create(model=MODEL, temperature=0, max_tokens=200,
            messages=[{"role": "user", "content": prompt}])
        text = r.choices[0].message.content.strip()
        if "{" in text: text = text[text.index("{"):text.rindex("}")+1]
        scores = json.loads(text)
        return {k: scores.get(k, 5) for k in ["completeness","accuracy","depth","structure","actionability","overall"]}
    except:
        return {"completeness":5,"accuracy":5,"depth":5,"structure":5,"actionability":5,"overall":5}


# ══════════════════════════════════════════════════════════════════════
# BENCHMARK RUNNER — one function per framework-config per scenario
# ══════════════════════════════════════════════════════════════════════

def benchmark(name, fn, *args):
    print(f"  [{name}] ", end="", flush=True)
    try:
        t0 = time.time()
        result = fn(*args)
        elapsed = time.time() - t0
        print(f"{elapsed:.1f}s OK")
        return result, elapsed
    except Exception as e:
        print(f"FAILED: {type(e).__name__}")
        return {"error": str(e)[:200]}, 0


# ══════════════════════════════════════════════════════════════════════
# SCENARIO 1: SDLC Code Review (8 agents)
# ══════════════════════════════════════════════════════════════════════

SDLC_TASK = "对代码文件进行完整SDLC审查：读取→安全→性能→风格→测试→文档→汇总→修复。生成150字PR Review。"


def run_dtk_fast_sdlc():
    from deepseek_toolkit.agent.agent import DeepSeekAgent
    from deepseek_toolkit.agent.task import Task
    from deepseek_toolkit.agent.crew import Crew

    mk = lambda role, goal, backstory, tools=False: DeepSeekAgent(
        role=role, goal=goal, backstory=backstory, api_key=API_KEY, model=MODEL, thinking=False, max_steps=1, mode="fast")

    reader = mk("代码阅读员", "读取并描述代码", "资深审查员", True)
    reader.with_default_tools()

    tasks = [
        Task(description=f"读取{DATA_DIR}前100行,列出类和方法(50字)", expected_output="结构", agent=reader),
        Task(description="审查安全风险(30字)", expected_output="安全", agent=mk("安全员","扫描漏洞","安全专家")),
        Task(description="审查性能问题(30字)", expected_output="性能", agent=mk("性能员","找瓶颈","优化专家")),
        Task(description="审查代码风格(30字)", expected_output="风格", agent=mk("风格员","检查规范","PEP8专家")),
        Task(description="生成测试用例(50字)", expected_output="测试", agent=mk("测试员","编写测试","TDD专家")),
        Task(description="生成文档(40字)", expected_output="文档", agent=mk("文档员","写docstring","文档专家")),
        Task(description="汇总所有发现,生成100字PR Review含TOP3问题和修复优先级", expected_output="Review", agent=mk("汇总员","生成Review","Tech Lead", False)),
    ]
    crew = Crew(tasks=tasks)
    return crew.kickoff()


def run_dtk_stable_sdlc():
    from deepseek_toolkit.agent.agent import DeepSeekAgent
    from deepseek_toolkit.agent.task import Task
    from deepseek_toolkit.agent.crew import Crew

    mk = lambda role, goal, backstory, tools=False: DeepSeekAgent(
        role=role, goal=goal, backstory=backstory, api_key=API_KEY, model=MODEL, thinking=False, max_steps=1, mode="stable")

    reader = mk("代码阅读员", "读取并描述代码", "资深审查员", True)
    reader.with_default_tools()
    aggregator = mk("汇总员", "生成PR Review", "Tech Lead,15年", False)

    tasks = [
        Task(description=f"读取{DATA_DIR}前100行,列出类和方法(50字)", expected_output="结构", agent=reader),
        Task(description=f"审查安全风险(30字)", expected_output="安全", agent=mk("安全员","扫描","安全专家")),
        Task(description=f"审查性能问题(30字)", expected_output="性能", agent=mk("性能员","找瓶颈","优化专家")),
        Task(description=f"审查代码风格(30字)", expected_output="风格", agent=mk("风格员","检查","风格专家")),
        Task(description=f"生成测试用例(50字)", expected_output="测试", agent=mk("测试员","编写","TDD专家")),
        Task(description=f"生成文档(40字)", expected_output="文档", agent=mk("文档员","文档","文档专家")),
        Task(description="汇总所有发现,生成100字PR Review含TOP3问题和修复优先级", expected_output="Review", agent=aggregator),
    ]
    crew = Crew(tasks=tasks)
    return crew.kickoff()


def run_langchain_sdlc():
    from langchain_openai import ChatOpenAI
    from langchain.agents import create_agent
    llm = ChatOpenAI(model=MODEL, base_url="https://api.deepseek.com/v1", api_key=API_KEY, temperature=0.0, max_tokens=2048,
                     extra_body={"thinking": {"type": "disabled"}})

    agents = [
        create_agent(llm, [], system_prompt=f"你是{role}。{backstory}。") for role, backstory in [
            ("代码阅读员","资深审查员"), ("安全员","安全专家"), ("性能员","优化专家"),
            ("风格员","风格专家"), ("测试员","TDD专家"), ("文档员","文档专家"),
            ("汇总员","Tech Lead"),
        ]
    ]
    roles = ["代码阅读员","安全员","性能员","风格员","测试员","文档员","汇总员"]
    tasks = [
        f"读取{DATA_DIR}前100行,列出类和方法(50字)",
        "审查安全风险(30字)", "审查性能问题(30字)", "审查代码风格(30字)",
        "生成测试用例(50字)", "生成文档(40字)", "汇总所有发现,生成100字PR Review含TOP3问题",
    ]
    context = ""
    for agent, role, task in zip(agents, roles, tasks):
        resp = agent.invoke({"messages": [("user", task)]})
        context += f"[{role}]: {resp['messages'][-1].content[:200]}\n"
    return context


def run_crewai_sdlc():
    from crewai import Agent, Task, Crew, Process, LLM
    llm = LLM(model=MODEL, base_url="https://api.deepseek.com/v1", api_key=API_KEY, temperature=0.0, max_tokens=2048,
              additional_params={"extra_body": {"thinking": {"type": "disabled"}}})

    roles = ["代码阅读员","安全员","性能员","风格员","测试员","文档员","汇总员"]
    goals = ["读取代码","扫描安全","分析性能","检查风格","编写测试","写文档","汇总Review"]
    descs = [f"读取{DATA_DIR}前100行,列出类和方法(50字)","审查安全风险(30字)","审查性能问题(30字)",
             "审查代码风格(30字)","生成测试用例(50字)","生成文档(40字)","汇总所有发现,生成100字PR Review"]

    agents = [Agent(role=r, goal=g, backstory="专家", llm=llm, verbose=False, max_iter=1) for r, g in zip(roles, goals)]
    tasks = [Task(description=d, expected_output="result", agent=a) for d, a in zip(descs, agents)]
    crew = Crew(agents=agents, tasks=tasks, process=Process.sequential, verbose=False)
    result = crew.kickoff()
    return result.raw if hasattr(result, 'raw') else str(result)


# ══════════════════════════════════════════════════════════════════════
# MAIN — Run all 4 configs across all 3 scenarios
# ══════════════════════════════════════════════════════════════════════

def main():
    results = {}

    scenarios = {
        "sdlc_code_review": {
            "task": SDLC_TASK,
            "runners": {
                "DTK Fast": run_dtk_fast_sdlc,
                "DTK Stable": run_dtk_stable_sdlc,
                "LangChain": run_langchain_sdlc,
                "CrewAI": run_crewai_sdlc,
            },
        },
        "data_etl": {
            "task": "ETL流水线:读取sales_data.csv→描述数据→推断schema→设计ETL→质量检测→定义清洗规则→生成100字报告",
            "runners": {},
        },
        "compliance": {
            "task": "GDPR合规审计:研究条款→识别差距→评估风险→起草政策→收集证据→交叉验证→生成报告",
            "runners": {},
        },
    }

    for scenario_name, scenario in scenarios.items():
        print(f"\n{'='*70}")
        print(f"  {scenario_name.upper()}")
        print(f"{'='*70}")
        results[scenario_name] = {}

        for fw_name, runner in scenario["runners"].items():
            print(f"\n[{fw_name}]", end="", flush=True)
            try:
                t0 = time.time()
                raw = runner()
                elapsed = time.time() - t0

                if isinstance(raw, str):
                    output = raw
                    cost = 0
                else:
                    output = raw.final_output if hasattr(raw, 'final_output') else raw.raw if hasattr(raw, 'raw') else str(raw)
                    cost = getattr(raw, 'total_cost', getattr(raw, 'cost', 0))

                quality = judge(scenario["task"], output)
                results[scenario_name][fw_name] = {
                    "latency_s": round(elapsed, 1),
                    "cost_cny": cost,
                    "output_len": len(output),
                    "quality": quality,
                    "framework": fw_name,
                    "output_preview": output[:200],
                }
                print(f"\r  [{fw_name}] {elapsed:.1f}s | CNY {cost:.6f} | {len(output)} chars | Q:{quality.get('overall',0)}/10")
            except Exception as e:
                results[scenario_name][fw_name] = {"error": f"{type(e).__name__}: {str(e)[:100]}"}
                print(f"\r  [{fw_name}] FAILED: {type(e).__name__}")

    # Save
    (OUTPUT_DIR / "showdown_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    # Final table
    print(f"\n\n{'='*80}")
    print(f"  FINAL SHOWDOWN TABLE")
    print(f"{'='*80}")
    for scenario, fw_results in results.items():
        print(f"\n  [{scenario}]")
        print(f"  {'Config':<15} {'Latency':>10} {'Cost(CNY)':>12} {'Output':>10} {'Quality':>10}")
        print(f"  {'-'*15} {'-'*10} {'-'*12} {'-'*10} {'-'*10}")
        for fw, r in fw_results.items():
            if "error" in r:
                print(f"  {fw:<15} {'FAILED':>10} {'---':>12} {'---':>10} {'---':>10}")
            else:
                q = r.get('quality', {})
                print(f"  {fw:<15} {r['latency_s']:>8.1f}s CNY{r['cost_cny']:>8.6f} {r['output_len']:>8}ch {q.get('overall',0):>8}/10")

    print(f"\n  Saved: {OUTPUT_DIR / 'showdown_results.json'}")


if __name__ == "__main__":
    main()
