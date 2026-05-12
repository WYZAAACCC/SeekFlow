"""Crew — multi-Agent orchestration."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from deepseek_toolkit.agent.task import Task, TaskResult


class Process(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    HIERARCHICAL = "hierarchical"


@dataclass
class CrewProgress:
    """Progress update during Crew execution."""
    current_task_index: int
    total_tasks: int
    current_agent_name: str = ""
    status: str = "running"  # "running" | "completed" | "failed"


@dataclass
class CrewResult:
    """Result of a Crew.kickoff() call."""
    outputs: list[TaskResult] = field(default_factory=list)
    final_output: str = ""
    errors: list[str] = field(default_factory=list)
    total_cost: float = 0.0
    total_latency_ms: float = 0.0
    thread_id: str = ""
    resumed_from: int | None = None

    @property
    def summary(self) -> str:
        """Auto-generated execution summary."""
        lines = ["Crew Execution Summary", "=" * 30]
        for i, tr in enumerate(self.outputs):
            status = "OK" if "ERROR" not in tr.output else "FAILED"
            preview = tr.output[:80].replace("\n", " ")
            lines.append(f"  Task {i}: {status} — {preview}")
        if self.errors:
            lines.append(f"\nErrors: {len(self.errors)}")
        lines.append(f"\nTotal cost: CNY {self.total_cost:.6f}")
        lines.append(f"Total latency: {self.total_latency_ms:.0f}ms")
        return "\n".join(lines)


@dataclass
class Crew:
    """Orchestrates multiple Agents executing Tasks.

    Usage:
        crew = Crew(
            tasks=[task1, task2, task3],
            process=Process.SEQUENTIAL,
        )
        result = crew.kickoff()
    """

    tasks: list[Task]
    process: Process = Process.SEQUENTIAL
    max_workers: int = 5
    callback: Any = None  # Callable[[CrewProgress], None] | None
    manager_agent: Any = None  # DeepSeekAgent | None (required for HIERARCHICAL)
    checkpoint: bool = False
    checkpoint_store: Any = None  # CheckpointStore | None
    graph_mode: bool = False  # Use StateGraph instead of sequential/parallel

    def kickoff(self) -> CrewResult:
        """Execute all tasks according to the configured process."""
        import uuid
        start = time.time()

        # EventBus: crew.start
        from deepseek_toolkit.agent.events import get_event_bus, Event
        get_event_bus().emit(Event("crew.start", {"tasks": len(self.tasks), "process": self.process.value}))

        if not self.tasks:
            return CrewResult(
                errors=["No tasks to execute. Crew.tasks must not be empty."],
                total_latency_ms=(time.time() - start) * 1000,
            )

        # Graph mode: use StateGraph for orchestration
        if self.graph_mode:
            result = self._kickoff_graph(thread_id, start)
            get_event_bus().emit(Event("crew.end", {"tasks": len(self.tasks), "errors": len(result.errors)}))
            return result

        thread_id = str(uuid.uuid4())[:8]
        if self.checkpoint and self.checkpoint_store is None:
            from deepseek_toolkit.agent.checkpoint import InMemoryStore
            self.checkpoint_store = InMemoryStore()

        if self.process == Process.HIERARCHICAL:
            result = self._kickoff_hierarchical(start, thread_id)
        elif self.process == Process.PARALLEL:
            result = self._kickoff_parallel(start, thread_id)
        else:
            result = self._kickoff_sequential(start, thread_id)

        result.thread_id = thread_id
        get_event_bus().emit(Event("crew.end", {"tasks": len(self.tasks), "errors": len(result.errors)}))
        return result

    def resume(self, thread_id: str) -> CrewResult:
        """Resume Crew execution from the last checkpoint."""
        if self.checkpoint_store is None:
            return CrewResult(
                errors=["No checkpoint store configured"],
                thread_id=thread_id,
            )
        cp = self.checkpoint_store.load(thread_id)
        if cp is None:
            return CrewResult(
                errors=[f"No checkpoint found for thread '{thread_id}'"],
                thread_id=thread_id,
            )

        # Find which tasks are already complete
        completed_indices: set[int] = set(cp.tool_calls_completed or [])
        start = time.time()
        outputs: list[TaskResult] = []
        errors: list[str] = []
        total_cost = 0.0

        for i, task in enumerate(self.tasks):
            if i in completed_indices:
                # Re-use completed task output from checkpoint if available
                outputs.append(TaskResult(output=f"[resumed] Task {i} was already completed"))
                continue
            try:
                tr = task.run()
                outputs.append(tr)
                if tr.agent_result and hasattr(tr.agent_result, 'cost'):
                    total_cost += tr.agent_result.cost
                completed_indices.add(i)
                self._save_checkpoint(thread_id, list(completed_indices))
            except Exception as e:
                errors.append(f"Task {i}: {e}")
                outputs.append(TaskResult(output=f"ERROR: {e}"))
                break

        final_output = outputs[-1].output if outputs else ""
        return CrewResult(
            outputs=outputs, final_output=final_output,
            errors=errors, total_cost=total_cost,
            total_latency_ms=(time.time() - start) * 1000,
            thread_id=thread_id,
            resumed_from=len(completed_indices),
        )

    def _save_checkpoint(self, thread_id: str, completed: list[int]) -> None:
        if not self.checkpoint or self.checkpoint_store is None:
            return
        from deepseek_toolkit.agent.checkpoint import AgentCheckpoint
        self.checkpoint_store.save(AgentCheckpoint(
            thread_id=thread_id,
            step=len(completed),
            tool_calls_completed=list(completed),
        ))

    def _notify(self, idx: int, status: str) -> None:
        if self.callback is None:
            return
        agent_name = ""
        if idx < len(self.tasks) and self.tasks[idx].agent:
            agent_name = getattr(self.tasks[idx].agent, 'role', '')
        self.callback(CrewProgress(
            current_task_index=idx,
            total_tasks=len(self.tasks),
            current_agent_name=agent_name,
            status=status,
        ))

    def _kickoff_sequential(self, start: float, thread_id: str = "") -> CrewResult:
        outputs: list[TaskResult] = []
        errors: list[str] = []
        total_cost = 0.0
        prev_output = ""
        completed: list[int] = []
        routing_ctx: dict = {}
        failed = False
        i = 0

        while i < len(self.tasks):
            task = self.tasks[i]

            # Conditional: skip
            if task.should_skip(routing_ctx):
                outputs.append(TaskResult(output="[SKIPPED]", skipped=True))
                routing_ctx["last_output"] = "[SKIPPED]"
                completed.append(i)
                self._notify(i, "completed")
                self._save_checkpoint(thread_id, completed)
                i += 1
                continue

            # Execute (possibly with loop)
            loop_count = 0
            while True:
                self._notify(i, "running")
                try:
                    tr = task.run(context=prev_output)
                    outputs.append(tr)
                    if tr.agent_result and hasattr(tr.agent_result, 'cost'):
                        total_cost += tr.agent_result.cost
                    prev_output = tr.output
                    routing_ctx["last_output"] = tr.output
                    routing_ctx[f"task_{i}_output"] = tr.output
                    loop_count += 1

                    # Conditional: loop
                    if task.should_loop(routing_ctx) and loop_count < task.max_loops:
                        prev_output = tr.output
                        continue
                    break
                except Exception as e:
                    error_msg = f"Task {i} ({task.description[:50]}): {e}"
                    errors.append(error_msg)
                    outputs.append(TaskResult(output=f"ERROR: {error_msg}"))
                    routing_ctx["last_output"] = f"ERROR: {error_msg}"
                    self._notify(i, "failed")
                    failed = True
                    break

            if failed:
                break

            completed.append(i)
            self._notify(i, "completed")
            self._save_checkpoint(thread_id, completed)

            # Conditional: branch
            branch_target = task.get_branch(routing_ctx)
            if branch_target is not None and 0 <= branch_target < len(self.tasks):
                i = branch_target
            else:
                i += 1

        final_output = outputs[-1].output if outputs else ""
        return CrewResult(
            outputs=outputs, final_output=final_output,
            errors=errors, total_cost=total_cost,
            total_latency_ms=(time.time() - start) * 1000,
        )

    def _kickoff_parallel(self, start: float, thread_id: str = "") -> CrewResult:
        outputs: list[TaskResult] = [TaskResult(output="")] * len(self.tasks)
        errors: list[str] = []
        total_cost = 0.0
        completed: list[int] = []

        def _run_task(idx: int, task: Task) -> tuple[int, TaskResult, str | None]:
            try:
                tr = task.run()
                return (idx, tr, None)
            except Exception as e:
                return (idx, TaskResult(output=f"ERROR: {e}"), str(e))

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(_run_task, i, task): i
                for i, task in enumerate(self.tasks)
            }
            for future in as_completed(futures):
                idx, tr, err = future.result()
                outputs[idx] = tr
                if err:
                    errors.append(f"Task {idx}: {err}")
                else:
                    completed.append(idx)
                    if tr.agent_result and hasattr(tr.agent_result, 'cost'):
                        total_cost += tr.agent_result.cost

        self._save_checkpoint(thread_id, completed)

        combined = "\n\n".join(
            f"[Task {i}]: {r.output}" for i, r in enumerate(outputs)
        )
        return CrewResult(
            outputs=outputs, final_output=combined,
            errors=errors, total_cost=total_cost,
            total_latency_ms=(time.time() - start) * 1000,
        )

    def _kickoff_hierarchical(self, start: float, thread_id: str = "") -> CrewResult:
        """Manager decomposes task and delegates to workers."""
        if self.manager_agent is None:
            raise ValueError(
                "Hierarchical process requires manager_agent to be set"
            )

        # Build worker registry from tasks
        workers: dict[str, Any] = {}
        for task in self.tasks:
            if task.agent:
                name = getattr(task.agent, 'role', f'worker-{id(task)}')
                workers[name] = task.agent

        # Create delegate_task tool for manager
        def delegate_task(worker_name: str, task_description: str) -> str:
            """Delegate a sub-task to a worker agent by name.

            Args:
                worker_name: The role name of the worker agent
                task_description: Detailed description of the sub-task
            """
            if worker_name not in workers:
                available = list(workers.keys())
                return f"Worker '{worker_name}' not found. Available: {available}"
            worker = workers[worker_name]
            result = worker.run(task_description)
            return result.final_output

        manager = self.manager_agent
        manager.add_tool(delegate_task)

        # Build manager's task: describe all workers
        worker_list = "\n".join(
            f"- {name}: {task.description} (期望: {task.expected_output})"
            for name, task in zip(workers.keys(), self.tasks)
        )
        manager_task = (
            f"你是{manager.role}。\n"
            f"目标：{manager.goal}\n\n"
            f"你的团队成员及各自的任务：\n{worker_list}\n\n"
            f"请使用 delegate_task 工具将每个子任务分配给对应的团队成员。\n"
            f"分配完成后，汇总所有成员的结果，生成最终输出。"
        )

        # Edge: warn if thinking settings differ between manager and workers
        for task in self.tasks:
            if task.agent and hasattr(task.agent, '_thinking'):
                if manager._thinking != task.agent._thinking:
                    import warnings
                    warnings.warn(
                        f"Manager thinking={manager._thinking} but worker "
                        f"'{task.agent.role}' thinking={task.agent._thinking}. "
                        f"This may cause inconsistent behavior."
                    )

        mr = manager.run(manager_task)
        self._save_checkpoint(thread_id, [0])

        return CrewResult(
            outputs=[TaskResult(output=mr.final_output, agent_result=mr)],
            final_output=mr.final_output,
            errors=[],
            total_cost=mr.cost,
            total_latency_ms=(time.time() - start) * 1000,
        )

    def _kickoff_graph(self, thread_id: str, start: float) -> CrewResult:
        """Use StateGraph for orchestration — sequential with channel state."""
        from deepseek_toolkit.agent.stategraph import StateGraph

        g = StateGraph(dict)
        outputs: list[TaskResult] = []
        errors: list[str] = []
        total_cost = 0.0

        for i, task in enumerate(self.tasks):
            idx = i
            def _node(state, t=task, n=idx):
                try:
                    ctx = state.get(f"output_{n-1}", "") if n > 0 else ""
                    tr = t.run(context=ctx)
                    cost = tr.agent_result.cost if tr.agent_result and hasattr(tr.agent_result, 'cost') else 0.0
                    return {**state, f"output_{n}": tr.output, f"cost_{n}": cost}
                except Exception as e:
                    errors.append(f"Task {n}: {e}")
                    return {**state, f"output_{n}": f"ERROR: {e}", f"cost_{n}": 0.0}
            g.add_node(f"t{i}", _node)
            if i > 0:
                g.add_edge(f"t{i-1}", f"t{i}")
            if i == len(self.tasks) - 1:
                g.set_finish_point(f"t{i}")

        g.set_entry_point("t0")
        state = g.invoke({})

        for i in range(len(self.tasks)):
            out = state.get(f"output_{i}", "")
            outputs.append(TaskResult(output=out))
            total_cost += state.get(f"cost_{i}", 0.0)

        final = outputs[-1].output if outputs else ""
        return CrewResult(
            outputs=outputs, final_output=final,
            errors=errors, total_cost=total_cost,
            total_latency_ms=(time.time() - start) * 1000,
            thread_id=thread_id,
        )
