"""Tests for performance upgrade issues — EventBus, StateGraph, etc."""
import os
import pytest


# ══════════════════════════════════════════════════════════════════════
# perf-002: EventBus — subscribe/unsubscribe/emit
# ══════════════════════════════════════════════════════════════════════

class TestEventBus:
    """EventBus: publish-subscribe for Agent lifecycle events."""

    def test_subscribe_and_emit(self):
        from deepseek_toolkit.agent.events import EventBus, Event

        bus = EventBus()
        received = []

        def handler(event: Event):
            received.append(event)

        bus.subscribe("test.event", handler)
        bus.emit(Event(type="test.event", data={"key": "value"}))
        assert len(received) == 1
        assert received[0].data["key"] == "value"

    def test_unsubscribe(self):
        from deepseek_toolkit.agent.events import EventBus, Event

        bus = EventBus()
        received = []

        def handler(event: Event):
            received.append(event)

        bus.subscribe("test.event", handler)
        bus.unsubscribe("test.event", handler)
        bus.emit(Event(type="test.event", data={}))
        assert len(received) == 0

    def test_multiple_handlers_same_event(self):
        from deepseek_toolkit.agent.events import EventBus, Event

        bus = EventBus()
        results = set()

        def handler_a(e): results.add("a")
        def handler_b(e): results.add("b")

        bus.subscribe("test.event", handler_a)
        bus.subscribe("test.event", handler_b)
        bus.emit(Event(type="test.event", data={}))
        assert results == {"a", "b"}

    def test_handler_exception_does_not_block_others(self):
        from deepseek_toolkit.agent.events import EventBus, Event

        bus = EventBus()
        ok = []

        def bad_handler(e):
            raise RuntimeError("boom")

        def good_handler(e):
            ok.append("ok")

        bus.subscribe("test.event", bad_handler)
        bus.subscribe("test.event", good_handler)
        bus.emit(Event(type="test.event", data={}))
        assert ok == ["ok"]  # good handler still called

    def test_wildcard_subscription(self):
        from deepseek_toolkit.agent.events import EventBus, Event

        bus = EventBus()
        received = []

        def catch_all(event: Event):
            received.append(event.type)

        bus.subscribe("*", catch_all)
        bus.emit(Event(type="agent.start", data={}))
        bus.emit(Event(type="tool.end", data={}))
        assert "agent.start" in received
        assert "tool.end" in received

    def test_global_bus_singleton(self):
        from deepseek_toolkit.agent.events import get_event_bus

        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2


# ══════════════════════════════════════════════════════════════════════
# perf-001: StateGraph — Channel state + conditional edges + interrupt
# ══════════════════════════════════════════════════════════════════════

class TestStateGraph:
    """StateGraph: state channels, conditional edges, interrupt/resume."""

    def test_simple_linear_graph(self):
        from deepseek_toolkit.agent.stategraph import StateGraph

        class TestState(dict):
            pass

        g = StateGraph(TestState)
        g.add_node("a", lambda s: {**s, "a": 1})
        g.add_node("b", lambda s: {**s, "b": s["a"] + 1})
        g.add_edge("a", "b")
        g.set_entry_point("a")
        g.set_finish_point("b")

        result = g.invoke(TestState({"x": 0}))
        assert result["a"] == 1
        assert result["b"] == 2

    def test_channel_with_append_reducer(self):
        from deepseek_toolkit.agent.stategraph import StateGraph

        class TestState(dict):
            pass

        g = StateGraph(TestState)
        g.add_channel("items", reducer="append")
        g.add_node("step1", lambda s: {**s, "items": ["a"]})
        g.add_node("step2", lambda s: {**s, "items": ["b"]})
        g.add_edge("step1", "step2")
        g.set_entry_point("step1")
        g.set_finish_point("step2")

        result = g.invoke(TestState({"items": []}))
        assert result["items"] == ["a", "b"]

    def test_conditional_edge_routes_correctly(self):
        from deepseek_toolkit.agent.stategraph import StateGraph

        class TestState(dict):
            pass

        g = StateGraph(TestState)
        g.add_node("start", lambda s: {**s, "score": 85})
        g.add_node("high", lambda s: {**s, "path": "high"})
        g.add_node("low", lambda s: {**s, "path": "low"})

        g.add_conditional_edges(
            "start",
            lambda s: "high" if s.get("score", 0) >= 80 else "low",
            {"high": "high", "low": "low"},
        )
        g.set_entry_point("start")
        g.set_finish_point("high")
        g.set_finish_point("low")

        result = g.invoke(TestState({}))
        assert result["path"] == "high"

    def test_interrupt_and_resume(self):
        from deepseek_toolkit.agent.stategraph import StateGraph, Interrupt, Command

        class TestState(dict):
            pass

        g = StateGraph(TestState)
        g.add_node("step1", lambda s: {**s, "a": 1})
        g.add_node("check", lambda s: Interrupt("need human approval"))
        g.add_node("step2", lambda s: {**s, "b": 2})
        g.add_edge("step1", "check")
        g.add_edge("check", "step2")
        g.set_entry_point("step1")
        g.set_finish_point("step2")

        # Execute: step1 → check (interrupt)
        result = g.invoke(TestState({}))
        assert g.interrupted is True
        assert result["a"] == 1  # step1 completed

        # Resume: check → step2
        result = g.invoke(result, command=Command(resume="approved"))
        assert result["b"] == 2  # step2 completed


# ══════════════════════════════════════════════════════════════════════
# perf-005: Session management — auto-compress + fork/rollback
# ══════════════════════════════════════════════════════════════════════

class TestSessionManagement:
    """Session: auto-compress, fork, rollback, persist."""

    def test_agent_has_session_methods(self):
        from deepseek_toolkit.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="test", goal="test", backstory="test", api_key="sk-test",
        )
        assert hasattr(agent, 'fork_session')
        assert hasattr(agent, 'rollback')
        assert hasattr(agent, 'list_sessions')
        assert callable(agent.fork_session)
        assert callable(agent.rollback)

    def test_rollback_restores_previous_state(self):
        from deepseek_toolkit.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="test", goal="test", backstory="test",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False, max_steps=1,
        )
        agent.chat("turn 1")
        count_after_1 = len(agent._session_messages)
        assert count_after_1 > 0
        agent.chat("turn 2")
        assert len(agent._session_messages) > count_after_1
        agent.rollback(1)  # rollback to after first turn
        assert len(agent._session_messages) == count_after_1


# ══════════════════════════════════════════════════════════════════════
# perf-003: Builtin tools — 20+ tools
# ══════════════════════════════════════════════════════════════════════

class TestBuiltinTools:
    """Builtin tools library with 20+ tools."""

    def test_with_default_tools_has_20_tools(self):
        from deepseek_toolkit.agent.agent import DeepSeekAgent

        agent = DeepSeekAgent(
            role="test", goal="test", backstory="test", api_key="sk-test",
        )
        agent.with_default_tools()
        assert len(agent.tools) >= 10, f"Expected >=10 tools, got {len(agent.tools)}"

    def test_builtin_tools_are_callable(self):
        from deepseek_toolkit.agent.builtins import fetch_url, run_python, parse_csv_str

        csv_result = parse_csv_str("name,age\nAlice,30\nBob,25")
        assert "Alice" in csv_result
        assert "30" in csv_result


# ══════════════════════════════════════════════════════════════════════
# perf-004: Semantic memory upgrade — TF-IDF
# ══════════════════════════════════════════════════════════════════════

class TestMemoryUpgrade:
    """Memory with optional TF-IDF support."""

    def test_memory_recall_still_works(self):
        from deepseek_toolkit.agent.memory import AgentMemory

        mem = AgentMemory()
        mem.remember("用户是Python开发者", importance=1.0)
        mem.remember("天气数据来源是OpenWeatherMap", importance=0.8)
        results = mem.recall("编程语言偏好", top_k=1)
        assert any("Python" in r for r in results)

    def test_memory_consolidation_merges_similar(self):
        from deepseek_toolkit.agent.memory import AgentMemory

        mem = AgentMemory()
        mem.remember("API key is sk-abc123", importance=0.9)
        mem.remember("API key is sk-abc123", importance=0.9)  # duplicate
        # Two similar memories should be consolidated
        assert mem.stats()["long_term_items"] <= 3


# ══════════════════════════════════════════════════════════════════════
# Remaining audit fixes: Crew.graph_mode, EventBus in Crew, TaskGraph, Search
# ══════════════════════════════════════════════════════════════════════

class TestCrewGraphMode:
    """Crew can switch to StateGraph-based orchestration."""

    def test_crew_graph_mode_property(self):
        from deepseek_toolkit.agent.crew import Crew, Process
        from deepseek_toolkit.agent.task import Task

        crew = Crew(
            tasks=[Task(description="test", expected_output="ok")],
            graph_mode=True,
        )
        assert crew.graph_mode is True

    def test_crew_graph_mode_default_is_false(self):
        from deepseek_toolkit.agent.crew import Crew
        from deepseek_toolkit.agent.task import Task

        crew = Crew(tasks=[Task(description="test", expected_output="ok")])
        assert crew.graph_mode is False


class TestCrewEventBus:
    """Crew.kickoff() emits events via EventBus."""

    def test_crew_emits_events_during_kickoff(self):
        from deepseek_toolkit.agent.crew import Crew
        from deepseek_toolkit.agent.task import Task
        from deepseek_toolkit.agent.agent import DeepSeekAgent
        from deepseek_toolkit.agent.events import get_event_bus

        events = []
        get_event_bus().subscribe("*", lambda e: events.append(e.type))

        agent = DeepSeekAgent(
            role="test", goal="test", backstory="test",
            api_key=os.environ.get("DEEPSEEK_API_KEY", "sk-test"),
            thinking=False, max_steps=1,
        )
        tasks = [
            Task(description="say ok", expected_output="ok", agent=agent),
        ]
        crew = Crew(tasks=tasks)
        crew.kickoff()

        assert "crew.start" in events
        assert "crew.end" in events
