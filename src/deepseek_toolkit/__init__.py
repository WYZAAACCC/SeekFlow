"""DeepSeek Toolkit — production-grade tool calling for DeepSeek.

Two layers, one library:
- **Reliability core** — tool(), ToolRuntime, JSON repair, retry, cache
- **Agent layer** — DeepSeekAgent, Crew, Task, StateGraph

Quick start:
    from deepseek_toolkit import tool, ToolRuntime

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

# ── Core API ──
from deepseek_toolkit.tools.decorator import tool
from deepseek_toolkit.tools.registry import ToolRegistry
from deepseek_toolkit.tools.executor import ToolExecutor
from deepseek_toolkit.runtime import ToolRuntime
from deepseek_toolkit.async_runtime import AsyncToolRuntime
from deepseek_toolkit.client import DeepSeekClient
from deepseek_toolkit.types import (
    ToolDefinition,
    ToolCall,
    ToolExecutionResult,
    ChatResponse,
    StreamChunk,
    StreamEvent,
    ToolRuntimeResult,
)
from deepseek_toolkit.errors import (
    DeepSeekToolkitError,
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
from deepseek_toolkit.agent.agent import DeepSeekAgent, AgentResult
from deepseek_toolkit.agent.task import Task, TaskResult
from deepseek_toolkit.agent.crew import Crew, CrewResult, Process
from deepseek_toolkit.agent.stategraph import StateGraph
from deepseek_toolkit.agent.memory import AgentMemory
from deepseek_toolkit.agent.checkpoint import AgentCheckpoint, InMemoryStore, SqliteStore

# ── Repair (standalone use) ──
from deepseek_toolkit.repair.json_repair import repair_json_arguments, JsonRepairResult
from deepseek_toolkit.repair.coercion import coerce_arguments

# ── Advanced ──
from deepseek_toolkit.retry import RetryPolicy, CircuitBreaker
from deepseek_toolkit.cost import CostTracker
from deepseek_toolkit.trace.recorder import TraceRecorder
from deepseek_toolkit.reasoning import check_consistency
from deepseek_toolkit.token_counter import count_tokens, count_text
from deepseek_toolkit.structured import structured_output
from deepseek_toolkit.fim import fim_complete, fim_complete_stream, FIMResponse
from deepseek_toolkit.balance import get_balance, BalanceInfo

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
    "StreamChunk",
    "StreamEvent",
    "ToolRuntimeResult",
    # Errors
    "DeepSeekToolkitError",
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
    "RetryPolicy",
    "CircuitBreaker",
    "CostTracker",
    "TraceRecorder",
    "check_consistency",
    "count_tokens",
    "count_text",
    "structured_output",
    "fim_complete",
    "fim_complete_stream",
    "FIMResponse",
    "get_balance",
    "BalanceInfo",
]
