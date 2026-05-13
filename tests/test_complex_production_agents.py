"""Truly complex production agents — real-world workflows at production scale.

Agent 1: Full SDLC Code Review (8 agents, file reading, FIM, parallel tools)
Agent 2: Multi-Source Data ETL (6 agents, conditional routing, structured output)
Agent 3: Regulatory Compliance Audit (7 agents, hierarchical, checkpoint, search)
"""
import json, os, time
from pathlib import Path
import pytest

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DATA_DIR = Path(__file__).parent.parent / "_archive" / "benchmarks" / "agents_comparison" / "data"
OUTPUT_DIR = Path(__file__).parent.parent / "output" / "complex_agents"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
pytestmark = pytest.mark.skipif(not API_KEY, reason="DEEPSEEK_API_KEY not set")


# ══════════════════════════════════════════════════════════════════════
# AGENT 1: Full SDLC Code Review Pipeline (8 agents)
# Reads real code → security scan → performance → style → tests → docs → review → FIM
# ══════════════════════════════════════════════════════════════════════

class TestSDLCCodeReview:
    """8-agent SDLC pipeline: read → scan → analyze → review → fix."""

    def test_full_sdlc_pipeline(self):
        from seekflow.agent.agent import DeepSeekAgent
        from seekflow.agent.task import Task
        from seekflow.agent.crew import Crew

        target_file = str(Path(__file__).parent / "test_v3_agent.py")

        reader = DeepSeekAgent(role="代码阅读员", goal="读取代码并识别结构", backstory="资深代码审查员", api_key=API_KEY, thinking=False, max_steps=1, mode="fast")
        security = DeepSeekAgent(role="安全扫描员", goal="检测安全漏洞", backstory="安全专家,OWASP认证", api_key=API_KEY, thinking=False, max_steps=2, mode="fast")
        performance = DeepSeekAgent(role="性能分析员", goal="发现性能瓶颈", backstory="性能优化专家", api_key=API_KEY, thinking=False, max_steps=1, mode="fast")
        style = DeepSeekAgent(role="代码风格检查员", goal="检查代码风格和可读性", backstory="PEP8专家", api_key=API_KEY, thinking=False, max_steps=1, mode="fast")
        test_writer = DeepSeekAgent(role="测试编写员", goal="为问题代码编写单元测试", backstory="TDD专家,10年经验", api_key=API_KEY, thinking=False, max_steps=2, mode="fast")
        docs = DeepSeekAgent(role="文档编写员", goal="为缺失文档的函数生成docstring", backstory="技术文档专家", api_key=API_KEY, thinking=False, max_steps=1, mode="fast")
        aggregator = DeepSeekAgent(role="审查汇总员", goal="汇总所有分析结果生成PR Review", backstory="Tech Lead,15年经验", api_key=API_KEY, thinking=True, max_steps=3, mode="stable")
        fixer = DeepSeekAgent(role="代码修复员", goal="使用FIM生成修复建议", backstory="资深软件工程师", api_key=API_KEY, thinking=False, max_steps=2, mode="fast")

        reader.with_default_tools()  # for read_file
        security.with_default_tools()

        tasks = [
            Task(description=f"读取{target_file}前100行,列出定义了哪些类和方法(60字)", expected_output="代码结构", agent=reader),
            Task(description="审查上述代码结构,找出安全风险(hardcoded keys/injection等)(50字)", expected_output="安全风险", agent=security),
            Task(description="审查性能问题(N+1查询/循环内分配/IO阻塞等)(50字)", expected_output="性能问题", agent=performance),
            Task(description="审查代码风格(命名/缩进/函数长度)(50字)", expected_output="风格问题", agent=style),
            Task(description="为发现的问题编写2个单元测试用例(80字)", expected_output="测试用例", agent=test_writer),
            Task(description="为关键函数生成docstring模板(60字)", expected_output="文档", agent=docs),
            Task(description="汇总所有审查发现,生成150字PR Review:列出TOP3问题和修复优先级", expected_output="PR Review", agent=aggregator),
            Task(description="使用FIM为最严重的问题生成修复代码(100字)", expected_output="修复代码", agent=fixer),
        ]

        crew = Crew(tasks=tasks)
        result = crew.kickoff()

        assert len(result.outputs) == 8, f"Expected 8 outputs, got {len(result.outputs)}"
        assert result.total_cost > 0, "Cost not tracked"
        assert len(result.final_output) > 50, "Final output too short"
        assert len(result.errors) == 0, f"Errors: {result.errors}"

        (OUTPUT_DIR / "sdlc_pipeline.json").write_text(json.dumps({
            "tasks": len(result.outputs), "cost": result.total_cost,
            "latency": result.total_latency_ms / 1000, "output_len": len(result.final_output),
        }, ensure_ascii=False, indent=2), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════
# AGENT 2: Multi-Source Data ETL Pipeline (6 agents, conditional, structured)
# Discovery → Schema → Plan → Quality → Transform → Report
# ══════════════════════════════════════════════════════════════════════

class TestDataETLPipeline:
    """6-agent ETL: discover → infer → plan → validate → transform → report."""

    def test_etl_pipeline_with_conditional_routing(self):
        from seekflow.agent.agent import DeepSeekAgent
        from seekflow.agent.task import Task
        from seekflow.agent.crew import Crew

        csv_path = str(DATA_DIR / "sales_data.csv")

        discoverer = DeepSeekAgent(role="数据发现员", goal="读取数据源并描述结构", backstory="数据工程师", api_key=API_KEY, thinking=False, max_steps=1, mode="fast")
        schema = DeepSeekAgent(role="Schema推断员", goal="自动推断数据schema", backstory="数据架构师", api_key=API_KEY, thinking=False, max_steps=1, mode="fast")
        planner = DeepSeekAgent(role="ETL规划员", goal="设计ETL流水线步骤", backstory="ETL专家", api_key=API_KEY, thinking=False, max_steps=1, mode="fast")
        quality = DeepSeekAgent(role="数据质量员", goal="检测数据质量问题", backstory="数据质量专家", api_key=API_KEY, thinking=False, max_steps=1, mode="fast")
        transformer = DeepSeekAgent(role="数据转换员", goal="定义数据清洗和转换规则", backstory="数据处理专家", api_key=API_KEY, thinking=False, max_steps=1, mode="fast")
        reporter = DeepSeekAgent(role="报告生成员", goal="生成完整的ETL执行报告", backstory="数据产品经理", api_key=API_KEY, thinking=True, max_steps=2, mode="stable")

        discoverer.with_default_tools()  # read_file

        tasks = [
            Task(description=f"读取{csv_path},描述数据:多少列,什么类型,多少行(40字)", expected_output="数据描述", agent=discoverer),
            Task(description="基于数据结构,自动推断schema定义(40字)", expected_output="schema", agent=schema),
            Task(description="设计ETL流水线:抽取→清洗→转换→加载,列出4步(50字)", expected_output="ETL计划", agent=planner),
            # Conditional: only run quality check if data is "large" (>10 cols)
            Task(description="检测数据质量问题:空值/重复/异常值(40字)", expected_output="质量报告",
                 agent=quality, skip_condition=lambda ctx: "列" not in ctx.get("last_output", "")),
            Task(description="定义数据清洗规则(40字)", expected_output="清洗规则", agent=transformer),
            Task(description="生成100字ETL执行报告:总结数据概况+质量+转换+建议", expected_output="ETL报告", agent=reporter),
        ]

        crew = Crew(tasks=tasks)
        result = crew.kickoff()

        assert len(result.outputs) >= 5, "Expected >=5 outputs with conditional routing"
        assert result.total_cost > 0
        assert len(result.final_output) > 30

        (OUTPUT_DIR / "etl_pipeline.json").write_text(json.dumps({
            "tasks": len(result.outputs), "cost": result.total_cost,
            "output_len": len(result.final_output), "errors": len(result.errors),
        }, ensure_ascii=False, indent=2), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════
# AGENT 3: Regulatory Compliance Audit (7 agents, hierarchical, checkpoint)
# Research → Gap → Risk → Policy → Evidence → Review → Report
# ══════════════════════════════════════════════════════════════════════

class TestComplianceAudit:
    """7-agent hierarchical compliance audit with checkpoint."""

    def test_hierarchical_compliance_audit(self):
        from seekflow.agent.agent import DeepSeekAgent
        from seekflow.agent.task import Task
        from seekflow.agent.crew import Crew, Process

        manager = DeepSeekAgent(role="审计总监", goal="将GDPR合规审计分解为子任务并分配给团队", backstory="CISA认证,15年IT审计经验", api_key=API_KEY, thinking=True, max_steps=8, mode="stable")
        researcher = DeepSeekAgent(role="法规研究员", goal="研究适用的GDPR条款", backstory="隐私法专家", api_key=API_KEY, thinking=False, max_steps=2, mode="fast")
        gap_analyzer = DeepSeekAgent(role="差距分析员", goal="识别当前合规差距", backstory="合规审计师", api_key=API_KEY, thinking=False, max_steps=1, mode="fast")
        risk_assessor = DeepSeekAgent(role="风险评估员", goal="评估合规风险等级和影响", backstory="风险管理专家", api_key=API_KEY, thinking=False, max_steps=1, mode="fast")
        policy_writer = DeepSeekAgent(role="政策撰写员", goal="起草合规政策和操作流程", backstory="政策分析师", api_key=API_KEY, thinking=False, max_steps=2, mode="fast")
        evidence = DeepSeekAgent(role="证据收集员", goal="收集合规证据清单", backstory="法务助理", api_key=API_KEY, thinking=False, max_steps=1, mode="fast")
        reviewer = DeepSeekAgent(role="审核员", goal="交叉验证所有发现", backstory="质量保证专家", api_key=API_KEY, thinking=False, max_steps=1, mode="fast")

        researcher.with_default_tools()  # web_search

        tasks = [
            Task(description="研究GDPR数据处理相关条款,列出3个关键要求(60字)", expected_output="法规要求", agent=researcher),
            Task(description="基于法规要求,识别当前数据处理的3个合规差距(60字)", expected_output="差距分析", agent=gap_analyzer),
            Task(description="评估每个合规差距的风险等级(高/中/低)和潜在影响(60字)", expected_output="风险评估", agent=risk_assessor),
            Task(description="起草2条合规政策:数据最小化+用户同意管理(80字)", expected_output="政策草案", agent=policy_writer),
            Task(description="列出实现合规需要的5项证据材料(60字)", expected_output="证据清单", agent=evidence),
            Task(description="交叉验证法规要求vs当前状态vs政策草案的一致性(60字)", expected_output="验证报告", agent=reviewer),
        ]

        crew = Crew(tasks=tasks, process=Process.HIERARCHICAL, manager_agent=manager)
        result = crew.kickoff()

        assert len(result.final_output) > 100, f"Report too short: {len(result.final_output)}"
        assert result.total_cost > 0
        assert len(result.errors) == 0

        (OUTPUT_DIR / "compliance_audit.json").write_text(json.dumps({
            "output_len": len(result.final_output), "cost": result.total_cost,
            "errors": result.errors,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_compliance_with_checkpoint_resume(self):
        from seekflow.agent.agent import DeepSeekAgent
        from seekflow.agent.task import Task
        from seekflow.agent.crew import Crew
        from seekflow.agent.checkpoint import InMemoryStore

        store = InMemoryStore()
        tid = f"compliance-{int(time.time())}"

        agent = DeepSeekAgent(role="合规审计员", goal="完成审计步骤", backstory="CISA", api_key=API_KEY, thinking=False, max_steps=2, mode="fast")

        tasks = [
            Task(description="列出GDPR的2个核心原则(30字)", expected_output="原则", agent=agent),
            Task(description="评估当前系统的合规差距(30字)", expected_output="差距", agent=agent),
        ]

        crew = Crew(tasks=tasks, checkpoint=True, checkpoint_store=store)
        result1 = crew.kickoff()

        # Verify checkpoint was saved
        checkpoints = store.list()
        assert len(checkpoints) > 0, "No checkpoint saved"

        # Resume from checkpoint (should complete almost instantly)
        result2 = crew.resume(result1.thread_id)
        assert result2.resumed_from is not None

        (OUTPUT_DIR / "compliance_checkpoint.json").write_text(json.dumps({
            "thread_id": result1.thread_id, "checkpoint_count": len(checkpoints),
            "resumed": result2.resumed_from is not None,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
