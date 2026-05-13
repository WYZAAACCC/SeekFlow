"""A2A Protocol — Agent-to-Agent communication (Google/Linux Foundation 2025).

Minimal implementation: AgentCard publishing, task push/receive.
Full A2A spec requires JSON-RPC over HTTPS; this module provides
the data structures and a local delegation bridge.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentCard:
    """A2A Agent Card — describes an agent's capabilities."""
    name: str
    description: str
    url: str = ""  # endpoint URL for remote A2A
    capabilities: list[str] = field(default_factory=list)


@dataclass
class A2ATask:
    """A task delegated from one agent to another via A2A."""
    task_id: str
    description: str
    from_agent: str = ""
    status: str = "pending"  # pending | running | completed | failed
    result: str = ""


class A2ABridge:
    """Local A2A bridge — allows Agents to discover and delegate tasks.

    Usage:
        bridge = A2ABridge()
        bridge.register(agent_card, agent_instance)
        result = bridge.send_task("agent-name", "analyze this data")
    """

    def __init__(self):
        self._registry: dict[str, tuple[AgentCard, Any]] = {}

    def register(self, card: AgentCard, agent: Any) -> None:
        """Register an agent in the A2A registry."""
        self._registry[card.name] = (card, agent)

    def discover(self) -> list[AgentCard]:
        """List all registered agents."""
        return [card for card, _ in self._registry.values()]

    def send_task(self, target_name: str, description: str) -> A2ATask:
        """Send a task to a registered agent and return the result."""
        import uuid
        if target_name not in self._registry:
            return A2ATask(
                task_id=str(uuid.uuid4())[:8],
                description=description,
                status="failed",
                result=f"Agent '{target_name}' not found. Available: {list(self._registry.keys())}",
            )
        _, agent = self._registry[target_name]
        task = A2ATask(
            task_id=str(uuid.uuid4())[:8],
            description=description,
            from_agent="a2a-bridge",
            status="running",
        )
        try:
            result = agent.run(description)
            task.status = "completed"
            task.result = result.final_output
        except Exception as e:
            task.status = "failed"
            task.result = str(e)
        return task


__all__ = ["AgentCard", "A2ATask", "A2ABridge"]
