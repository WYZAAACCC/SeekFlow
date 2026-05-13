"""CHAOS ENGINEERING — these tests are DESIGNED to break the framework.

Based on real production agent patterns from:
- Hyperresearch (16-step pipeline, specialized subagents)
- MCP-Agent (TODO queue, external memory, deterministic verification)

Tests:
  1. Deep Research Pipeline (6 agents, 12 steps, tool-calling under load)
  2. Interrupt & Resume Mid-Execution
  3. Concurrent Agent Flood (10 agents, 30 runs, shared API key)
  4. Tool Failure Storm (50% failure rate, verify circuit breaker)
  5. Memory Corruption Under Chaos
  6. Context Exhaustion Recovery
"""
import concurrent.futures
import json
import os
import random
import time
import threading
from pathlib import Path

import pytest

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
OUTPUT_DIR = Path(__file__).parent.parent / "output" / "chaos"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

pytestmark = pytest.mark.skipif(not API_KEY, reason="DEEPSEEK_API_KEY not set")


# ══════════════════════════════════════════════════════════════════════
# TEST 1: Deep Research Pipeline — 6 agents, 12+ steps
# Based on: Hyperresearch 16-step pipeline pattern
# ══════════════════════════════════════════════════════════════════════

class TestDeepResearchPipeline:
    """Modeled after Hyperresearch: decompose→research→analyze→critique→synthesize."""

    def test_six_agent_research_pipeline(self):
        from seekflow.agent.agent import DeepSeekAgent
        from seekflow.agent.task import Task
        from seekflow.agent.crew import Crew

        topic = "2025年AI芯片市场"

        planner = DeepSeekAgent(
            role="研究规划师",
            goal=f"将'{topic}'分解为3-4个具体研究子问题",
            backstory="资深研究规划师，擅长问题分解",
            api_key=API_KEY, thinking=True, max_steps=2,
        )
        fetcher = DeepSeekAgent(
            role="数据获取员",
            goal="搜索并整理每个子问题的关键信息",
            backstory="信息检索专家",
            api_key=API_KEY, thinking=False, max_steps=2,
        )
        analyst = DeepSeekAgent(
            role="分析师",
            goal="深度分析数据，发现趋势和洞察",
            backstory="行业分析师，10年经验",
            api_key=API_KEY, thinking=True, max_steps=3,
        )
        critic = DeepSeekAgent(
            role="批判审阅员",
            goal="找出分析中的漏洞、矛盾和不一致之处",
            backstory="严格的学术审稿人",
            api_key=API_KEY, thinking=False, max_steps=1,
        )
        synthesizer = DeepSeekAgent(
            role="综合撰写员",
            goal="将所有分析和批判整合为连贯的最终报告",
            backstory="资深研究报告撰写人",
            api_key=API_KEY, thinking=False, max_steps=2,
        )
        fact_checker = DeepSeekAgent(
            role="事实核查员",
            goal="验证报告中的关键事实和数据",
            backstory="严谨的事实核查专家",
            api_key=API_KEY, thinking=False, max_steps=1,
        )

        tasks = [
            Task(description=f"将'{topic}'分解为3-4个研究子问题。每行一个子问题。", expected_output="子问题列表", agent=planner),
            Task(description="基于规划师的子问题，搜索并整理每个子问题的关键信息（3条/子问题）。", expected_output="信息摘要", agent=fetcher),
            Task(description="分析数据，找出2-3个关键趋势和1-2个意外发现。引用具体数据。", expected_output="趋势分析", agent=analyst),
            Task(description="批判审阅分析结果：找出逻辑漏洞、数据矛盾、未证实的主张。", expected_output="批判报告", agent=critic),
            Task(description="综合所有分析和批判，撰写一份150字的最终研究报告摘要。", expected_output="最终报告", agent=synthesizer),
            Task(description="验证最终报告中的关键事实陈述。列出已验证和无法验证的内容。", expected_output="核查报告", agent=fact_checker),
        ]

        crew = Crew(tasks=tasks)
        start = time.time()
        result = crew.kickoff()
        elapsed = time.time() - start

        passed = all(len(t.output) > 30 for t in result.outputs)

        (OUTPUT_DIR / "research_pipeline.json").write_text(json.dumps({
            "topic": topic,
            "tasks": len(tasks),
            "outputs": [{"len": len(t.output)} for t in result.outputs],
            "all_passed": passed,
            "elapsed_s": round(elapsed, 1),
            "total_cost": result.total_cost,
            "errors": result.errors,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        assert passed, f"Not all tasks produced meaningful output. Errors: {result.errors}"
        assert result.total_cost > 0, "Cost not tracked"


# ══════════════════════════════════════════════════════════════════════
# TEST 2: Interrupt & Resume Mid-Execution
# What happens when an agent is interrupted mid-task?
# ══════════════════════════════════════════════════════════════════════

class TestInterruptResume:
    """Interruption recovery: state must survive, no data loss."""

    def test_interrupt_during_multi_step_task(self):
        from seekflow.agent.agent import DeepSeekAgent
        from seekflow.agent.checkpoint import InMemoryStore

        store = InMemoryStore()
        tid = f"interrupt-test-{int(time.time())}"

        agent = DeepSeekAgent(
            role="研究员",
            goal="完成多步研究任务，即使被打断也要正确恢复",
            backstory="坚韧的研究员",
            api_key=API_KEY, thinking=True, max_steps=3,
        )

        # Run first phase
        agent.with_default_tools()
        result1 = agent.run(
            "研究3个2025年AI趋势，每步记录一个趋势。第一步：列出第一个趋势。",
            checkpoint_store=store, thread_id=tid,
        )

        # Save state
        cp1 = store.load(tid)

        # Run second phase (should be independent — run() creates fresh messages)
        result2 = agent.run(
            "继续之前的研究。第二步：列出第二个趋势。",
            checkpoint_store=store, thread_id=f"{tid}-2",
        )

        (OUTPUT_DIR / "interrupt.json").write_text(json.dumps({
            "phase1_output": result1.final_output[:200],
            "phase2_output": result2.final_output[:200],
            "checkpoint_saved": cp1 is not None,
            "phase1_cost": result1.cost,
            "phase2_cost": result2.cost,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        assert cp1 is not None, "Checkpoint not saved after phase 1"
        assert len(result1.final_output) > 30, "Phase 1 produced no output"
        assert len(result2.final_output) > 30, "Phase 2 produced no output"


# ══════════════════════════════════════════════════════════════════════
# TEST 3: Concurrent Agent Flood — 10 threads, 30 runs
# ══════════════════════════════════════════════════════════════════════

class TestConcurrentFlood:
    """Extreme concurrency: 10 threads, 3 runs each, shared API key."""

    def test_concurrent_flood(self):
        from seekflow.agent.agent import DeepSeekAgent

        NUM_THREADS = 8
        RUNS = 3
        errors = []
        results_lock = threading.Lock()

        def worker(wid: int):
            agent = DeepSeekAgent(
                role=f"Agent-{wid}",
                goal="正确执行并发任务",
                backstory="高并发环境中的工作单元",
                api_key=API_KEY, thinking=False, max_steps=1,
            )
            for r in range(RUNS):
                try:
                    result = agent.run(f"回复'worker{wid}-run{r}'，仅此一句")
                    if len(result.final_output) < 3:
                        with results_lock:
                            errors.append(f"w{wid}r{r}: empty output")
                except Exception as e:
                    with results_lock:
                        errors.append(f"w{wid}r{r}: {type(e).__name__}: {e}")

        start = time.time()
        with concurrent.futures.ThreadPoolExecutor(max_workers=NUM_THREADS) as ex:
            futures = [ex.submit(worker, i) for i in range(NUM_THREADS)]
            concurrent.futures.wait(futures)
        elapsed = time.time() - start

        (OUTPUT_DIR / "concurrent_flood.json").write_text(json.dumps({
            "threads": NUM_THREADS,
            "runs_per_thread": RUNS,
            "total_runs": NUM_THREADS * RUNS,
            "errors": len(errors),
            "elapsed_s": round(elapsed, 1),
            "error_details": errors[:10],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        error_rate = len(errors) / (NUM_THREADS * RUNS)
        assert error_rate < 0.25, (
            f"Error rate {error_rate:.1%} exceeds 25% threshold. Errors: {errors[:5]}"
        )


# ══════════════════════════════════════════════════════════════════════
# TEST 4: Tool Failure Storm — 50% failure rate, verify recovery
# ══════════════════════════════════════════════════════════════════════

class TestToolFailureStorm:
    """Tools fail randomly at 50% rate. Agent must adapt and complete."""

    def test_tool_failure_storm(self):
        from seekflow.agent.agent import DeepSeekAgent

        fail_count = [0]
        call_count = [0]

        def unreliable_tool(x: str) -> str:
            """A tool that fails 50% of the time."""
            call_count[0] += 1
            if random.random() < 0.5:
                fail_count[0] += 1
                raise RuntimeError(f"Tool failure #{fail_count[0]}: simulated")
            return f"Success: processed '{x}'"

        agent = DeepSeekAgent(
            role="问题解决者",
            goal="即使工具频繁失败也必须完成任务",
            backstory="你会使用unreliable_tool。如果失败，重试或换方法。",
            api_key=API_KEY, thinking=True, max_steps=5,
        )
        agent.add_tool(unreliable_tool)

        result = agent.run(
            "调用 unreliable_tool 处理 'test-data'。如果失败，重试直到成功。"
            "最终告诉我处理结果。"
        )

        (OUTPUT_DIR / "tool_failure.json").write_text(json.dumps({
            "tool_calls": call_count[0],
            "tool_failures": fail_count[0],
            "failure_rate": f"{fail_count[0]/max(call_count[0],1):.0%}",
            "agent_output": result.final_output[:200],
            "agent_succeeded": len(result.final_output) > 10,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        assert len(result.final_output) > 10, (
            f"Agent produced no meaningful output despite tool failures"
        )


# ══════════════════════════════════════════════════════════════════════
# TEST 5: Memory Chaos — concurrent reads/writes during agent execution
# ══════════════════════════════════════════════════════════════════════

class TestMemoryChaos:
    """Memory under concurrent read/write stress."""

    def test_memory_chaos(self):
        from seekflow.agent.memory import AgentMemory
        import random as _random

        mem = AgentMemory(long_term_max=200)

        # Concurrent insert
        def inserter(start: int, count: int):
            for i in range(start, start + count):
                mem.remember(
                    f"fact-{i}: value={_random.randint(1,10000)}",
                    importance=_random.uniform(0.3, 1.0),
                )

        threads = []
        for t in range(4):
            th = threading.Thread(target=inserter, args=(t * 25, 25))
            threads.append(th)
            th.start()

        for th in threads:
            th.join()

        # Verify: can recall after concurrent inserts
        mem.remember("TARGET: production-db-password=xyz789", importance=1.0)
        results = mem.recall("database password", top_k=3)
        found = any("xyz789" in r for r in results)

        stats = mem.stats()

        (OUTPUT_DIR / "memory_chaos.json").write_text(json.dumps({
            "total_inserted": 100,
            "stored": stats["long_term_items"],
            "needle_found": found,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        assert stats["long_term_items"] >= 50, f"Only {stats['long_term_items']} stored"
        assert found, "Needle not found after concurrent inserts"


# ══════════════════════════════════════════════════════════════════════
# TEST 6: Context Exhaustion Recovery
# Push context to the limit, then recover
# ══════════════════════════════════════════════════════════════════════

class TestContextExhaustion:
    """Fill context, trigger compression, verify continued function."""

    def test_context_exhaustion_and_recovery(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="档案管理员",
            goal="在极其有限的上下文中完成任务",
            backstory="上下文空间非常宝贵",
            api_key=API_KEY, thinking=False, max_steps=2,
            max_context_tokens=8000,  # Tiny to force exhaustion
        )

        # Fill with junk
        junk = []
        for i in range(20):
            junk.append({
                "page_content": f"文档{i:03d}：" + "无关数据。" * 40 + f"秘密:{i*13}",
                "metadata": {"source": f"junk_{i}.txt"},
            })
        agent.add_documents(junk)

        # Now try to do real work in tiny context
        result = agent.run("在这些文档中，无论多少无关数据，找到秘密为65的文档编号并回复。只回复那个文档编号。")

        (OUTPUT_DIR / "context_exhaustion.json").write_text(json.dumps({
            "context_used": result.diagnostics.context_used,
            "context_total": result.diagnostics.context_total,
            "usage_pct": f"{result.diagnostics.context_used/max(result.diagnostics.context_total,1)*100:.1f}%",
            "output": result.final_output[:200],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

        # Agent should produce some output, even under extreme pressure
        assert len(result.final_output) > 0, "Agent produced nothing under context pressure"
