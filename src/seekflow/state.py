"""Explicit state machine types for the tool-calling runtime."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class StepKind(str, Enum):
    """Phases of the tool-calling state machine."""

    PREPARE = "prepare"
    MODEL_CALL = "model_call"
    PARSE_RESPONSE = "parse_response"
    VALIDATE_TOOL_CALLS = "validate_tool_calls"
    POLICY_GATE = "policy_gate"
    EXECUTE_TOOLS = "execute_tools"
    APPEND_RESULTS = "append_results"
    FINALIZE = "finalize"


class RuntimeErrorRecord(BaseModel):
    """A non-fatal error that occurred during a runtime phase."""

    phase: str
    message: str
    step: int = 0


class BudgetState(BaseModel):
    """Remaining budget tracked across runtime steps."""

    remaining_cny: float = float("inf")
    remaining_prompt_tokens: int = 1_000_000
    remaining_tool_calls: int = 20
    deadline: float = 0.0


class RunState(BaseModel):
    """Typed, serializable snapshot of the tool-calling loop.

    Each phase of the state machine reads and updates this model.
    It is the single source of truth for a run's progress.
    """

    model_config = {"arbitrary_types_allowed": True}

    run_id: str
    model: str
    step: int = 0
    current_phase: StepKind = StepKind.PREPARE
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[Any] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    trace_id: str = ""
    finish_reason: str | None = None
    pending_tool_calls: list[Any] = Field(default_factory=list)
    budget: BudgetState = Field(default_factory=BudgetState)

    def record_error(self, phase: str, message: str) -> None:
        """Record a non-fatal error that occurred during *phase*."""
        self.errors.append({
            "phase": phase,
            "message": message,
            "step": self.step,
        })
