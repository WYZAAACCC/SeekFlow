"""SeekFlow — production-grade tool calling for DeepSeek.

Two layers, one library:
- **Reliability core** — tool(), ToolRuntime, JSON repair, retry, cache
- **Agent layer** — DeepSeekAgent, Crew, Task, StateGraph

Quick start:
    from seekflow import tool, ToolRuntime

    @tool
    def add(a: int, b: int) -> int:
        '''Add two numbers.'''
        return a + b

    runtime = ToolRuntime(tools=[add])
    result = runtime.chat(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "What is 123 + 456?"}],
    )
    print(result.final)
"""

__version__ = "0.2.5"

# ── Core API ──
from seekflow.tools.decorator import tool
from seekflow.tools.registry import ToolRegistry
from seekflow.tools.executor import ToolExecutor
from seekflow.runtime import ToolRuntime
from seekflow.async_runtime import AsyncToolRuntime
from seekflow.client import DeepSeekClient
from seekflow.types import (
    ToolDefinition,
    ToolCall,
    ToolExecutionResult,
    ChatResponse,
    StreamEvent,
    ToolRuntimeResult,
    ToolChoice,
)
from seekflow.errors import (
    SeekFlowError,
    DeepSeekAPIError,
    AuthenticationError,
    RateLimitError,
    InsufficientBalanceError,
    ContextLengthExceededError,
    ServiceUnavailableError,
    ToolSchemaError,
    ToolNotFoundError,
    ToolExecutionError,
    MCPConnectionError,
    map_http_error,
)

# ── Agent Layer (v3) ──
from seekflow.agent.agent import DeepSeekAgent, AgentResult
from seekflow.agent.task import Task, TaskResult
from seekflow.agent.crew import Crew, CrewResult, Process
from seekflow.agent.stategraph import StateGraph
from seekflow.agent.memory import AgentMemory
from seekflow.agent.checkpoint import AgentCheckpoint, InMemoryStore, SqliteStore

# ── Repair (standalone use) ──
from seekflow.repair.json_repair import repair_json_arguments, JsonRepairResult
from seekflow.repair.coercion import coerce_arguments

# ── Cache (prompt cache stability) ──
from seekflow.cache import CacheStabilizer, CacheSentinel, append_only_compress

# ── Advanced ──
from seekflow.retry import RetryPolicy, CircuitBreaker
from seekflow.cost import CostTracker
from seekflow.trace.recorder import TraceRecorder
from seekflow.reasoning import check_consistency, harvest_thoughts, HarvestedThoughts
from seekflow.consistency import run_branched, BranchResult
from seekflow.token_counter import count_tokens, count_text
from seekflow.structured import structured_output
from seekflow.fim import fim_complete, fim_complete_stream, FIMResponse
from seekflow.balance import get_balance, BalanceInfo

__all__ = [
    # Core
    "tool",
    "ToolRegistry",
    "ToolExecutor",
    "ToolRuntime",
    "AsyncToolRuntime",
    "DeepSeekClient",
    # Types
    "ToolDefinition",
    "ToolCall",
    "ToolExecutionResult",
    "ChatResponse",
    "StreamEvent",
    "ToolRuntimeResult",
    "ToolChoice",
    # Errors
    "SeekFlowError",
    "DeepSeekAPIError",
    "AuthenticationError",
    "RateLimitError",
    "InsufficientBalanceError",
    "ContextLengthExceededError",
    "ServiceUnavailableError",
    "ToolSchemaError",
    "ToolNotFoundError",
    "ToolExecutionError",
    "MCPConnectionError",
    "map_http_error",
    # Agent
    "DeepSeekAgent",
    "AgentResult",
    "Task",
    "TaskResult",
    "Crew",
    "CrewResult",
    "Process",
    "StateGraph",
    "AgentMemory",
    "AgentCheckpoint",
    "InMemoryStore",
    "SqliteStore",
    # Repair
    "repair_json_arguments",
    "JsonRepairResult",
    "coerce_arguments",
    # Advanced
    "CacheStabilizer",
    "CacheSentinel",
    "append_only_compress",
    "RetryPolicy",
    "CircuitBreaker",
    "CostTracker",
    "TraceRecorder",
    "check_consistency",
    "harvest_thoughts",
    "HarvestedThoughts",
    "run_branched",
    "BranchResult",
    "count_tokens",
    "count_text",
    "structured_output",
    "fim_complete",
    "fim_complete_stream",
    "FIMResponse",
    "get_balance",
    "BalanceInfo",
]
