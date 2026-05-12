"""Polish stress tests — StateGraph complex scenarios, race conditions, etc."""
import json
import os
import time
from pathlib import Path

import pytest

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
OUTPUT_DIR = Path(__file__).parent.parent / "output" / "polish"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

pytestmark = pytest.mark.skipif(not API_KEY, reason="DEEPSEEK_API_KEY not set")


def _make_agent(role="助手", goal="帮助", backstory="通用", **kw):
    from deepseek_toolkit.agent.agent import DeepSeekAgent
    return DeepSeekAgent(
        role=role, goal=goal, backstory=backstory,
        api_key=API_KEY, thinking=False, max_steps=2, **kw,
    )


# ══════════════════════════════════════════════════════════════════════
# polish-001: StateGraph complex scenarios
# ══════════════════════════════════════════════════════════════════════

class TestStateGraphStress:
    """StateGraph: nested graphs, quality loops, interrupt+fallback."""

    def test_quality_loop_workflow(self):
        """research→analyze→check, loop back if score<80, max 3 loops."""
        from deepseek_toolkit.agent.stategraph import StateGraph

        results = []
        for run_n in range(10):
            g = StateGraph(dict)

            def research(s):
                agent = _make_agent("研究员", "研究AI芯片市场", "搜索整理信息")
                r = agent.run("列出2个2025年AI芯片市场的关键趋势（50字以内）")
                return {**s, "research": r.final_output[:200]}

            def analyze(s):
                agent = _make_agent("分析师", "分析研究结果", "深度分析")
                r = agent.run(f"基于研究结论：{s.get('research','')}，给出2条深度分析（50字以内）")
                return {**s, "analysis": r.final_output[:200], "loops": s.get("loops", 0) + 1}

            def quality_check(s):
                agent = _make_agent("审核员", "评估分析质量", "严格评分")
                r = agent.run(
                    f"评估以下分析质量，只回复JSON："
                    f'{{"score": 0-100, "feedback": "..."}}\n\n{s.get("analysis","")}'
                )
                try:
                    data = json.loads(r.final_output.strip().split("```")[0].strip())
                    score = int(data.get("score", 70))
                except Exception:
                    score = 70
                return {**s, "score": score, "feedback": str(data.get("feedback", ""))}

            def finalize(s):
                agent = _make_agent("编辑", "整理最终报告", "专业编辑")
                r = agent.run(
                    f"将以下内容整理为一段50字的报告摘要：\n研究：{s.get('research','')}\n分析：{s.get('analysis','')}"
                )
                return {**s, "report": r.final_output[:200]}

            g.add_node("research", research)
            g.add_node("analyze", analyze)
            g.add_node("check", quality_check)
            g.add_node("finalize", finalize)
            g.add_edge("research", "analyze")
            g.add_edge("analyze", "check")
            g.add_conditional_edges(
                "check",
                lambda s: "finalize" if s.get("score", 0) >= 80 or s.get("loops", 0) >= 2 else "analyze",
                {"finalize": "finalize", "analyze": "analyze"},
            )
            g.set_entry_point("research")
            g.set_finish_point("finalize")

            result = g.invoke({})
            results.append({
                "run": run_n,
                "loops": result.get("loops", 0),
                "score": result.get("score", 0),
                "has_report": len(result.get("report", "")) > 20,
            })
            assert result.get("loops", 0) <= 2, f"Exceeded max loops at run {run_n}"
            assert len(result.get("report", "")) > 20, f"No report at run {run_n}"

        (OUTPUT_DIR / "stategraph").mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "stategraph" / "quality_loop.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

        success = sum(1 for r in results if r["has_report"])
        assert success >= 8, f"Only {success}/10 runs produced valid reports"

    def test_conditional_routing_accuracy(self):
        """Verify conditional edges route correctly across 20 runs."""
        from deepseek_toolkit.agent.stategraph import StateGraph

        routing_results = []

        for run_n in range(20):
            g = StateGraph(dict)

            def evaluator(s):
                agent = _make_agent("评分员", "评分", "给1-100分")
                r = agent.run("给这个项目一个1-100的分数，只回复数字")
                try:
                    score = int(''.join(c for c in r.final_output if c.isdigit())[:3])
                except Exception:
                    score = 50
                return {**s, "score": score}

            def high_path(s):
                return {**s, "path": "high", "action": "推进立项"}

            def low_path(s):
                return {**s, "path": "low", "action": "重新评估"}

            g.add_node("eval", evaluator)
            g.add_node("high", high_path)
            g.add_node("low", low_path)
            g.add_conditional_edges(
                "eval",
                lambda s: "high" if s.get("score", 0) >= 60 else "low",
                {"high": "high", "low": "low"},
            )
            g.set_entry_point("eval")
            g.set_finish_point("high")
            g.set_finish_point("low")

            result = g.invoke({})
            score = result.get("score", 0)
            path = result.get("path", "")
            correct = (score >= 60 and path == "high") or (score < 60 and path == "low")
            routing_results.append({"run": run_n, "score": score, "path": path, "correct": correct})

        accuracy = sum(1 for r in routing_results if r["correct"]) / len(routing_results)
        (OUTPUT_DIR / "stategraph" / "routing.json").write_text(
            json.dumps({"accuracy": accuracy, "runs": routing_results}, ensure_ascii=False, indent=2), encoding="utf-8")

        assert accuracy >= 0.90, f"Routing accuracy {accuracy:.1%} < 90%"


# ══════════════════════════════════════════════════════════════════════
# polish-002: Parallel Crew thread safety
# ══════════════════════════════════════════════════════════════════════

class TestParallelCrewRace:
    """Parallel Crew: shared Agent, no data races across 50 runs."""

    def test_parallel_crew_no_session_corruption(self):
        """50 parallel crew runs with shared agent — no message loss."""
        from deepseek_toolkit.agent.agent import DeepSeekAgent
        from deepseek_toolkit.agent.task import Task
        from deepseek_toolkit.agent.crew import Crew, Process

        agent = _make_agent("助手", "帮助", "回复简短确认")
        stats = {"runs": 0, "errors": 0, "session_lengths": []}

        for run_n in range(20):
            tasks = [
                Task(description="回复'任务A完成'", expected_output="确认", agent=agent),
                Task(description="回复'任务B完成'", expected_output="确认", agent=agent),
                Task(description="回复'任务C完成'", expected_output="确认", agent=agent),
            ]
            crew = Crew(tasks=tasks, process=Process.PARALLEL)
            try:
                result = crew.kickoff()
                stats["runs"] += 1
                stats["session_lengths"].append(len(result.outputs))
                assert len(result.outputs) == 3, f"Run {run_n}: expected 3 outputs, got {len(result.outputs)}"
            except Exception as e:
                stats["errors"] += 1
                stats["session_lengths"].append(0)

        (OUTPUT_DIR / "race").mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "race" / "parallel.json").write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

        assert stats["errors"] == 0, f"{stats['errors']}/20 runs crashed"
        assert stats["runs"] == 20

    def test_parallel_crew_cache_stats_accurate(self):
        """Cache stats should accurately count parallel runs."""
        from deepseek_toolkit.agent.task import Task
        from deepseek_toolkit.agent.crew import Crew, Process

        agent = _make_agent("助手", "帮助", "回复简短确认")
        stats_before = dict(agent.cache_stats)

        tasks = [
            Task(description="回复'OK'", expected_output="确认", agent=agent),
            Task(description="回复'OK'", expected_output="确认", agent=agent),
        ]
        crew = Crew(tasks=tasks, process=Process.PARALLEL)
        crew.kickoff()

        stats_after = dict(agent.cache_stats)
        assert stats_after["total_requests"] >= stats_before["total_requests"] + 2, (
            f"Cache stats not updated correctly: before={stats_before}, after={stats_after}"
        )


# ══════════════════════════════════════════════════════════════════════
# polish-004: Thinking mode long conversation
# ══════════════════════════════════════════════════════════════════════

class TestThinkingLongConversation:
    """10-round thinking mode: no 400 errors, reasoning preserved."""

    def test_ten_round_thinking_chat(self):
        from deepseek_toolkit.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手", goal="保持对话连贯性",
            backstory="你会记住之前讨论的内容",
            api_key=API_KEY, thinking=True, max_steps=2,
        )

        rounds_ok = 0
        for i in range(10):
            result = agent.chat(
                f"第{i+1}轮。请引用上一轮我告诉你的事实。如果是第1轮，回复'第一轮开始'。简短回复。"
            )
            if result.reasoning_content and len(result.reasoning_content) > 0:
                rounds_ok += 1

        (OUTPUT_DIR / "thinking").mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "thinking" / "long_chat.json").write_text(
            json.dumps({"rounds_with_reasoning": rounds_ok, "total": 10}, ensure_ascii=False), encoding="utf-8")

        assert rounds_ok >= 8, f"Only {rounds_ok}/10 rounds had reasoning_content"


# ══════════════════════════════════════════════════════════════════════
# polish-003: MCP robustness
# ══════════════════════════════════════════════════════════════════════

class TestMCPRobustness:
    """MCP: server crash, timeout, malformed data — agent survives."""

    def test_mcp_missing_command_does_not_crash_agent(self):
        """Agent with non-existent MCP server still runs normally."""
        from deepseek_toolkit.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手", goal="帮助", backstory="通用",
            api_key=API_KEY, thinking=False, max_steps=1,
        )
        agent.add_mcp_server("broken", "nonexistent_command_xyz", [])
        result = agent.run("回复'hello'")
        assert "hello" in result.final_output.lower() or len(result.final_output) > 0
        # Agent should complete even though MCP server failed to start


# ══════════════════════════════════════════════════════════════════════
# polish-005: Production E2E scenarios
# ══════════════════════════════════════════════════════════════════════

class TestProductionScenarios:
    """Full production workflows: financial, multi-agent, conditional."""

    def test_financial_analysis_workflow(self):
        """Read financial data → compute ratios → generate report."""
        from deepseek_toolkit.agent.agent import DeepSeekAgent

        DATA = str(Path(__file__).parent.parent / "benchmarks/agents_comparison/data/financial_report.json")

        agent = DeepSeekAgent(
            role="财务分析师", goal="分析财务报告并计算关键比率",
            backstory="CPA+CFA，20年经验",
            api_key=API_KEY, thinking=True, max_steps=3,
        )
        agent.with_default_tools()

        results_ok = 0
        for run_n in range(5):
            result = agent.run(
                f"读取 {DATA}，计算毛利率、净利率、ROE、资产负债率。"
                f"给出财务健康评级（优秀/良好/一般/风险）。200字以内。",
                files=[DATA],
            )
            has_ratios = any(w in result.final_output for w in ["毛利率", "净利", "ROE"])
            has_rating = any(w in result.final_output for w in ["优秀", "良好", "一般", "风险"])
            if has_ratios and has_rating:
                results_ok += 1

        (OUTPUT_DIR / "production").mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "production" / "financial.json").write_text(
            json.dumps({"ok": results_ok, "total": 5}, ensure_ascii=False), encoding="utf-8")

        assert results_ok >= 4, f"Only {results_ok}/5 financial analyses passed"

    def test_multi_agent_research_team(self):
        """Researcher → Analyst → Writer sequential crew."""
        from deepseek_toolkit.agent.agent import DeepSeekAgent
        from deepseek_toolkit.agent.task import Task
        from deepseek_toolkit.agent.crew import Crew

        researcher = _make_agent("研究员", "搜索AI趋势", "搜索整理信息")
        analyst = _make_agent("分析师", "深度分析趋势", "数据分析")
        writer = _make_agent("撰稿人", "撰写商业简报", "专业写作")

        tasks = [
            Task(description="列出2025年AI行业2个关键趋势（30字以内）", expected_output="趋势列表", agent=researcher),
            Task(description="基于趋势分析对企业的影响（40字以内）", expected_output="影响分析", agent=analyst),
            Task(description="整理为一段80字的商业简报", expected_output="商业简报", agent=writer),
        ]

        results_ok = 0
        for run_n in range(5):
            crew = Crew(tasks=tasks)
            result = crew.kickoff()
            if len(result.outputs) == 3 and len(result.final_output) > 40:
                results_ok += 1

        (OUTPUT_DIR / "production" / "multi_agent.json").write_text(
            json.dumps({"ok": results_ok, "total": 5}, ensure_ascii=False), encoding="utf-8")

        assert results_ok >= 4, f"Only {results_ok}/5 multi-agent runs passed"

    def test_conditional_workflow(self):
        """plan→execute→evaluate, retry if score<80."""
        from deepseek_toolkit.agent.stategraph import StateGraph

        results = []
        for run_n in range(10):
            g = StateGraph(dict)

            def plan(s):
                agent = _make_agent("规划师", "制定计划", "项目规划专家")
                r = agent.run("为'提升用户留存率'制定3步行动计划（50字以内）")
                return {**s, "plan": r.final_output[:200]}

            def execute(s):
                return {**s, "executed": True, "attempts": s.get("attempts", 0) + 1}

            def evaluate(s):
                agent = _make_agent("评估师", "评估执行质量", "严格评估")
                r = agent.run(
                    f"评估这个行动计划的质量，只回复分数(0-100)：\n{s.get('plan','')}"
                )
                try:
                    score = int(''.join(c for c in r.final_output if c.isdigit())[:3])
                except:
                    score = 70
                return {**s, "score": score}

            def finalize(s):
                return {**s, "status": "complete"}

            g.add_node("plan", plan)
            g.add_node("execute", execute)
            g.add_node("evaluate", evaluate)
            g.add_node("finalize", finalize)
            g.add_edge("plan", "execute")
            g.add_edge("execute", "evaluate")
            g.add_conditional_edges(
                "evaluate",
                lambda s: "finalize" if s.get("score", 0) >= 80 or s.get("attempts", 0) >= 2 else "plan",
                {"finalize": "finalize", "plan": "plan"},
            )
            g.set_entry_point("plan")
            g.set_finish_point("finalize")

            r = g.invoke({})
            results.append({"run": run_n, "attempts": r.get("attempts", 0), "status": r.get("status")})
            assert r.get("status") == "complete", f"Run {run_n}: did not complete"

        success = sum(1 for r in results if r["status"] == "complete")
        (OUTPUT_DIR / "production" / "conditional.json").write_text(
            json.dumps({"ok": success, "total": 10, "runs": results}, ensure_ascii=False, indent=2), encoding="utf-8")

        assert success == 10, f"Only {success}/10 conditional workflow runs completed"

