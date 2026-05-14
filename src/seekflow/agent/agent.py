"""Minimal Agent — role/goal/backstory + .run()."""
from __future__ import annotations

import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from seekflow.agent.memory import AgentMemory
    from seekflow.compat.compressor import ContextCompressor

from seekflow.runtime import ToolRuntime

_RISK_ORDER = {"read": 0, "network": 1, "write": 2, "code_exec": 3, "destructive": 4}


def _max_of_risk(a: str, b: str) -> str:
    return a if _RISK_ORDER.get(a, 0) >= _RISK_ORDER.get(b, 0) else b


# Model pricing: (input, cached_input, output) CNY per 1M tokens, max_context
PRICING: dict[str, dict] = {
    "deepseek-v4-pro":   {"input": 1.74, "cached_input": 0.028, "output": 3.48, "max_context": 1_000_000},
    "deepseek-v4-flash": {"input": 0.14, "cached_input": 0.014, "output": 0.28, "max_context": 1_000_000},
    # Legacy model names — deprecated, will be removed after 2026-07-24
    "deepseek-chat":     {"input": 0.14, "cached_input": 0.014, "output": 0.28, "max_context": 128_000,
                          "_deprecated": True, "_replacement": "deepseek-v4-flash"},
    "deepseek-v3":       {"input": 0.28, "cached_input": 0.028, "output": 1.12, "max_context": 128_000,
                          "_deprecated": True, "_replacement": "deepseek-v4-pro"},
    "deepseek-reasoner": {"input": 1.74, "cached_input": 0.028, "output": 3.48, "max_context": 1_000_000,
                          "_deprecated": True, "_replacement": "deepseek-v4-pro"},
    "__default__":       {"input": 1.74, "cached_input": 0.028, "output": 3.48, "max_context": 1_000_000},
}

LEGACY_MODEL_MAP: dict[str, str] = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-v3": "deepseek-v4-pro",
    "deepseek-reasoner": "deepseek-v4-pro",
}

# Model-specific defaults
MODEL_DEFAULTS: dict[str, dict] = {
    "deepseek-v4-pro":   {"temperature": 0.0, "max_tokens": 8192},
    "deepseek-v4-flash": {"temperature": 0.0, "max_tokens": 4096},
    # Legacy
    "deepseek-chat":     {"temperature": 0.0, "max_tokens": 4096},
    "deepseek-v3":       {"temperature": 0.0, "max_tokens": 4096},
    "deepseek-reasoner": {"temperature": 0.0, "max_tokens": 8192},
    "__default__":       {"temperature": 0.0, "max_tokens": 4096},
}

# Thinking mode: sampling params that have no effect and should be warned
_THINKING_IGNORED_PARAMS = frozenset({
    "temperature", "top_p", "presence_penalty", "frequency_penalty",
})


def update_pricing(model: str, input_price: float, output_price: float,
                   cached_input: float | None = None, max_context: int | None = None):
    """Update pricing for a model. Use when DeepSeek changes prices."""
    if model not in PRICING:
        PRICING[model] = dict(PRICING["__default__"])
    PRICING[model]["input"] = input_price
    PRICING[model]["output"] = output_price
    if cached_input is not None:
        PRICING[model]["cached_input"] = cached_input
    if max_context is not None:
        PRICING[model]["max_context"] = max_context


@dataclass
class RunDiagnostics:
    """Extended diagnostics for advanced users."""
    context_used: int = 0
    context_total: int = 1
    context_breakdown: dict = field(default_factory=lambda: {
        "system_prompt": 0, "documents": 0, "conversation": 0,
        "tool_results": 0, "reasoning": 0,
    })
    cache_hit: bool = False
    cache_tokens: int = 0
    cache_hit_rate: float = 0.0
    retry_attempts: int = 0
    retry_cost: float = 0.0
    cost_tag: str | None = None
    empty_content_retries: int = 0
    hallucinated_tool_retries: int = 0


@dataclass
class AgentResult:
    """Result of an Agent.run() call.

    Core fields (always populated):
        final_output, tool_calls, tokens, cost, reasoning_content, model

    Advanced diagnostics:
        result.diagnostics.cache_hit_rate
        result.diagnostics.context_breakdown
        result.diagnostics.retry_attempts
    """
    final_output: str = ""
    tool_calls: list = field(default_factory=list)
    tokens: dict = field(default_factory=dict)
    cost: float = 0.0
    reasoning_content: str | None = None
    model: str = ""
    diagnostics: RunDiagnostics = field(default_factory=RunDiagnostics)


class DeepSeekAgent:
    """A lightweight Agent driven by role/goal/backstory.

    Usage:
        agent = DeepSeekAgent(role="分析师", goal="分析数据", backstory="CPA持证人")
        result = agent.run("分析这份数据")
    """

    def __init__(
        self,
        *,
        role: str,
        goal: str,
        backstory: str,
        api_key: str | None = None,
        thinking: bool = True,
        model: str = "deepseek-v4-pro",
        temperature: float = 0.2,
        max_steps: int = 25,
        max_context_tokens: int = 900000,
        response_format: str | None = None,
        parallel_tools: bool = False,
        check_balance: bool = False,
        cost_tag: str | None = None,
        fallback_models: list[str] | None = None,
        mode: str = "stable",
        dangerous_tools: bool = False,
    ):
        self.role = role
        self.goal = goal
        self.backstory = backstory
        self._api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self._thinking = thinking
        self._model = model
        self._mode = mode  # "fast" | "stable"
        self._dangerous_tools = dangerous_tools

        # Capability profile (mutable, populated by allow_* methods)
        self._allowed_capabilities: set[str] = {"read"}
        self._allowed_domains: set[str] = set()
        self._workspace_root: str | None = None
        self._max_risk: str = "read"
        self._sandbox: Any = None

        # Apply model-specific defaults if not explicitly overridden
        md = MODEL_DEFAULTS.get(model, MODEL_DEFAULTS["__default__"])
        self._temperature = temperature  # User override always wins
        self._model_max_tokens = md["max_tokens"]

        self._max_steps = max_steps
        self._max_context_tokens = max_context_tokens
        self._response_format = response_format
        self._check_balance = check_balance
        self._cost_tag = cost_tag
        self._fallback_models = fallback_models or []
        # Cache-first strategy: system prompt FIRST for maximum cache hit rate.
        # DeepSeek caches from byte 0 — system-first shares cache across sessions.
        # system-at-end improves adherence but kills cache (user msg is unique per call).
        # Tradeoff: 10x cheaper input tokens vs minor quality difference.
        self._system_at_end: bool = False
        self._tools: list = []
        self._mcp_servers: list = []
        self._documents_text: str = ""
        self._embedding_fn: Callable[..., Any] | None = None
        self._vector_store: Any = None
        self._runtime: ToolRuntime | None = None
        self._cache_stats: dict[str, int] = {"total_requests": 0, "total_cached": 0, "total_prompt": 0}
        self._runtime_lock: threading.Lock | None = None
        self._compressor: ContextCompressor | None = None
        self._max_cost: float = float("inf")
        self._session_messages: list[dict[str, Any]] = []
        self._api_key_validated: bool = False

        # Deprecation warning for legacy model names
        if model in LEGACY_MODEL_MAP:
            replacement = LEGACY_MODEL_MAP[model]
            import warnings
            warnings.warn(
                f"Model '{model}' is deprecated and will be removed after 2026-07-24. "
                f"Use '{replacement}' instead.",
                FutureWarning, stacklevel=2,
            )

        from seekflow.cache import CacheSentinel, CacheStabilizer
        self._cache_sentinel = CacheSentinel()
        self._cache_stabilizer = CacheStabilizer(warn_on_drift=self._mode == "stable")
        from seekflow.retry import RateLimitState
        self._rate_limit_state = RateLimitState()
        self.memory: AgentMemory | None = None

        # Validate API key format early
        if self._api_key and not self._api_key.startswith("sk-"):
            import warnings
            warnings.warn(f"API key does not start with 'sk-'. This may cause authentication errors.")

    def add_mcp_server(
        self, name: str, command: str, args: list[str] | None = None
    ) -> None:
        """Register an MCP server via stdio transport.

        On Agent.run(), the server process is started and its tools
        become available alongside Python-native tools.
        """
        from seekflow.mcp.config import MCPServerConfig
        self._mcp_servers.append(
            MCPServerConfig.stdio(name=name, command=command, args=args or [])
        )

    def add_documents(self, docs: list) -> None:
        """Accept Document-like objects (LangChain, CrewAI, dict, str).

        Automatically detects and converts LangChain/CrewAI documents.
        No manual conversion needed — just pass them directly.
        """
        from seekflow.compat.documents import to_agent_text
        from seekflow.compat.bridge import from_langchain_documents

        # Auto-detect: try LangChain/CrewAI document conversion
        converted = []
        for doc in docs:
            if hasattr(doc, 'page_content') and hasattr(doc, 'metadata'):
                converted.append(from_langchain_documents([doc])[0] if callable(from_langchain_documents) else doc)
            elif hasattr(doc, 'text') and hasattr(doc, 'metadata'):
                # CrewAI Knowledge format
                converted.append({"page_content": doc.text, "metadata": getattr(doc, 'metadata', {})})
            else:
                converted.append(doc)
        if converted:
            self._documents_text = to_agent_text(converted)

    def use_embedding(self, fn) -> None:
        """Set embedding function for vector search."""
        self._embedding_fn = fn
        # Validate: test call to check dimension
        try:
            test_vec = fn("test")
            if not isinstance(test_vec, list) or len(test_vec) == 0:
                import warnings
                warnings.warn(f"Embedding function returned invalid vector: {type(test_vec)}")
        except Exception as e:
            import warnings
            warnings.warn(f"Embedding function test call failed: {e}")

    def use_vector_store(self, store) -> None:
        """Set vector store for RAG-like retrieval."""
        self._vector_store = store

    def enable_memory(self, short_term_size: int = 10) -> None:
        """Enable Agent memory (short-term + long-term)."""
        from seekflow.agent.memory import AgentMemory
        self.memory = AgentMemory(short_term_size=short_term_size)

    @property
    def tools(self) -> list:
        """Return a copy of the registered tools list (read-only)."""
        return list(self._tools)

    def add_tool(self, tool) -> None:
        """Register a single tool. Duplicates are silently ignored."""
        if tool not in self._tools:
            self._tools.append(tool)

    def add_tools(self, tools: list) -> None:
        """Register multiple tools at once."""
        for t in tools:
            self.add_tool(t)

    def with_default_tools(self) -> None:
        """Load built-in tools.

        By default (``dangerous_tools=False``), only the AST-safe
        ``calculate`` tool is registered.  Set ``dangerous_tools=True``
        on the Agent to load all 11 built-in tools.
        """
        calculate = safe_calculate  # standalone function below
        self.add_tool(calculate)

        if not self._dangerous_tools:
            return

        import warnings
        warnings.warn(
            "dangerous_tools=True enables file read, web fetch, Python exec, "
            "SQL query, and other tools that can access the host filesystem "
            "and network. Only use in trusted/sandboxed environments.",
            UserWarning,
        )

        # Safe builtin tools are registered by allow_filesystem / allow_network
        # / allow_python / allow_sqlite (called before with_default_tools).
        # Legacy text utils added for convenience.
        from seekflow.agent.builtins import (
            parse_csv_str, extract_entities, classify_text,
        )
        self.add_tools([parse_csv_str, extract_entities, classify_text])

    async def run_async(self, task: str, files: list[str] | None = None) -> AgentResult:
        """Async version of run()."""
        import asyncio
        return await asyncio.to_thread(self.run, task, files=files)

    def react(self, task: str, files: list[str] | None = None,
              max_iterations: int = 10) -> AgentResult:
        """Execute task with explicit ReAct (Thought→Action→Observation) loop.

        Each iteration: model outputs Thought + optional Action → execute tool
        → feed Observation back → loop until Final Answer or max_iterations.
        """
        rt = self._make_runtime()
        messages = self._make_messages(task)

        react_prompt = (
            "\n\n使用 ReAct 模式解决问题：\n"
            "Thought: 分析当前状态，决定下一步\n"
            "Action: 如需使用工具，写 tool_name(arg=value)\n"
            "Observation: 工具返回结果\n"
            "...重复 Thought/Action/Observation...\n"
            "Final Answer: 最终回答"
        )
        messages[1]["content"] += react_prompt

        result = rt.chat(
            model=self._model,
            messages=messages,
            files=files,
            thinking_mode=self._thinking_mode(),
            temperature=self._temperature,
            max_steps=max_iterations,
        )
        return self._result_from_runtime(result)

    def plan_solve(self, task: str, files: list[str] | None = None) -> AgentResult:
        """Execute task with Plan→Solve pattern.

        First pass: create step-by-step plan.
        Second pass: execute each step.
        """
        # Phase 1: Plan
        plan_agent = DeepSeekAgent(
            role=self.role + "（规划阶段）",
            goal=f"为以下任务制定详细的执行计划：{task}",
            backstory=self.backstory,
            api_key=self._api_key,
            thinking=self._thinking,
            model=self._model,
            max_steps=1,
        )
        plan_result = plan_agent.run(
            f"请为以下任务制定一个3-5步的执行计划，每步要具体可执行。\n\n任务：{task}"
        )

        # Phase 2: Execute plan
        exec_prompt = (
            f"任务：{task}\n\n"
            f"执行计划：\n{plan_result.final_output}\n\n"
            f"请按计划逐步执行，每完成一步汇报进度。"
        )
        return self.run(exec_prompt, files=files)

    def reflect(self, task: str, files: list[str] | None = None,
                max_refinements: int = 2) -> AgentResult:
        """Execute task with Reflection — self-critique and iterative improvement.

        Generates initial output → self-evaluates → refines → returns final version.
        """
        # First pass
        result = self.run(task, files=files)

        for i in range(max_refinements):
            if not hasattr(self, '_critic_agent'):
                self._critic_agent = DeepSeekAgent(
                    role="质量审核员",
                    goal="审阅输出并给出具体改进建议",
                    backstory="严格的质量审核专家",
                    api_key=self._api_key,
                    thinking=self._thinking,
                    model=self._model,
                    max_steps=1,
                )
            critic_agent = self._critic_agent
            critique = critic_agent.run(
                f"审阅以下输出，给出1-3条具体的改进建议（如果已经很好，说'无需改进'）：\n\n{result.final_output}"
            )

            if "无需改进" in critique.final_output:
                break

            # Refine
            result = self.run(
                f"原任务：{task}\n\n"
                f"改进建议：\n{critique.final_output}\n\n"
                f"请根据建议重新输出改进后的版本。"
            )

        return result

    def chat(self, message: str) -> AgentResult:
        """Multi-turn conversation — appends to persistent session history.

        Unlike run() which starts fresh each call, chat() maintains message
        history across calls. reasoning_content is auto-passed for thinking mode.
        """
        if not self._session_messages:
            self._session_messages = self._make_messages(message)
        else:
            self._session_messages.append({"role": "user", "content": message})
        result = self._make_runtime().chat(
            model=self._model,
            messages=list(self._session_messages),
            thinking_mode=self._thinking_mode(),
            temperature=self._temperature,
        )
        # Append assistant response to history (with reasoning if present)
        assistant_msg = {"role": "assistant", "content": result.final}
        if result.reasoning_contents:
            assistant_msg["reasoning_content"] = result.reasoning_contents[-1]
        self._session_messages.append(assistant_msg)

        # Store in memory for long-term recall
        if self.memory is not None:
            self.memory.add_interaction("user", message)
            self.memory.add_interaction("assistant", result.final[:500])

        return self._result_from_runtime(result)

    def load_session(self, path: str) -> None:
        """Load conversation history from a JSON file."""
        import json
        with open(path, "r", encoding="utf-8") as f:
            self._session_messages = json.load(f)

    def save_session(self, path: str) -> None:
        """Save conversation history to a JSON file."""
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._session_messages, f, ensure_ascii=False, indent=2)

    def fork_session(self, from_turn: int = 0) -> str:
        """Fork a new session from a specific turn. Returns new session ID."""
        import uuid, json, os
        sid = str(uuid.uuid4())[:8]
        msgs = self._session_messages[:from_turn * 2] if from_turn > 0 else []
        path = os.path.expanduser(f"~/.seekflow/sessions/{sid}.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(msgs, f, ensure_ascii=False, indent=2)
        return sid

    def rollback(self, to_turn: int = 0) -> None:
        """Rollback conversation to a specific turn (0 = start)."""
        # 1 system msg + to_turn * 2 (user+assistant per turn)
        self._session_messages = self._session_messages[:1 + to_turn * 2]

    @staticmethod
    def list_sessions() -> list[str]:
        """List saved session IDs."""
        import os, glob
        path = os.path.expanduser("~/.seekflow/sessions/")
        if not os.path.exists(path):
            return []
        return [os.path.splitext(os.path.basename(f))[0]
                for f in glob.glob(os.path.join(path, "*.json"))]

    def allow_filesystem(
        self, *, root: str,
        read: bool = True, write: bool = False,
        allowed_extensions: set[str] | None = None,
        max_file_bytes: int = 5_000_000,
    ) -> "DeepSeekAgent":
        """Enable filesystem capabilities within a workspace root.

        Immediately registers the safe read_file tool bound to *root*.
        Call BEFORE with_default_tools() to avoid order issues.
        """
        self._workspace_root = root
        self._allowed_capabilities.add("filesystem.read")
        if write:
            self._allowed_capabilities.add("filesystem.write")
            self._max_risk = _max_of_risk(self._max_risk, "write")
        self._invalidate_runtime()
        # Register safe factory immediately
        from seekflow.tools.builtins import make_read_file
        self.add_tool(make_read_file(workspace_root=root,
                      allowed_extensions=allowed_extensions,
                      max_file_bytes=max_file_bytes))
        return self

    def allow_network(
        self, *, domains: set[str],
        https_only: bool = True,
        max_response_bytes: int = 1_000_000,
    ) -> "DeepSeekAgent":
        """Enable network fetch for specified domains.

        Immediately registers the safe fetch_url tool bound to *domains*.
        """
        self._allowed_capabilities.add("network.public_http")
        self._allowed_domains.update(domains)
        self._max_risk = _max_of_risk(self._max_risk, "network")
        self._invalidate_runtime()
        from seekflow.tools.builtins import make_fetch_url
        self.add_tool(make_fetch_url(allowed_domains=domains))
        return self

    def allow_python(
        self, *, sandbox, timeout_s: float = 10.0,
    ) -> "DeepSeekAgent":
        """Enable Python code execution with a configured sandbox.

        Immediately registers the safe run_python tool using *sandbox*.
        """
        from seekflow.sandbox import NoSandbox
        if isinstance(sandbox, NoSandbox):
            raise ValueError("Python execution requires a real sandbox, not NoSandbox")
        self._allowed_capabilities.add("code.exec")
        self._sandbox = sandbox
        self._max_risk = _max_of_risk(self._max_risk, "code_exec")
        self._invalidate_runtime()
        from seekflow.tools.builtins import make_python_exec
        self.add_tool(make_python_exec(sandbox=sandbox, timeout_s=timeout_s))
        return self

    def allow_sqlite(
        self, *, root: str, readonly: bool = True,
        max_rows: int = 1000,
    ) -> "DeepSeekAgent":
        """Enable read-only SQLite queries within a workspace root.

        Immediately registers the safe query_sql tool bound to *root*.
        """
        self._allowed_capabilities.add("data.sqlite")
        self._workspace_root = root
        self._invalidate_runtime()
        from seekflow.tools.builtins import make_sqlite_query
        self.add_tool(make_sqlite_query(workspace_root=root, max_rows=max_rows))
        return self

    def _invalidate_runtime(self) -> None:
        """Force next run() to create a fresh ToolRuntime with updated context."""
        self._runtime = None

    def cleanup(self) -> None:
        """Clean up resources: MCP sessions, runtime cache, open connections."""
        rt = getattr(self, '_runtime', None)
        if rt is not None and hasattr(rt, 'cleanup'):
            rt.cleanup()

    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass

    def fill_in_middle(self, prefix: str, suffix: str,
                       temperature: float = 0.0) -> str:
        """Complete code using DeepSeek FIM (Fill-in-the-Middle) API.

        DeepSeek-exclusive beta endpoint. LangChain/CrewAI cannot do this.
        """
        from seekflow.fim import fim_complete
        return fim_complete(
            prefix=prefix, suffix=suffix,
            api_key=self._api_key,
            model=self._model,
            temperature=temperature,
        )

    def prewarm(self) -> bool:
        """Pre-warm the API connection to eliminate cold-start latency.

        Sends a minimal request (max_tokens=1) to initialize the
        httpx connection pool. Results are cached for 300s.
        Returns True if warmup succeeded.
        """
        import time as _time
        if hasattr(self, '_last_warmup') and _time.time() - self._last_warmup < 300:
            return True
        try:
            self._last_warmup = _time.time()
            self.run("ok", execution_timeout=5)
            return True
        except Exception:
            return False

    @staticmethod
    def _sanitize_output(text: str) -> str:
        """Wrap tool output as untrusted data."""
        from seekflow.security import wrap_untrusted
        wrapped = wrap_untrusted("tool", text)
        return wrapped.format_for_model()

    def run_batch(self, tasks: list[str], poll_interval: int = 30,
                  max_wait: int = 86400) -> list[AgentResult]:
        """Submit multiple tasks via DeepSeek Batch API (50% cost saving)."""
        from seekflow.batch_client import BatchClient
        from seekflow.client import DeepSeekClient

        raw_client = DeepSeekClient(api_key=self._api_key)
        client = BatchClient(client=raw_client, poll_interval=poll_interval)

        requests = []
        for i, task in enumerate(tasks):
            messages = self._make_messages(task)
            requests.append({
                "custom_id": f"batch-{i}",
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": self._model,
                    "messages": messages,
                    "temperature": self._temperature,
                },
            })

        batch_id = client.submit_batch(requests)
        _, batch_obj = client.poll_batch(batch_id, max_wait=max_wait)
        outputs = client.download_results(batch_id)

        results = []
        for out in outputs:
            content = ""
            if out.get("response", {}).get("body", {}).get("choices"):
                content = out["response"]["body"]["choices"][0]["message"].get("content", "")
            results.append(AgentResult(
                final_output=content, model=self._model,
                diagnostics=RunDiagnostics(cost_tag=self._cost_tag),
            ))
        return results

    @property
    def cache_stats(self) -> dict:
        """Return accumulated cache statistics across all runs."""
        return dict(self._cache_stats)

    @property
    def rate_limit_status(self) -> dict:
        """Return current DeepSeek rate limit status.

        Proactive — check before running to avoid 429 errors.
        """
        state = self._rate_limit_state
        return {
            "remaining": state.remaining,
            "reset_at": state.reset_at,
            "is_limited": state.is_limited,
            "is_near_limit": state.is_near_limit,
        }

    def _result_from_runtime(self, result, messages=None, model_used: str = "", output_model=None) -> AgentResult:
        """Build AgentResult from ToolRuntimeResult using model pricing."""
        model = model_used or self._model
        tokens = result.usage or {}
        prompt_tokens = tokens.get("prompt_tokens", 0)
        completion_tokens = tokens.get("completion_tokens", 0)
        cached_tokens = (
            (tokens.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0)
        )
        pricing = PRICING.get(model, PRICING["__default__"])
        cost = (
            max(prompt_tokens - cached_tokens, 0) * pricing["input"] / 1_000_000
            + cached_tokens * pricing["cached_input"] / 1_000_000
            + completion_tokens * pricing["output"] / 1_000_000
        )
        context_used = prompt_tokens + completion_tokens
        cache_hit_rate = cached_tokens / max(prompt_tokens, 1)
        ar = AgentResult(
            final_output=result.final,
            tool_calls=[
                {"name": tr.name, "ok": tr.ok, "result": str(tr.result)[:200]}
                for tr in result.tool_results
            ],
            tokens=tokens,
            cost=cost,
            reasoning_content=(
                result.reasoning_contents[-1]
                if result.reasoning_contents
                else None
            ),
            model=model,
            diagnostics=RunDiagnostics(
                context_used=context_used,
                context_total=self._max_context_tokens,
                context_breakdown=self._compute_breakdown(messages, result),
                cost_tag=self._cost_tag,
                cache_hit=cached_tokens > 0,
                cache_tokens=cached_tokens,
                cache_hit_rate=round(cache_hit_rate, 4),
                retry_attempts=getattr(result, 'retry_count', 0),
                retry_cost=0.0,
                empty_content_retries=getattr(result, 'empty_content_retries', 0),
                hallucinated_tool_retries=getattr(result, 'hallucinated_tool_retries', 0),
            ),
        )

        if output_model is not None and hasattr(output_model, 'model_validate_json'):
            try:
                validated = output_model.model_validate_json(result.final)
                ar.final_output = str(validated)
            except Exception:
                pass

        return ar

    def _build_system_prompt(self) -> str:
        return (
            f"你是{self.role}。\n"
            f"目标：{self.goal}\n"
            f"背景：{self.backstory}"
        )

    def _make_runtime(self, checkpoint_cb=None) -> ToolRuntime:
        import threading
        if self._runtime_lock is None:
            self._runtime_lock = threading.Lock()
        with self._runtime_lock:
            registered_names = {td.name for td in self._runtime._registry.list()} if self._runtime else set()
            need_names = {getattr(t, 'name', getattr(t, '__name__', '')) for t in self._tools}
            if self._runtime is not None and registered_names == need_names:
                if checkpoint_cb:
                    self._runtime._step_callback = checkpoint_cb
                return self._runtime
            from seekflow.policy import PolicyEngine
            from seekflow.execution.context import ToolExecutionContext

            ctx = ToolExecutionContext(
                run_id=getattr(self, '_cost_tag', '') or 'agent',
                dangerous_tools_enabled=self._dangerous_tools,
                allowed_capabilities=self._allowed_capabilities,
                max_risk=self._max_risk,
                workspace_root=(
                    self._workspace_root if self._workspace_root else None
                ),
                allowed_domains=self._allowed_domains,
                sandbox=self._sandbox,
            )

            self._runtime = ToolRuntime(
                tools=self._tools,
                api_key=self._api_key,
                max_steps=self._max_steps,
                max_context_tokens=self._max_context_tokens,
                mcp_servers=[s for s in self._mcp_servers],
                policy_engine=PolicyEngine(),
                policy_context=ctx,
            )
        # FREEZE the cacheable prefix now that tools are finalized
        if self._mode == "stable":
            tools_schema = self._runtime._registry.to_deepseek_tools()
            self._cache_stabilizer.freeze(
                self._build_system_prompt(),
                tool_schemas=tools_schema,
            )
        if checkpoint_cb:
            self._runtime._step_callback = checkpoint_cb
        return self._runtime

    def _make_messages(self, task: str) -> list[dict]:
        # Static system prompt — NEVER append dynamic content here!
        # Dynamic content (docs, memories, vectors) goes as separate messages
        # to preserve the byte-stable cache prefix.
        system = self._build_system_prompt()

        # Sanitize input (stable mode only)
        if self._mode == "stable":
            task = self._sanitize_input(task)

        # Build dynamic context as separate messages (not merged into system)
        dynamic_msgs: list[dict] = []

        if self._documents_text:
            dynamic_msgs.append({
                "role": "user",
                "content": f"[Reference Documents]\n{self._documents_text[:8000]}",
            })

        # Memory retrieval (stable mode only)
        if self._mode == "stable" and self.memory is not None:
            memories = self.memory.recall(task, top_k=3, min_importance=0.3)
            if memories:
                dynamic_msgs.append({
                    "role": "user",
                    "content": "[Relevant Memories]\n" + "\n".join(f"- {m}" for m in memories),
                })

        # Vector store retrieval
        if self._vector_store is not None:
            query_vec = task
            if self._embedding_fn is not None:
                query_vec = self._embedding_fn(task)
            try:
                results = self._vector_store.search(query_vec, top_k=5)
                from seekflow.compat.documents import to_agent_text
                dynamic_msgs.append({
                    "role": "user",
                    "content": f"[Vector Search Results]\n{to_agent_text(results)[:8000]}",
                })
            except Exception:
                pass

        # DeepSeek json_object mode
        user_task = task
        if self._response_format == "json_object" and "json" not in task.lower():
            user_task = task + "\n\n请以JSON格式输出。"

        # Build message list — get the cache-stabilized system prompt first
        if self._system_at_end:
            msgs = [{"role": "user", "content": user_task}]
            msgs.extend(dynamic_msgs)
            msgs.append({"role": "system", "content": system})
        else:
            msgs = [{"role": "system", "content": system}]
            msgs.extend(dynamic_msgs)
            msgs.append({"role": "user", "content": user_task})

        # Cache stability check (stable mode only)
        if self._mode == "stable":
            msgs = self._cache_stabilizer.ensure_stable_prefix(msgs)
            advice = self._cache_sentinel.check(msgs)
            if advice.status == "changed":
                import warnings
                warnings.warn(
                    f"DeepSeek prompt cache INVALIDATED. {advice.message} "
                    f"Uncached input costs ¥1.74/M vs ¥0.028/M cached (62x)."
                )

        return msgs

    def _thinking_mode(self) -> str:
        return "enabled" if self._thinking else "disabled"

    @staticmethod
    def _sanitize_input(text: str) -> str:
        """Basic input sanitization: strip PII patterns."""
        import re
        # Mask credit card numbers
        text = re.sub(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b', '[CREDIT_CARD]', text)
        # Mask Chinese ID numbers (18 digits)
        text = re.sub(r'\b\d{6}(19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]\b', '[ID_NUMBER]', text)
        return text

    @staticmethod
    def _compute_breakdown(messages, result) -> dict:
        """Estimate token breakdown by category."""
        bd = {"system_prompt": 0, "documents": 0, "conversation": 0,
              "tool_results": 0, "reasoning": 0}
        if not messages:
            return bd
        for m in messages:
            content = str(m.get("content", ""))
            estimated = len(content) // 4
            role = m.get("role", "")
            if role == "system":
                # Split: first part is system prompt, rest is documents
                parts = content.split("## 参考文档", 1)
                bd["system_prompt"] += len(parts[0]) // 4
                if len(parts) > 1:
                    bd["documents"] += len(parts[1]) // 4
            elif role == "tool":
                bd["tool_results"] += estimated
            elif role in ("user", "assistant"):
                bd["conversation"] += estimated
            if m.get("reasoning_content"):
                bd["reasoning"] += len(str(m["reasoning_content"])) // 4
        return bd

    @staticmethod
    def _filter_output(text: str) -> str:
        """Basic output filtering."""
        # Truncate extremely long outputs
        if len(text) > 100000:
            text = text[:100000] + "\n...[output truncated]"
        return text

    def stream(self, task: str, files: list[str] | None = None):
        """Execute a task and stream events in real time.

        Yields StreamEvent objects: content, reasoning, tool_call_start,
        tool_call_result, done. Use this for real-time UI updates.
        """
        rt = self._make_runtime()
        messages = self._make_messages(task)
        kwargs = {}
        if self._response_format:
            kwargs["response_format"] = self._response_format
        yield from rt.chat_stream(
            model=self._model,
            messages=messages,
            files=files,
            thinking_mode=self._thinking_mode(),
            temperature=self._temperature,
            **kwargs,
        )

    def run(self, task: str, files: list[str] | None = None,
            checkpoint_store: Any = None, thread_id: str = "",
            max_cost: float | None = None,
            execution_timeout: float | None = None,
            output_model: Any = None) -> AgentResult:
        """Execute a task and return structured results.

        Args:
            task: Task description in natural language.
            files: Optional file paths to attach.
            checkpoint_store: Optional CheckpointStore for save/resume.
            thread_id: Optional thread ID for checkpoint keying.
            max_cost: Optional cost ceiling in CNY (guardrail).
            execution_timeout: Optional max execution time in seconds.
            output_model: Optional Pydantic BaseModel for output validation.
        """
        # Event: agent.start (stable mode only)
        if self._mode == "stable":
            from seekflow.agent.events import get_event_bus, Event
            get_event_bus().emit(Event("agent.start", {"role": self.role, "task": task[:200]}))

        # Balance check
        if self._check_balance and self._api_key:
            from seekflow.balance import get_balance
            bal = get_balance(self._api_key)
            if bal.total_balance <= 0:
                from seekflow.errors import InsufficientBalanceError
                raise InsufficientBalanceError(
                    f"账户余额不足 (¥{bal.total_balance:.2f})。请充值后重试。"
                    f"充值地址: https://platform.deepseek.com"
                )

        task = task.strip()[:50000]

        # Adaptive max_steps: scale with task complexity.
        # Short tasks get fewer steps, complex multi-tool tasks get more.
        task_chars = len(task)
        tool_count = len(self._tools)
        estimated_steps = max(3, min(task_chars // 1500 + tool_count // 5, 8))
        if self._max_steps < estimated_steps:
            self._max_steps = estimated_steps

        # Execution timeout via ThreadPoolExecutor (clean, no recursion)
        if execution_timeout and execution_timeout > 0:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    self._run_impl, task, files,
                    checkpoint_store=checkpoint_store, thread_id=thread_id,
                    max_cost=max_cost, output_model=output_model,
                )
                try:
                    return future.result(timeout=execution_timeout)
                except concurrent.futures.TimeoutError:
                    return AgentResult(
                        final_output=f"[EXECUTION TIMEOUT] Task exceeded {execution_timeout}s limit.",
                        cost=0.0,
                    )

        return self._run_impl(task, files,
                              checkpoint_store=checkpoint_store,
                              thread_id=thread_id,
                              max_cost=max_cost,
                              output_model=output_model)

    def _run_impl(self, task: str, files: list[str] | None = None,
                  checkpoint_store: Any = None, thread_id: str = "",
                  max_cost: float | None = None,
                  output_model: Any = None) -> AgentResult:
        """Core execution logic — separated from run() for clean timeout wrapping."""
        from seekflow.compat.telemetry import agent_span

        rt = self._make_runtime()
        messages = self._make_messages(task)

        # Context compression (stable mode only)
        if self._mode == "stable":
            if self._compressor is None:
                from seekflow.compat.compressor import ContextCompressor
                self._compressor = ContextCompressor(max_tokens=self._max_context_tokens)
            if self._compressor.should_compress(messages):
                messages = self._compressor.compress(messages)

        kwargs = {}
        if self._response_format:
            kwargs["response_format"] = self._response_format

        models_to_try = [self._model] + self._fallback_models
        last_error = None
        actual_model = self._model
        for model_name in models_to_try:
            try:
                if self._mode == "stable":
                    with agent_span(self.role, task):
                        result = rt.chat(
                            model=model_name,
                            messages=messages,
                            files=files,
                            thinking_mode=self._thinking_mode(),
                            temperature=self._temperature,
                            **kwargs,
                        )
                else:
                    result = rt.chat(
                        model=model_name,
                        messages=messages,
                        files=files,
                        thinking_mode=self._thinking_mode(),
                        temperature=self._temperature,
                        **kwargs,
                    )
                actual_model = model_name
                last_error = None
                break
            except Exception as e:
                last_error = e
        if last_error:
            raise last_error

        # Memory: store interaction (stable mode only)
        if self._mode == "stable" and self.memory is not None:
            self.memory.add_interaction("user", task)
            self.memory.add_interaction("assistant", result.final[:500])

        # Accumulate cache stats
        usage = result.usage if isinstance(result.usage, dict) else {}
        cached = (usage.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0)
        prompt = usage.get("prompt_tokens", 0)
        self._cache_stats["total_requests"] += 1
        self._cache_stats["total_cached"] += cached
        self._cache_stats["total_prompt"] += prompt

        # Event: agent.end (stable mode only)
        if self._mode == "stable":
            from seekflow.agent.events import get_event_bus, Event
            get_event_bus().emit(Event("agent.end", {"role": self.role, "cost": 0.0}))

        # Guardrail: cost check
        result_cost = self._result_from_runtime(result, messages, actual_model, output_model)
        if self._mode == "stable":
            get_event_bus().emit(Event("agent.end", {"role": self.role, "cost": result_cost.cost}))
        cost_limit = max_cost if max_cost is not None else self._max_cost
        if result_cost.cost > cost_limit > 0:
            return AgentResult(
                final_output=f"[COST LIMIT EXCEEDED] Task cost CNY {result_cost.cost:.6f} exceeds limit CNY {cost_limit:.6f}. "
                             f"Tokens: {result_cost.tokens.get('total_tokens', 0)}. Consider reducing task scope.",
                cost=result_cost.cost,
                tokens=result_cost.tokens,
            )

        # Save checkpoint if store is provided
        if checkpoint_store and thread_id:
            from seekflow.agent.checkpoint import AgentCheckpoint
            cp = AgentCheckpoint(
                thread_id=thread_id,
                step=1,
                messages=messages + [{"role": "assistant", "content": result.final}],
            )
            checkpoint_store.save(cp)

        return self._result_from_runtime(result, None, output_model=output_model)


# ── Standalone safe calculator (extracted for testability) ──────────

def safe_calculate(expression: str) -> str:
    """Evaluate a math expression using AST whitelist.

    Only arithmetic operators (+, -, *, /, //, %, **, unary +/-) and
    allowlisted functions (abs, round, min, max, sum, pow) are permitted.
    All other constructs — attribute access, imports, comprehensions,
    lambdas, assignments — are rejected at the AST level.

    Returns "Result: {value:.4f}" on success, "Calculation error: {details}" on failure.
    """
    import ast
    import operator

    _SAFE_OPS: dict[type, Any] = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.USub: operator.neg,
        ast.UAdd: operator.pos,
    }
    _SAFE_FUNCS: dict[str, Any] = {
        "abs": abs, "round": round, "min": min, "max": max,
        "sum": sum, "pow": pow,
    }

    def _eval(node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.List):
            return [_eval(e) for e in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(_eval(e) for e in node.elts)
        if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
            return _SAFE_OPS[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_OPS:
            return _SAFE_OPS[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _SAFE_FUNCS:
                return _SAFE_FUNCS[node.func.id](*map(_eval, node.args))
        raise ValueError(f"Unsupported expression: {ast.unparse(node)}")

    try:
        tree = ast.parse(expression.strip(), mode="eval")
        result = _eval(tree.body)
        return f"Result: {result:.4f}"
    except Exception as e:
        return f"Calculation error: {e}"
