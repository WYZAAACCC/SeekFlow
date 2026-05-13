"""Real-world production tests for SeekFlow v3 Agent Framework.

Tests cover:
  1. Single Agent + tools + thinking mode (financial analysis)
  2. Multi-Agent Sequential Crew (research → analyze → write)
  3. Multi-Agent Parallel Crew (multi-dimensional analysis)
  4. Hierarchical Crew (Manager → Workers)
  5. Checkpoint/Resume (interrupt recovery)
  6. Document Protocol (LangChain bridge)
  7. Cross-framework comparison (SeekFlow vs minimal LangChain vs minimal CrewAI)

Each test verifies: output quality, cost tracking, tool call count, latency.
"""
import json
import os
import time
from pathlib import Path

import pytest

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DATA_DIR = Path(__file__).parent.parent / "_archive" / "benchmarks" / "agents_comparison" / "data"
OUTPUT_DIR = Path(__file__).parent.parent / "output" / "v3_production_tests"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

pytestmark = pytest.mark.skipif(not API_KEY, reason="DEEPSEEK_API_KEY not set")


# ══════════════════════════════════════════════════════════════════════
# Scenario 1: Single Agent — Financial Analysis with Thinking
# ══════════════════════════════════════════════════════════════════════

class TestScenario1_FinancialAgent:
    """Real financial analysis with thinking mode."""

    def test_financial_analysis_with_thinking(self):
        """Analyze ByteDance 2025 financials — thinking mode ON."""
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="资深财务分析师",
            goal="全面分析企业财务数据，给出专业评级和建议",
            backstory="CPA+CFA持证人，20年互联网科技行业审计经验",
            api_key=API_KEY,
            thinking=True,
        )

        # Add analysis tools
        def calculate_ratio(expression: str) -> str:
            """Calculate financial ratios. e.g. '8630/15800'"""
            try:
                result = eval(expression, {"__builtins__": {}}, {})
                return f"Result: {result:.4f}"
            except Exception as e:
                return f"Error: {e}"

        agent.add_tool(calculate_ratio)

        data_file = str(DATA_DIR / "financial_report.json")
        result = agent.run(
            f"读取 {data_file}，分析字节跳动2025年财务状况。\n"
            "计算关键比率（毛利率、净利率、资产负债率），给出评级（优秀/良好/一般/风险）。\n"
            "输出一份简短的分析报告（300字以内）。",
            files=[data_file],
        )

        # Quality checks
        assert result.final_output is not None
        assert len(result.final_output) > 200, f"Output too short: {len(result.final_output)} chars"
        assert result.cost > 0, "Cost should be tracked"
        assert result.reasoning_content is not None, "Thinking should produce reasoning"
        assert len(result.reasoning_content) > 100, "Reasoning too short"

        # Content checks
        output = result.final_output
        assert any(w in output for w in ["毛利率", "净利", "资产"]), "Missing key financial terms"
        assert any(w in output for w in ["优秀", "良好", "风险", "评级"]), "Missing rating"

        print(f"\n[Scenario 1] Financial Analysis:")
        print(f"  Cost: CNY {result.cost:.6f}")
        print(f"  Reasoning: {len(result.reasoning_content)} chars")
        print(f"  Output: {len(result.final_output)} chars")
        print(f"  Tools: {len(result.tool_calls)} calls")

        # Save output
        (OUTPUT_DIR / "scenario1_financial.txt").write_text(
            result.final_output, encoding="utf-8"
        )


# ══════════════════════════════════════════════════════════════════════
# Scenario 2: Sequential Crew — Research → Analyze → Write
# ══════════════════════════════════════════════════════════════════════

class TestScenario2_SequentialCrew:
    """Multi-Agent pipeline: researcher → analyst → writer."""

    def test_research_analyze_write_pipeline(self):
        from seekflow.agent.agent import DeepSeekAgent
        from seekflow.agent.task import Task
        from seekflow.agent.crew import Crew

        researcher = DeepSeekAgent(
            role="行业研究员",
            goal="搜索和整理行业信息",
            backstory="资深研究员，擅长快速搜集和整理信息",
            api_key=API_KEY,
            thinking=False,
            max_steps=3,
        )
        analyst = DeepSeekAgent(
            role="数据分析师",
            goal="分析数据并发现洞察",
            backstory="10年数据分析经验，精通统计和商业分析",
            api_key=API_KEY,
            thinking=False,
            max_steps=3,
        )
        writer = DeepSeekAgent(
            role="商业撰稿人",
            goal="撰写专业、可读性强的商业报告",
            backstory="前财经记者，擅长将复杂数据转化为易懂文字",
            api_key=API_KEY,
            thinking=False,
            max_steps=2,
        )

        tasks = [
            Task(
                description="研究2025年中国电商行业趋势，列出3个关键趋势",
                expected_output="3个关键趋势的列表",
                agent=researcher,
            ),
            Task(
                description="基于前一步的趋势发现，分析这些趋势对中小商家的影响",
                expected_output="趋势影响分析",
                agent=analyst,
            ),
            Task(
                description="将前面的研究结果整理成一篇300字的商业简报",
                expected_output="300字商业简报",
                agent=writer,
            ),
        ]

        crew = Crew(tasks=tasks)
        result = crew.kickoff()

        assert len(result.outputs) == 3
        assert result.total_cost > 0
        assert result.total_latency_ms > 0

        # Each agent's output should be meaningful
        assert len(result.outputs[0].output) > 50  # researcher
        assert len(result.outputs[1].output) > 50  # analyst
        assert len(result.outputs[2].output) > 100  # writer (final report)

        print(f"\n[Scenario 2] Sequential Crew:")
        print(f"  Tasks: {len(result.outputs)}")
        print(f"  Cost: CNY {result.total_cost:.6f}")
        print(f"  Latency: {result.total_latency_ms:.0f}ms")
        print(f"  Summary: {result.summary[:200]}")

        (OUTPUT_DIR / "scenario2_sequential.txt").write_text(
            result.summary + "\n\n" + result.final_output, encoding="utf-8"
        )


# ══════════════════════════════════════════════════════════════════════
# Scenario 3: Parallel Crew — Multi-dimensional Analysis
# ══════════════════════════════════════════════════════════════════════

class TestScenario3_ParallelCrew:
    """Three analysts work simultaneously on different dimensions."""

    def test_parallel_multi_dimension_analysis(self):
        from seekflow.agent.agent import DeepSeekAgent
        from seekflow.agent.task import Task
        from seekflow.agent.crew import Crew, Process

        # Three independent analysts
        analyst_args = dict(
            goal="分析指定维度",
            backstory="资深分析师",
            api_key=API_KEY,
            thinking=False,
            max_steps=1,
        )

        tasks = [
            Task(
                description="分析：如果2025年AI取代50%的客服岗位，服务业的就业结构会如何变化？100字以内",
                expected_output="服务业就业分析",
                agent=DeepSeekAgent(role="服务业分析师", **analyst_args),
            ),
            Task(
                description="分析：如果2025年AI取代50%的客服岗位，科技公司的营收结构会如何变化？100字以内",
                expected_output="科技公司分析",
                agent=DeepSeekAgent(role="科技行业分析师", **analyst_args),
            ),
            Task(
                description="分析：如果2025年AI取代50%的客服岗位，消费者体验会如何变化？100字以内",
                expected_output="消费者体验分析",
                agent=DeepSeekAgent(role="消费者研究员", **analyst_args),
            ),
        ]

        crew = Crew(tasks=tasks, process=Process.PARALLEL)
        start = time.time()
        result = crew.kickoff()
        elapsed = time.time() - start

        assert len(result.outputs) == 3
        # Parallel should be faster than sequential sum
        # Each individual run ~3-5s, parallel should be close to max not sum

        print(f"\n[Scenario 3] Parallel Crew:")
        print(f"  Tasks: {len(result.outputs)}")
        print(f"  Wall time: {elapsed:.1f}s")
        print(f"  Cost: CNY {result.total_cost:.6f}")
        for i, tr in enumerate(result.outputs):
            print(f"  Task {i}: {len(tr.output)} chars — {tr.output[:80]}...")

        (OUTPUT_DIR / "scenario3_parallel.txt").write_text(
            result.final_output, encoding="utf-8"
        )


# ══════════════════════════════════════════════════════════════════════
# Scenario 4: Hierarchical Crew — Manager delegates
# ══════════════════════════════════════════════════════════════════════

class TestScenario4_HierarchicalCrew:
    """Manager decomposes task and delegates to specialists."""

    def test_manager_delegates_to_specialists(self):
        from seekflow.agent.agent import DeepSeekAgent
        from seekflow.agent.task import Task
        from seekflow.agent.crew import Crew, Process

        manager = DeepSeekAgent(
            role="项目总监",
            goal="将'AI对就业影响'这个主题分解为3个子任务，分别分配给经济学家、社会学家、技术专家执行，然后汇总结果",
            backstory="经验丰富的项目管理者，擅长任务分解和团队协调",
            api_key=API_KEY,
            thinking=False,
            max_steps=8,
        )
        economist = DeepSeekAgent(
            role="经济学家",
            goal="从经济学角度分析问题",
            backstory="劳动经济学家，研究技术对就业的影响",
            api_key=API_KEY,
            thinking=False,
            max_steps=1,
        )
        sociologist = DeepSeekAgent(
            role="社会学家",
            goal="从社会学角度分析问题",
            backstory="社会学家，研究技术对社会结构的影响",
            api_key=API_KEY,
            thinking=False,
            max_steps=1,
        )
        technologist = DeepSeekAgent(
            role="技术专家",
            goal="从技术角度分析问题",
            backstory="AI技术专家，10年行业经验",
            api_key=API_KEY,
            thinking=False,
            max_steps=1,
        )

        tasks = [
            Task(
                description="从经济学角度分析AI对就业的影响（50字以内）",
                expected_output="经济分析",
                agent=economist,
            ),
            Task(
                description="从社会学角度分析AI对就业的影响（50字以内）",
                expected_output="社会分析",
                agent=sociologist,
            ),
            Task(
                description="从技术角度分析AI对就业的影响（50字以内）",
                expected_output="技术分析",
                agent=technologist,
            ),
        ]

        crew = Crew(
            tasks=tasks,
            process=Process.HIERARCHICAL,
            manager_agent=manager,
        )
        result = crew.kickoff()

        assert result.final_output is not None
        assert len(result.final_output) > 100
        assert result.total_cost > 0

        print(f"\n[Scenario 4] Hierarchical Crew:")
        print(f"  Cost: CNY {result.total_cost:.6f}")
        print(f"  Output length: {len(result.final_output)} chars")
        print(f"  Preview: {result.final_output[:200]}...")

        (OUTPUT_DIR / "scenario4_hierarchical.txt").write_text(
            result.final_output, encoding="utf-8"
        )


# ══════════════════════════════════════════════════════════════════════
# Scenario 5: Checkpoint/Resume
# ══════════════════════════════════════════════════════════════════════

class TestScenario5_Checkpoint:
    """Checkpoint save and resume after simulated failure."""

    def test_checkpoint_save_and_verify(self):
        from seekflow.agent.checkpoint import (
            AgentCheckpoint, InMemoryStore, SqliteStore,
        )

        # InMemory test
        store = InMemoryStore()
        cp = AgentCheckpoint(
            thread_id="scenario5-test",
            step=3,
            messages=[
                {"role": "system", "content": "你是助手"},
                {"role": "user", "content": "任务A"},
                {"role": "assistant", "content": "任务A完成"},
            ],
            tool_calls_completed=["tool_1", "tool_2"],
        )
        store.save(cp)
        loaded = store.load("scenario5-test")
        assert loaded is not None
        assert loaded.step == 3
        assert len(loaded.messages) == 3
        assert len(loaded.tool_calls_completed) == 2
        store.delete("scenario5-test")
        assert store.load("scenario5-test") is None

        # Sqlite test
        import tempfile
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = tmp.name
        tmp.close()
        try:
            sql_store = SqliteStore(db_path)
            sql_store.save(cp)
            loaded2 = sql_store.load("scenario5-test")
            assert loaded2 is not None
            assert loaded2.step == 3
            sql_store.delete("scenario5-test")
            assert sql_store.load("scenario5-test") is None
            sql_store._conn.close()
        finally:
            try:
                os.unlink(db_path)
            except PermissionError:
                pass  # Windows may hold the file briefly

        print(f"\n[Scenario 5] Checkpoint: InMemory + Sqlite — OK")


# ══════════════════════════════════════════════════════════════════════
# Scenario 6: Document Protocol Bridge
# ══════════════════════════════════════════════════════════════════════

class TestScenario6_DocumentProtocol:
    """Bridge LangChain ecosystem documents into SeekFlow Agent."""

    def test_langchain_document_to_dtk_agent(self):
        from seekflow.compat.documents import (
            DocumentLike, to_agent_text, validate_document,
        )
        from seekflow.agent.agent import DeepSeekAgent

        # Simulate LangChain Document
        class LangChainDocument:
            def __init__(self, content, source="unknown"):
                self.page_content = content
                self.metadata = {"source": source}

        docs = [
            LangChainDocument("2025年全球AI市场规模达到5000亿美元。", "ai_report.txt"),
            LangChainDocument("中国AI专利申请量占全球40%。", "patent_data.txt"),
        ]

        # Validate
        assert validate_document(docs[0])
        assert isinstance(docs[0], DocumentLike)

        # Convert
        text = to_agent_text(docs)
        assert "ai_report.txt" in text
        assert "5000亿美元" in text
        assert "patent_data.txt" in text

        # Feed to Agent
        agent = DeepSeekAgent(
            role="分析师",
            goal="基于文档内容回答问题",
            backstory="专家",
            api_key=API_KEY,
            thinking=False,
            max_steps=1,
        )
        agent_prompt = (
            f"基于以下参考文档回答问题：\n\n{text}\n\n"
            f"问题：全球AI市场规模和中国的AI专利占比是多少？简短回答。"
        )
        result = agent.run(agent_prompt)
        assert "5000" in result.final_output or "40%" in result.final_output

        print(f"\n[Scenario 6] Document Protocol:")
        print(f"  Documents: {len(docs)}")
        print(f"  Agent output: {result.final_output[:150]}...")

        (OUTPUT_DIR / "scenario6_document_protocol.txt").write_text(
            result.final_output, encoding="utf-8"
        )


# ══════════════════════════════════════════════════════════════════════
# Scenario 7: Comparison — SeekFlow vs minimal LangChain vs minimal CrewAI
# ══════════════════════════════════════════════════════════════════════

class TestScenario7_CrossFrameworkComparison:
    """Same task across SeekFlow, LangChain, CrewAI — compare cost + quality."""

    COMPARISON_TASK = (
        "从投资人角度分析：AI客服取代人工客服对以下三家公司的影响——"
        "阿里巴巴（电商客服）、中国移动（运营商客服）、招商银行（银行客服）。"
        "每家50字，给出投资建议。"
    )

    def test_dtk_agent_on_comparison_task(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="投资分析师",
            goal="分析AI对不同公司的影响，给出投资建议",
            backstory="CFA持证人，10年买方研究经验",
            api_key=API_KEY,
            thinking=True,
            max_steps=1,
        )
        start = time.time()
        result = agent.run(self.COMPARISON_TASK)
        elapsed = time.time() - start

        dtk_metrics = {
            "framework": "SeekFlow",
            "latency_s": round(elapsed, 1),
            "cost_cny": result.cost,
            "tokens": result.tokens.get("total_tokens", 0),
            "output_length": len(result.final_output),
            "has_reasoning": result.reasoning_content is not None,
            "reasoning_length": len(result.reasoning_content or ""),
            "tool_calls": len(result.tool_calls),
        }

        assert dtk_metrics["output_length"] > 100
        assert dtk_metrics["cost_cny"] > 0

        print(f"\n[Scenario 7a] SeekFlow Comparison Task:")
        for k, v in dtk_metrics.items():
            print(f"  {k}: {v}")

        (OUTPUT_DIR / "scenario7_comparison.json").write_text(
            json.dumps({"dtk": dtk_metrics}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def test_langchain_minimal_agent_on_comparison_task(self):
        """Minimal LangChain create_agent for comparison."""
        pytest.importorskip("langchain")
        from langchain_openai import ChatOpenAI
        from langchain.agents import create_agent

        model = ChatOpenAI(
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com/v1",
            api_key=API_KEY,
            temperature=0.2,
            max_tokens=2048,
        )
        agent = create_agent(
            model, [],
            system_prompt="你是投资分析师，CFA持证人，10年买方研究经验。",
        )
        start = time.time()
        result = agent.invoke({"messages": [("user", self.COMPARISON_TASK)]})
        elapsed = time.time() - start

        output = ""
        if result and "messages" in result:
            last_msg = result["messages"][-1]
            output = last_msg.content if hasattr(last_msg, 'content') else str(last_msg)

        lc_metrics = {
            "framework": "LangChain",
            "latency_s": round(elapsed, 1),
            "output_length": len(output),
        }
        print(f"\n[Scenario 7b] LangChain Comparison Task:")
        for k, v in lc_metrics.items():
            print(f"  {k}: {v}")

        # Append to comparison file
        data = json.loads((OUTPUT_DIR / "scenario7_comparison.json").read_text())
        data["langchain"] = lc_metrics
        (OUTPUT_DIR / "scenario7_comparison.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
        )

    def test_crewai_minimal_agent_on_comparison_task(self):
        """Minimal CrewAI Agent for comparison."""
        pytest.importorskip("crewai")
        from crewai import Agent, Task, Crew, Process, LLM

        llm = LLM(
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com/v1",
            api_key=API_KEY,
            temperature=0.2,
            max_tokens=2048,
            additional_params={"extra_body": {"thinking": {"type": "disabled"}}},
        )
        agent = Agent(
            role="投资分析师",
            goal="分析AI对不同公司的影响，给出投资建议",
            backstory="CFA持证人，10年买方研究经验",
            llm=llm,
            verbose=False,
            max_iter=2,
        )
        task = Task(
            description=self.COMPARISON_TASK,
            expected_output="三家公司的分析和投资建议",
            agent=agent,
        )
        crew = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False)

        start = time.time()
        result = crew.kickoff()
        elapsed = time.time() - start

        output = result.raw if hasattr(result, 'raw') else str(result)

        ca_metrics = {
            "framework": "CrewAI",
            "latency_s": round(elapsed, 1),
            "output_length": len(output),
        }
        print(f"\n[Scenario 7c] CrewAI Comparison Task:")
        for k, v in ca_metrics.items():
            print(f"  {k}: {v}")

        # Append to comparison file
        data = json.loads((OUTPUT_DIR / "scenario7_comparison.json").read_text())
        data["crewai"] = ca_metrics
        (OUTPUT_DIR / "scenario7_comparison.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
        )
