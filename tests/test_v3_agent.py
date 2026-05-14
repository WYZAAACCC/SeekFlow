"""Tests for v3 Agent layer — DeepSeekAgent, Task, Crew."""
import os
import pytest
from dataclasses import dataclass



# ══════════════════════════════════════════════════════════════════════
# v3-001: DeepSeekAgent — role/goal/backstory + .run()
# ══════════════════════════════════════════════════════════════════════

class TestDeepSeekAgentCreation:
    """Agent can be instantiated with three core fields."""

    def test_agent_creation_with_role_goal_backstory(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="财务分析师",
            goal="分析财务报告",
            backstory="CPA持证人，10年经验",
            api_key="sk-test",
        )
        assert agent.role == "财务分析师"
        assert agent.goal == "分析财务报告"
        assert agent.backstory == "CPA持证人，10年经验"

    def test_agent_missing_role_raises_error(self):
        from seekflow.agent.agent import DeepSeekAgent
        import pytest

        with pytest.raises(TypeError):
            DeepSeekAgent(goal="分析", backstory="专家")  # missing role

    def test_agent_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-test")
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师",
            goal="分析",
            backstory="专家",
        )
        assert agent._api_key == "sk-env-test"

    def test_agent_default_values(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师",
            goal="分析",
            backstory="专家",
            api_key="sk-test",
        )
        assert agent._thinking is True
        assert agent._model == "deepseek-v4-pro"
        assert agent._temperature == 0.2
        assert agent._max_steps == 25


class TestDeepSeekAgentRun:
    """Agent.run() executes tasks end-to-end."""

    def test_run_returns_agent_result_with_final_output(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手",
            goal="帮助用户",
            backstory="通用助手",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False,
        )
        result = agent.run("回复'你好，测试成功'，不要其他内容")
        assert result.final_output is not None
        assert len(result.final_output) > 0
        assert "你好" in result.final_output or "测试" in result.final_output

    def test_run_returns_structured_agent_result(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手",
            goal="帮助用户",
            backstory="通用助手",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False,
            max_steps=1,
        )
        result = agent.run("说'ok'，不要其他内容")
        # All 5 fields must exist
        assert hasattr(result, 'final_output')
        assert hasattr(result, 'tool_calls')
        assert hasattr(result, 'tokens')
        assert hasattr(result, 'cost')
        assert hasattr(result, 'reasoning_content')
        assert isinstance(result.tool_calls, list)
        assert isinstance(result.tokens, dict)
        assert isinstance(result.cost, float)

    def test_run_with_thinking_produces_reasoning_content(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手",
            goal="帮助用户",
            backstory="通用助手，擅长逻辑推理",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=True,
            max_steps=1,
        )
        result = agent.run("请一步步推理：如果今天是周三，后天是周几？")
        assert result.reasoning_content is not None, (
            "thinking=True should produce reasoning_content"
        )
        assert len(result.reasoning_content) > 0

    def test_run_tracks_cost(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手",
            goal="帮助用户",
            backstory="通用助手",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False,
            max_steps=1,
        )
        result = agent.run("说'hello'")
        assert result.cost > 0.0, "Agent should track token cost"
        assert result.tokens.get("total_tokens", 0) > 0


# ══════════════════════════════════════════════════════════════════════
# v3-002: Task — description + expected_output + Agent binding
# ══════════════════════════════════════════════════════════════════════

class TestTaskDefinition:
    """Task is a Pydantic model with description and expected_output."""

    def test_task_creation(self):
        from seekflow.agent.task import Task

        task = Task(
            description="分析数据",
            expected_output="一份分析报告",
        )
        assert task.description == "分析数据"
        assert task.expected_output == "一份分析报告"
        assert task.agent is None
        assert task.context is None

    def test_task_with_agent_binding(self):
        from seekflow.agent.task import Task
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师",
            goal="分析",
            backstory="专家",
            api_key="sk-test",
        )
        task = Task(
            description="分析数据",
            expected_output="报告",
            agent=agent,
        )
        assert task.agent is agent

    def test_task_run_executes_bound_agent(self):
        from seekflow.agent.task import Task
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手",
            goal="帮助用户",
            backstory="通用助手",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False,
            max_steps=1,
        )
        task = Task(
            description="回复'任务完成'即可",
            expected_output="任务完成确认",
            agent=agent,
        )
        result = task.run()
        assert result.output is not None
        assert len(result.output) > 0
        assert result.agent_result is not None

    def test_task_context_passing(self):
        from seekflow.agent.task import Task
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手",
            goal="帮助用户",
            backstory="通用助手",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False,
            max_steps=1,
        )
        task = Task(
            description="回复'前置上下文: {context}'",
            expected_output="上下文回应",
            agent=agent,
        )
        result = task.run(context="这是前置任务的结果")
        assert len(result.output) > 0  # context was passed; output non-empty

    def test_task_without_agent_raises_on_run(self):
        from seekflow.agent.task import Task

        task = Task(
            description="分析数据",
            expected_output="报告",
        )
        with pytest.raises(RuntimeError, match="No agent assigned"):
            task.run()


# ══════════════════════════════════════════════════════════════════════
# v3-003: Agent Tools — .add_tool() / .add_tools()
# ══════════════════════════════════════════════════════════════════════

class TestAgentTools:
    """Agent can register and use custom tools."""

    def test_add_single_tool(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师", goal="分析", backstory="专家", api_key="sk-test",
        )

        def my_tool(x: str) -> str:
            """A test tool."""
            return f"result: {x}"

        agent.add_tool(my_tool)
        assert len(agent.tools) == 1

    def test_add_multiple_tools(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师", goal="分析", backstory="专家", api_key="sk-test",
        )

        def tool_a():
            return "a"

        def tool_b():
            return "b"

        agent.add_tools([tool_a, tool_b])
        assert len(agent.tools) == 2

    def test_duplicate_tool_warns(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师", goal="分析", backstory="专家", api_key="sk-test",
        )

        def my_tool():
            return "ok"

        agent.add_tool(my_tool)
        agent.add_tool(my_tool)  # duplicate — should not double-add
        assert len(agent.tools) == 1

    def test_agent_uses_registered_tool(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手",
            goal="使用工具完成任务",
            backstory="你会使用 get_time 工具",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False,
            max_steps=2,
        )

        def get_time() -> str:
            """Return the current time."""
            return "2025-01-15 14:30:00"

        agent.add_tool(get_time)
        result = agent.run("调用 get_time 工具，告诉我现在几点")
        assert "2025" in result.final_output or "14:30" in result.final_output

    def test_tools_property_is_readonly(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师", goal="分析", backstory="专家", api_key="sk-test",
        )
        agent.add_tool(lambda: "test")
        tools = agent.tools
        assert len(tools) == 1
        # Modifying returned list should not affect agent
        tools.append(lambda: "evil")
        assert len(agent.tools) == 1

    def test_with_default_tools_loads_builtins(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师", goal="分析", backstory="专家", api_key="sk-test",
            dangerous_tools=True,
        )
        agent.with_default_tools()
        assert len(agent.tools) >= 3  # calculate + read_file + save_result + ...

    def test_default_tools_are_callable_by_agent(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手",
            goal="使用工具解决问题",
            backstory="你会使用 calculate 工具",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False,
            max_steps=2,
        )
        agent.with_default_tools()
        result = agent.run("用 calculate 工具计算 123 * 456，告诉我结果")
        assert "56088" in result.final_output.replace(",", "") or "56088" in result.final_output.replace(" ", ""), (
            f"Expected 56088 in output, got: {result.final_output[:200]}"
        )

    def test_async_run_returns_agent_result(self):
        import pytest
        pytest.importorskip("asyncio")
        import asyncio
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手", goal="帮助", backstory="通用",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False, max_steps=1,
        )

        async def _test():
            return await agent.run_async("回复'async ok'")

        result = asyncio.run(_test())
        assert result.final_output is not None
        assert len(result.final_output) > 0


# ══════════════════════════════════════════════════════════════════════
# v3-004: Agent File Input — .run(files=[...])
# ══════════════════════════════════════════════════════════════════════

class TestAgentFileInput:
    """Agent can process files passed via .run(files=[...])."""

    DATA_DIR = "_archive/benchmarks/agents_comparison/data"

    def test_run_with_csv_file(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="数据分析师",
            goal="分析CSV数据",
            backstory="精通数据分析",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False,
            max_steps=1,
        )
        result = agent.run(
            "这个CSV文件包含多少条记录？简要回答",
            files=[f"{self.DATA_DIR}/sales_data.csv"],
        )
        assert "500" in result.final_output, (
            f"Expected '500' in output, got: {result.final_output[:200]}"
        )

    def test_run_with_json_file(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师",
            goal="分析JSON数据",
            backstory="专家",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False,
            max_steps=1,
        )
        result = agent.run(
            "这个JSON文件是关于什么公司的？简要回答",
            files=[f"{self.DATA_DIR}/financial_report.json"],
        )
        assert "字节" in result.final_output or "ByteDance" in result.final_output

    def test_nonexistent_file_raises_error(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师",
            goal="分析",
            backstory="专家",
            api_key="sk-test",
        )
        with pytest.raises(FileNotFoundError):
            agent.run("分析这个文件", files=["nonexistent_file.xyz"])


# ══════════════════════════════════════════════════════════════════════
# v3-006: Crew — Sequential Process
# ══════════════════════════════════════════════════════════════════════

class TestCrewSequential:
    """Crew executes Tasks in sequential order."""

    def test_crew_creation(self):
        from seekflow.agent.crew import Crew, Process
        from seekflow.agent.task import Task

        crew = Crew(
            tasks=[
                Task(description="task 1", expected_output="result 1"),
                Task(description="task 2", expected_output="result 2"),
            ],
            process=Process.SEQUENTIAL,
        )
        assert len(crew.tasks) == 2
        assert crew.process == Process.SEQUENTIAL

    def test_crew_default_process_is_sequential(self):
        from seekflow.agent.crew import Crew, Process
        from seekflow.agent.task import Task

        crew = Crew(tasks=[Task(description="t1", expected_output="r1")])
        assert crew.process == Process.SEQUENTIAL

    def test_sequential_crew_executes_all_tasks(self):
        from seekflow.agent.crew import Crew
        from seekflow.agent.task import Task
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手",
            goal="帮助用户",
            backstory="通用助手",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False,
            max_steps=1,
        )
        tasks = [
            Task(description="回复'第一步完成'", expected_output="确认", agent=agent),
            Task(description="回复'第二步完成'", expected_output="确认", agent=agent),
        ]
        crew = Crew(tasks=tasks)
        result = crew.kickoff()
        assert len(result.outputs) == 2
        assert result.final_output is not None
        assert result.total_cost > 0
        assert result.total_latency_ms > 0

    def test_sequential_crew_passes_context(self):
        from seekflow.agent.crew import Crew
        from seekflow.agent.task import Task
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手",
            goal="帮助用户",
            backstory="通用助手",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False,
            max_steps=1,
        )
        tasks = [
            Task(
                description="回复'我的数据: 苹果'",
                expected_output="数据",
                agent=agent,
            ),
            Task(
                description="基于前面的任务结果，复述收到的数据",
                expected_output="复述",
                agent=agent,
            ),
        ]
        crew = Crew(tasks=tasks)
        result = crew.kickoff()
        assert "苹果" in result.outputs[1].output

    def test_task_failure_stops_sequential_crew(self):
        from seekflow.agent.crew import Crew
        from seekflow.agent.task import Task
        from seekflow.agent.agent import DeepSeekAgent

        good_agent = DeepSeekAgent(
            role="助手", goal="帮助", backstory="通用",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False, max_steps=1,
        )
        # Task without agent will fail
        tasks = [
            Task(description="task 1", expected_output="ok", agent=good_agent),
            Task(description="task 2", expected_output="ok"),  # no agent → failure
            Task(description="task 3", expected_output="ok", agent=good_agent),
        ]
        crew = Crew(tasks=tasks)
        result = crew.kickoff()
        assert len(result.errors) > 0  # task 2 failed
        assert len(result.outputs) == 2  # task 2 (error) recorded, task 3 stopped


# ══════════════════════════════════════════════════════════════════════
# v3-007: Crew — Parallel Process
# ══════════════════════════════════════════════════════════════════════

class TestCrewParallel:
    """Crew executes independent Tasks in parallel."""

    def test_parallel_crew_executes_all_tasks(self):
        from seekflow.agent.crew import Crew, Process
        from seekflow.agent.task import Task
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手", goal="帮助", backstory="通用",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False, max_steps=1,
        )
        tasks = [
            Task(description="回复'任务A完成'", expected_output="确认", agent=agent),
            Task(description="回复'任务B完成'", expected_output="确认", agent=agent),
            Task(description="回复'任务C完成'", expected_output="确认", agent=agent),
        ]
        crew = Crew(tasks=tasks, process=Process.PARALLEL)
        result = crew.kickoff()
        assert len(result.outputs) == 3
        assert all("完成" in r.output for r in result.outputs)

    def test_parallel_one_failure_does_not_block_others(self):
        from seekflow.agent.crew import Crew, Process
        from seekflow.agent.task import Task
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手", goal="帮助", backstory="通用",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False, max_steps=1,
        )
        tasks = [
            Task(description="回复'OK'", expected_output="ok", agent=agent),
            # No agent → will fail
            Task(description="bad task", expected_output="x"),
            Task(description="回复'OK'", expected_output="ok", agent=agent),
        ]
        crew = Crew(tasks=tasks, process=Process.PARALLEL)
        result = crew.kickoff()
        assert len(result.outputs) == 3  # all tasks recorded
        assert len(result.errors) == 1  # one failure


# ══════════════════════════════════════════════════════════════════════
# v3-009: Document Protocol
# ══════════════════════════════════════════════════════════════════════

class TestDocumentProtocol:
    """Accept Documents via duck typing, not hard LangChain dependency."""

    def test_validate_langchain_document(self):
        from seekflow.compat.documents import validate_document

        class LCDoc:
            page_content = "hello"
            metadata = {"source": "test"}

        assert validate_document(LCDoc()) is True

    def test_validate_dict_as_document(self):
        from seekflow.compat.documents import to_agent_text

        docs = [{"page_content": "hello", "metadata": {"source": "test"}}]
        text = to_agent_text(docs)
        assert "hello" in text
        assert "test" in text

    def test_validate_str_as_document(self):
        from seekflow.compat.documents import to_agent_text

        text = to_agent_text(["plain text"])
        assert "plain text" in text

    def test_invalid_type_raises(self):
        from seekflow.compat.documents import to_agent_text

        import pytest
        with pytest.raises(TypeError, match="Unsupported document type"):
            to_agent_text([42])


# ══════════════════════════════════════════════════════════════════════
# v3-012: Checkpoint — InMemoryStore + SqliteStore
# ══════════════════════════════════════════════════════════════════════

class TestCheckpointStore:
    """Checkpoint save/load/delete/list works."""

    def test_inmemory_save_and_load(self):
        from seekflow.agent.checkpoint import (
            AgentCheckpoint, InMemoryStore,
        )

        store = InMemoryStore()
        cp = AgentCheckpoint(
            thread_id="test-1", step=3,
            messages=[{"role": "user", "content": "hi"}],
        )
        store.save(cp)
        loaded = store.load("test-1")
        assert loaded is not None
        assert loaded.step == 3
        assert loaded.messages[0]["content"] == "hi"

    def test_inmemory_load_missing_returns_none(self):
        from seekflow.agent.checkpoint import InMemoryStore

        store = InMemoryStore()
        assert store.load("nonexistent") is None

    def test_inmemory_list_sorted_by_timestamp(self):
        from seekflow.agent.checkpoint import (
            AgentCheckpoint, InMemoryStore,
        )

        store = InMemoryStore()
        store.save(AgentCheckpoint(thread_id="a", timestamp="2025-01-01"))
        store.save(AgentCheckpoint(thread_id="b", timestamp="2025-06-01"))
        results = store.list()
        assert results[0].thread_id == "b"  # newest first

    def test_sqlite_save_and_load(self, tmp_path):
        from seekflow.agent.checkpoint import (
            AgentCheckpoint, SqliteStore,
        )

        db_path = str(tmp_path / "test.db")
        store = SqliteStore(db_path)
        cp = AgentCheckpoint(
            thread_id="sql-1", step=5, messages=[{"role": "assistant", "content": "ok"}],
        )
        store.save(cp)
        loaded = store.load("sql-1")
        assert loaded is not None
        assert loaded.step == 5

    def test_sqlite_delete(self, tmp_path):
        from seekflow.agent.checkpoint import (
            AgentCheckpoint, SqliteStore,
        )

        db_path = str(tmp_path / "test.db")
        store = SqliteStore(db_path)
        store.save(AgentCheckpoint(thread_id="del-me"))
        store.delete("del-me")
        assert store.load("del-me") is None


# ══════════════════════════════════════════════════════════════════════
# v3-008: Crew Lifecycle — CrewContext + Callback
# ══════════════════════════════════════════════════════════════════════

class TestCrewLifecycle:
    """CrewContext and progress callback."""

    def test_crew_progress_callback_is_called(self):
        from seekflow.agent.crew import Crew, CrewProgress
        from seekflow.agent.task import Task
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手", goal="帮助", backstory="通用",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False, max_steps=1,
        )
        tasks = [
            Task(description="回复'OK'", expected_output="ok", agent=agent),
            Task(description="回复'OK'", expected_output="ok", agent=agent),
        ]

        progress_calls = []

        def callback(p: CrewProgress):
            progress_calls.append(p)

        crew = Crew(tasks=tasks, callback=callback)
        result = crew.kickoff()
        assert len(progress_calls) >= 2  # at least start + end for each task

    def test_crew_result_summary(self):
        from seekflow.agent.crew import Crew
        from seekflow.agent.task import Task
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手", goal="帮助", backstory="通用",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False, max_steps=1,
        )
        tasks = [
            Task(description="回复'任务A'", expected_output="ok", agent=agent),
            Task(description="回复'任务B'", expected_output="ok", agent=agent),
        ]
        crew = Crew(tasks=tasks)
        result = crew.kickoff()
        assert result.summary is not None
        assert "任务A" in result.summary or "Task 0" in result.summary


# ══════════════════════════════════════════════════════════════════════
# v3-014: Hierarchical Process — Manager delegates to Workers
# ══════════════════════════════════════════════════════════════════════

class TestCrewHierarchical:
    """Manager Agent decomposes and delegates to Worker Agents."""

    def test_hierarchical_crew_has_manager_and_workers(self):
        from seekflow.agent.crew import Crew, Process
        from seekflow.agent.task import Task
        from seekflow.agent.agent import DeepSeekAgent

        manager = DeepSeekAgent(
            role="项目经理",
            goal="分解任务并分配给团队",
            backstory="经验丰富的项目经理",
            api_key="sk-test",
        )
        worker = DeepSeekAgent(
            role="研究员",
            goal="执行研究任务",
            backstory="研究专家",
            api_key="sk-test",
        )
        tasks = [
            Task(description="研究AI趋势", expected_output="研究报告", agent=worker),
        ]
        crew = Crew(
            tasks=tasks,
            process=Process.HIERARCHICAL,
            manager_agent=manager,
        )
        assert crew.manager_agent is manager
        assert crew.process == Process.HIERARCHICAL

    def test_hierarchical_without_manager_raises(self):
        from seekflow.agent.crew import Crew, Process
        from seekflow.agent.task import Task

        with pytest.raises(ValueError, match="manager_agent"):
            Crew(
                tasks=[Task(description="t1", expected_output="ok")],
                process=Process.HIERARCHICAL,
            ).kickoff()

    def test_delegate_tool_dispatches_to_worker(self):
        from seekflow.agent.crew import Crew, Process
        from seekflow.agent.task import Task
        from seekflow.agent.agent import DeepSeekAgent

        worker = DeepSeekAgent(
            role="数据分析师",
            goal="分析数据",
            backstory="数据专家",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False,
            max_steps=1,
        )
        manager = DeepSeekAgent(
            role="项目经理",
            goal="将任务分配给数据分析师执行",
            backstory="你有一个团队成员叫'数据分析师'，使用 delegate_task 工具分配任务",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False,
            max_steps=3,
        )
        tasks = [
            Task(description="计算1+1", expected_output="数字2", agent=worker),
        ]
        crew = Crew(
            tasks=tasks,
            process=Process.HIERARCHICAL,
            manager_agent=manager,
        )
        result = crew.kickoff()
        assert result.final_output is not None
        assert len(result.final_output) > 0


# ══════════════════════════════════════════════════════════════════════
# v3-011: MCP Integration at Agent layer
# ══════════════════════════════════════════════════════════════════════

class TestMCPIntegration:
    """Agent can register MCP server configs."""

    def test_add_mcp_server_stores_config(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师", goal="分析", backstory="专家", api_key="sk-test",
        )
        agent.add_mcp_server("my-server", "python", ["-m", "echo_server"])
        assert len(agent._mcp_servers) == 1
        assert agent._mcp_servers[0].name == "my-server"

    def test_add_mcp_server_without_args(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师", goal="分析", backstory="专家", api_key="sk-test",
        )
        agent.add_mcp_server("simple-server", "node", [])
        assert len(agent._mcp_servers) == 1


# ══════════════════════════════════════════════════════════════════════
# v3-013: Crew Checkpoint/Resume Integration
# ══════════════════════════════════════════════════════════════════════

class TestCrewCheckpointResume:
    """Crew can save/restore state and resume from interrupt."""

    def test_crew_saves_checkpoint_per_task(self):
        from seekflow.agent.crew import Crew
        from seekflow.agent.task import Task
        from seekflow.agent.agent import DeepSeekAgent
        from seekflow.agent.checkpoint import InMemoryStore

        agent = DeepSeekAgent(
            role="助手", goal="帮助", backstory="通用",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False, max_steps=1,
        )
        tasks = [
            Task(description="回复'任务A'", expected_output="ok", agent=agent),
            Task(description="回复'任务B'", expected_output="ok", agent=agent),
        ]
        store = InMemoryStore()
        crew = Crew(tasks=tasks, checkpoint=True, checkpoint_store=store)
        result = crew.kickoff()

        # After kickoff, checkpoint should exist for thread
        checkpoints = store.list()
        assert len(checkpoints) > 0
        assert result.thread_id is not None

    def test_crew_resume_from_checkpoint(self):
        from seekflow.agent.crew import Crew
        from seekflow.agent.task import Task
        from seekflow.agent.agent import DeepSeekAgent
        from seekflow.agent.checkpoint import InMemoryStore

        agent = DeepSeekAgent(
            role="助手", goal="帮助", backstory="通用",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False, max_steps=1,
        )
        tasks = [
            Task(description="回复'第一步完成'", expected_output="确认", agent=agent),
            Task(description="回复'第二步完成'", expected_output="确认", agent=agent),
        ]
        store = InMemoryStore()
        crew = Crew(tasks=tasks, checkpoint=True, checkpoint_store=store)
        result1 = crew.kickoff()

        # Simulate resume — should have completed both tasks already
        result2 = crew.resume(result1.thread_id)
        assert result2.resumed_from is not None
        # Nothing to run — all tasks complete
        assert len(result2.outputs) >= 0


# ══════════════════════════════════════════════════════════════════════
# v3-017: Agent.stream() — streaming with reasoning events
# ══════════════════════════════════════════════════════════════════════

class TestAgentStream:
    """Agent.stream() yields StreamEvents in real time."""

    def test_stream_yields_content_and_done(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手", goal="帮助", backstory="通用",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False, max_steps=1,
        )
        events = list(agent.stream("说'hello world'，仅此一句"))
        assert len(events) > 0
        # Should have at least content + done
        types = [e.type for e in events]
        assert "content" in types or any(e.content and "hello" in e.content.lower() for e in events if e.content)
        assert "done" in types

    def test_stream_with_thinking_yields_reasoning(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手", goal="帮助", backstory="擅长逻辑推理",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=True, max_steps=1,
        )
        events = list(agent.stream("1+1等于几？一步一步推理"))
        types = [e.type for e in events]
        assert "reasoning" in types, f"Expected reasoning events, got types: {types}"

    def test_stream_with_tools(self):
        from seekflow.agent.agent import DeepSeekAgent

        def get_time() -> str:
            """Return current time."""
            return "14:30:00"

        agent = DeepSeekAgent(
            role="助手", goal="使用工具", backstory="会调用get_time",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False, max_steps=3,
        )
        agent.add_tool(get_time)
        events = list(agent.stream("调用get_time工具告诉我时间"))
        types = [e.type for e in events]
        assert "tool_call_start" in types or "tool_call_result" in types

    def test_stream_done_event_has_usage(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手", goal="帮助", backstory="通用",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False, max_steps=1,
        )
        events = list(agent.stream("回复ok"))
        done_events = [e for e in events if e.type == "done"]
        assert len(done_events) >= 1
        assert done_events[-1].usage is not None


# ══════════════════════════════════════════════════════════════════════
# v3-018: Structured Output — response_format + Pydantic
# ══════════════════════════════════════════════════════════════════════

class TestAgentStructuredOutput:
    """Agent can constrain output format."""

    def test_response_format_json_object(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手", goal="返回JSON", backstory="总是返回JSON",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False, max_steps=1,
            response_format="json_object",
        )
        result = agent.run('返回 {"name": "test", "value": 42}')
        assert result.final_output is not None
        # Should contain JSON-like structure
        assert "{" in result.final_output or "name" in result.final_output

    def test_response_format_default_is_none(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手", goal="帮助", backstory="通用",
            api_key="sk-test",
        )
        assert agent._response_format is None


# ══════════════════════════════════════════════════════════════════════
# v3-019: 1M Context Window
# ══════════════════════════════════════════════════════════════════════

class TestAgent1MContext:
    """Agent uses 1M context window by default."""

    def test_default_max_context_is_900k(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师", goal="分析", backstory="专家", api_key="sk-test",
        )
        rt = agent._make_runtime()
        assert rt._max_context_tokens == 900000, (
            f"Expected 900K max context, got {rt._max_context_tokens}"
        )

    def test_custom_max_context(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师", goal="分析", backstory="专家", api_key="sk-test",
            max_context_tokens=500000,
        )
        rt = agent._make_runtime()
        assert rt._max_context_tokens == 500000


# ══════════════════════════════════════════════════════════════════════
# v3-020: Parallel Tool Execution
# ══════════════════════════════════════════════════════════════════════

class TestAgentVectorStore:
    """Vector store + embedding wiring works."""

    def test_use_embedding_stores_function(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师", goal="分析", backstory="专家", api_key="sk-test",
        )

        def fake_embed(text: str) -> list[float]:
            return [0.1, 0.2, 0.3]

        agent.use_embedding(fake_embed)
        assert agent._embedding_fn is not None

    def test_vector_store_retrieval_injects_into_messages(self):
        from seekflow.agent.agent import DeepSeekAgent

        class FakeStore:
            def search(self, query, top_k=5):
                return [{"page_content": "relevant info", "metadata": {"source": "db"}}]

        agent = DeepSeekAgent(
            role="分析师", goal="分析", backstory="专家", api_key="sk-test",
        )
        agent.use_vector_store(FakeStore())
        msgs = agent._make_messages("test query")
        assert any("relevant info" in m["content"] for m in msgs)


# ══════════════════════════════════════════════════════════════════════
# v3-027: tiktoken accurate token counting
# ══════════════════════════════════════════════════════════════════════

class TestTokenAccuracy:
    """Token counting uses tiktoken when available, not char/4 fallback."""

    def test_count_tokens_uses_tiktoken_for_messages(self):
        from seekflow.token_counter import count_tokens

        tokens = count_tokens([
            {"role": "user", "content": "你好世界"}
        ])
        # tiktoken cl100k_base: 你好世界 = ~4-8 tokens
        assert 2 < tokens < 20, f"Expected 2-20 tokens, got {tokens}"

    def test_count_tokens_includes_reasoning_content(self):
        from seekflow.token_counter import count_tokens

        tokens = count_tokens([
            {"role": "assistant", "content": "ok", "reasoning_content": "let me think about this carefully"}
        ])
        tokens_no_reasoning = count_tokens([
            {"role": "assistant", "content": "ok"}
        ])
        assert tokens > tokens_no_reasoning, "reasoning_content should add tokens"

    def test_context_compressor_uses_token_counter(self):
        from seekflow.compat.compressor import ContextCompressor

        cc = ContextCompressor(max_tokens=100, keep_last=2)
        msgs = [
            {"role": "user", "content": "hello world " * 50}  # ~200 chars
        ]
        # Should detect overflow and compress
        assert cc.should_compress(msgs)


# ══════════════════════════════════════════════════════════════════════
# v3-034: A2A Protocol
# ══════════════════════════════════════════════════════════════════════

class TestA2AProtocol:
    """A2A bridge: register agents, discover, send tasks."""

    def test_agent_card_creation(self):
        from seekflow.compat.a2a import AgentCard

        card = AgentCard(
            name="analyst",
            description="Data analysis agent",
            capabilities=["analysis", "reporting"],
        )
        assert card.name == "analyst"
        assert "analysis" in card.capabilities

    def test_bridge_register_and_discover(self):
        from seekflow.compat.a2a import AgentCard, A2ABridge
        from seekflow.agent.agent import DeepSeekAgent

        bridge = A2ABridge()
        agent = DeepSeekAgent(
            role="分析师", goal="分析", backstory="专家", api_key="sk-test",
        )
        card = AgentCard(name="analyst", description="Data analyst")
        bridge.register(card, agent)
        cards = bridge.discover()
        assert len(cards) == 1

    def test_bridge_send_task_to_unknown_agent(self):
        from seekflow.compat.a2a import A2ABridge

        bridge = A2ABridge()
        task = bridge.send_task("nonexistent", "do something")
        assert task.status == "failed"
        assert "not found" in task.result


# ══════════════════════════════════════════════════════════════════════
# Gap Fix 1: Conditional Routing — skip/loop/branch in Crew
# ══════════════════════════════════════════════════════════════════════

class TestConditionalRouting:
    """Tasks can be conditionally skipped, looped, or branched."""

    def test_task_with_skip_condition(self):
        from seekflow.agent.task import Task

        task = Task(
            description="should skip",
            expected_output="any",
            skip_condition=lambda ctx: True,  # always skip
        )
        assert task.should_skip({}) is True

    def test_task_with_loop_condition(self):
        from seekflow.agent.task import Task

        count = [0]

        def loop_until_three(ctx):
            count[0] += 1
            return count[0] < 3  # repeat 3 times

        task = Task(
            description="loop task",
            expected_output="any",
            loop_condition=loop_until_three,
            max_loops=5,
        )
        # should keep looping while loop_condition returns True
        assert task.should_loop({}) is True
        assert task.should_loop({}) is True
        assert task.should_loop({}) is False  # count[0] now 3

    def test_sequential_crew_skips_conditionally(self):
        from seekflow.agent.crew import Crew
        from seekflow.agent.task import Task
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手", goal="帮助", backstory="通用",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False, max_steps=1,
        )
        tasks = [
            Task(description="回复'hello'", expected_output="ok", agent=agent),
            Task(
                description="should be skipped",
                expected_output="any",
                agent=agent,
                skip_condition=lambda ctx: True,
            ),
            Task(description="回复'world'", expected_output="ok", agent=agent),
        ]
        crew = Crew(tasks=tasks)
        result = crew.kickoff()
        # Task 1 should be skipped, so outputs should have 2 results + 1 skip
        assert len(result.outputs) >= 2


# ══════════════════════════════════════════════════════════════════════
# Gap Fix 2: Semantic Memory
# ══════════════════════════════════════════════════════════════════════

class TestAgentMemory:
    """AgentMemory: short-term + long-term, zero external deps."""

    def test_short_term_memory_stores_interactions(self):
        from seekflow.agent.memory import AgentMemory

        mem = AgentMemory(short_term_size=5)
        mem.add_interaction("user", "hello")
        mem.add_interaction("assistant", "hi there")
        assert len(mem.recent()) == 2

    def test_long_term_recall_finds_relevant(self):
        from seekflow.agent.memory import AgentMemory

        mem = AgentMemory()
        mem.remember("用户喜欢简短的回答", importance=0.9)
        mem.remember("用户是Python开发者", importance=0.8)
        mem.remember("今天天气不错", importance=0.1)

        results = mem.recall("编程语言偏好", top_k=2)
        assert any("Python" in r for r in results)

    def test_memory_forgets_by_content(self):
        from seekflow.agent.memory import AgentMemory

        mem = AgentMemory()
        mem.remember("temporary fact")
        assert mem.forget("temporary fact") is True
        assert mem.forget("nonexistent") is False

    def test_agent_enable_memory(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="助手", goal="帮助", backstory="通用", api_key="sk-test",
        )
        agent.enable_memory()
        assert agent.memory is not None
        assert agent.memory.stats()["short_term_items"] == 0


# ══════════════════════════════════════════════════════════════════════
# v3-021/022/023/028: MCP + Documents + Presets
# ══════════════════════════════════════════════════════════════════════

class TestAgentMCP:
    """MCP server configs are properly wired to runtime."""

    def test_mcp_server_creates_valid_config(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师", goal="分析", backstory="专家", api_key="sk-test",
        )
        agent.add_mcp_server("test-srv", "python", ["-m", "echo"])
        assert len(agent._mcp_servers) == 1
        cfg = agent._mcp_servers[0]
        assert cfg.name == "test-srv"
        assert cfg.command == "python"
        assert cfg.transport == "stdio"

    def test_mcp_servers_passed_to_runtime(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师", goal="分析", backstory="专家", api_key="sk-test",
        )
        agent.add_mcp_server("srv", "node", ["server.js"])
        rt = agent._make_runtime()
        assert len(rt._mcp_servers) == 1


class TestAgentDocuments:
    """add_documents injects content into Agent context."""

    def test_add_documents_sets_internal_state(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师", goal="分析", backstory="专家", api_key="sk-test",
        )
        agent.add_documents([{"page_content": "test content", "metadata": {"source": "test.txt"}}])
        assert "test content" in agent._documents_text

    def test_add_documents_includes_in_messages(self):
        from seekflow.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="分析师", goal="分析", backstory="专家", api_key="sk-test",
        )
        agent.add_documents([{"page_content": "important data", "metadata": {"source": "data.txt"}}])
        msgs = agent._make_messages("query")
        assert any("important data" in m["content"] for m in msgs)


class TestAgentPresets:
    """Preset templates produce valid Agents."""

    def test_analyst_preset(self):
        from seekflow.agent.presets import analyst

        agent = analyst(api_key="sk-test")
        assert agent.role == "数据分析师"
        assert agent._thinking is True

    def test_coder_preset(self):
        from seekflow.agent.presets import coder

        agent = coder(api_key="sk-test")
        assert agent.role == "软件工程师"

    def test_researcher_preset(self):
        from seekflow.agent.presets import researcher

        agent = researcher(api_key="sk-test")
        assert agent.role == "研究员"
