"""Task — description + expected_output + Agent binding + conditional routing."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from seekflow.agent.agent import AgentResult, DeepSeekAgent


@dataclass
class TaskResult:
    """Result of executing a Task."""
    output: str = ""
    agent_result: Any = None  # AgentResult
    skipped: bool = False


@dataclass
class Task:
    """A unit of work assigned to an Agent.

    Supports conditional routing:
    - skip_condition: if True, skip this task
    - loop_condition: if True, re-run this task (up to max_loops)
    - branch_condition: returns next task index to jump to

    Usage:
        task = Task(description="分析数据", expected_output="报告", agent=agent)
        conditional = Task(
            description="check quality",
            expected_output="pass/fail",
            agent=agent,
            loop_condition=lambda ctx: "PASS" not in ctx.get("last_output", ""),
            max_loops=3,
        )
    """

    description: str
    expected_output: str
    agent: Any = None  # DeepSeekAgent | None
    context: list[Task] | None = field(default=None, repr=False)

    # Conditional routing
    skip_condition: Callable[[dict], bool] | None = field(default=None, repr=False)
    loop_condition: Callable[[dict], bool] | None = field(default=None, repr=False)
    branch_condition: Callable[[dict], int | None] | None = field(default=None, repr=False)
    max_loops: int = 1

    def should_skip(self, ctx: dict) -> bool:
        """Check if this task should be skipped."""
        if self.skip_condition is None:
            return False
        return self.skip_condition(ctx)

    def should_loop(self, ctx: dict) -> bool:
        """Check if this task should be re-executed."""
        if self.loop_condition is None:
            return False
        return self.loop_condition(ctx)

    def get_branch(self, ctx: dict) -> int | None:
        """Get the next task index to jump to, or None for default flow."""
        if self.branch_condition is None:
            return None
        return self.branch_condition(ctx)

    def run(self, context: str = "") -> TaskResult:
        """Execute this task with the bound Agent."""
        if self.agent is None:
            raise RuntimeError("No agent assigned to this task")

        task_prompt = self.description
        if context:
            task_prompt = f"{self.description}\n\n前置上下文:\n{context}"
        task_prompt += f"\n\n期望输出: {self.expected_output}"

        agent_result = self.agent.run(task_prompt)
        return TaskResult(
            output=agent_result.final_output,
            agent_result=agent_result,
        )
