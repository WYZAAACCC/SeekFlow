"""Minimal Agent — role/goal/backstory + .run()."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from deepseek_toolkit.runtime import ToolRuntime


# Model pricing: (input, cached_input, output) CNY per 1M tokens, max_context
PRICING: dict[str, dict] = {
    "deepseek-chat":    {"input": 0.14, "cached_input": 0.014, "output": 0.28, "max_context": 128_000},
    "deepseek-v3":      {"input": 0.28, "cached_input": 0.028, "output": 1.12, "max_context": 128_000},
    "deepseek-v4-pro":  {"input": 1.74, "cached_input": 0.028, "output": 3.48, "max_context": 1_000_000},
    "deepseek-v4-flash": {"input": 0.14, "cached_input": 0.014, "output": 0.28, "max_context": 1_000_000},
    "__default__":      {"input": 1.74, "cached_input": 0.028, "output": 3.48, "max_context": 1_000_000},
}

# Model-specific defaults: DeepSeek recommends different settings per model
MODEL_DEFAULTS: dict[str, dict] = {
    "deepseek-chat":     {"temperature": 0.0, "max_tokens": 4096},
    "deepseek-v3":       {"temperature": 0.0, "max_tokens": 4096},
    "deepseek-v4-pro":   {"temperature": 0.0, "max_tokens": 8192},
    "deepseek-v4-flash": {"temperature": 0.0, "max_tokens": 4096},
    "__default__":       {"temperature": 0.0, "max_tokens": 4096},
}


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
    ):
        self.role = role
        self.goal = goal
        self.backstory = backstory
        self._api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self._thinking = thinking
        self._model = model
        self._mode = mode  # "fast" | "stable"

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
        # DeepSeek V3/V4: put system prompt at END for better results
        self._system_at_end: bool = True
        self._tools: list = []
        self._mcp_servers: list = []
        self._documents_text: str = ""
        self._embedding_fn = None
        self._vector_store = None
        self._runtime: ToolRuntime | None = None
        self._cache_stats: dict = {"total_requests": 0, "total_cached": 0, "total_prompt": 0}  # cached, invalidated on tool changes
        self._runtime_lock: Any = None  # threading.Lock, lazy init
        self._compressor: Any = None  # ContextCompressor, set on first use
        self._max_cost: float = float("inf")  # cost ceiling for guardrails
        self._session_messages: list[dict] = []  # persistent conversation history
        self._api_key_validated: bool = False
        from deepseek_toolkit.cache import CacheSentinel
        self._cache_sentinel = CacheSentinel()
        from deepseek_toolkit.retry import RateLimitState
        self._rate_limit_state = RateLimitState()
        self.memory: Any = None  # AgentMemory, set via enable_memory()

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
        from deepseek_toolkit.mcp.config import MCPServerConfig
        self._mcp_servers.append(
            MCPServerConfig.stdio(name=name, command=command, args=args or [])
        )

    def add_documents(self, docs: list) -> None:
        """Accept Document-like objects (LangChain, CrewAI, dict, str).

        Automatically detects and converts LangChain/CrewAI documents.
        No manual conversion needed — just pass them directly.
        """
        from deepseek_toolkit.compat.documents import to_agent_text
        from deepseek_toolkit.compat.bridge import from_langchain_documents

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
        from deepseek_toolkit.agent.memory import AgentMemory
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
        """Load built-in tools: read_file, web_search, download_page, calculate, save_result."""
        import urllib.request as _ur
        import urllib.parse as _up
        import re as _re
        import html as _html
        from pathlib import Path as _Path

        def read_file(path: str) -> str:
            """Read content from a file path."""
            p = _Path(path)
            if not p.exists():
                return f"ERROR: File not found: {path}"
            try:
                content = p.read_text(encoding="utf-8")
            except Exception:
                content = p.read_bytes().decode("utf-8", errors="replace")
            if len(content) > 8000:
                content = content[:8000] + f"\n...[truncated, {len(content)} total chars]"
            return content

        def web_search(query: str) -> str:
            """Search the web using auto-detected provider. Returns top 5 results."""
            from deepseek_toolkit.search import get_search_provider
            provider = get_search_provider("auto")
            results = provider.search(query, max_results=5)
            return "\n".join(results) if results else "No results."

        def download_page(url: str) -> str:
            """Download and extract text from a web page."""
            try:
                req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with _ur.urlopen(req, timeout=15) as resp:
                    raw = resp.read().decode("utf-8", errors="replace")
                text = _re.sub(r"<script[^>]*>.*?</script>", "", raw, flags=_re.DOTALL)
                text = _re.sub(r"<style[^>]*>.*?</style>", "", text, flags=_re.DOTALL)
                text = _re.sub(r"<[^>]+>", " ", text)
                text = _re.sub(r"\s+", " ", text).strip()
                if len(text) > 8000:
                    text = text[:8000] + "\n...[truncated]"
                return text
            except Exception as e:
                return f"Download failed: {e}"

        def calculate(expression: str) -> str:
            """Evaluate a math expression. e.g. '(8630-3120)/8630'

            Uses AST whitelist for safe evaluation — only arithmetic operators,
            numbers, and allowlisted functions (abs, round, min, max, sum, pow).
            """
            import ast as _ast
            import operator as _operator

            _SAFE_OPS = {
                _ast.Add: _operator.add, _ast.Sub: _operator.sub,
                _ast.Mult: _operator.mul, _ast.Div: _operator.truediv,
                _ast.FloorDiv: _operator.floordiv, _ast.Mod: _operator.mod,
                _ast.Pow: _operator.pow, _ast.USub: _operator.neg,
                _ast.UAdd: _operator.pos,
            }
            _SAFE_FUNCS = {
                "abs": abs, "round": round, "min": min, "max": max,
                "sum": sum, "pow": pow,
            }

            def _eval_node(node):
                if isinstance(node, _ast.Constant):
                    return node.value
                if isinstance(node, _ast.BinOp) and type(node.op) in _SAFE_OPS:
                    left = _eval_node(node.left)
                    right = _eval_node(node.right)
                    return _SAFE_OPS[type(node.op)](left, right)
                if isinstance(node, _ast.UnaryOp) and type(node.op) in _SAFE_OPS:
                    return _SAFE_OPS[type(node.op)](_eval_node(node.operand))
                if isinstance(node, _ast.Call):
                    if isinstance(node.func, _ast.Name) and node.func.id in _SAFE_FUNCS:
                        args = [_eval_node(a) for a in node.args]
                        return _SAFE_FUNCS[node.func.id](*args)
                raise ValueError(f"Unsupported expression: {_ast.unparse(node)}")

            try:
                tree = _ast.parse(expression.strip(), mode="eval")
                result = _eval_node(tree.body)
                return f"Result: {result:.4f}"
            except Exception as e:
                return f"Calculation error: {e}"

        def save_result(filename: str, content: str) -> str:
            """Save content to output directory."""
            out = _Path("output")
            out.mkdir(exist_ok=True)
            (out / filename).write_text(content, encoding="utf-8")
            return f"Saved {len(content)} chars to output/{filename}"

        # Add more builtins
        from deepseek_toolkit.agent.builtins import (
            fetch_url, run_python, parse_csv_str, extract_entities, query_sql, classify_text,
        )
        self.add_tools([read_file, web_search, download_page, calculate, save_result,
                        fetch_url, run_python, parse_csv_str, extract_entities,
                        query_sql, classify_text])

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
        path = os.path.expanduser(f"~/.deepseek_toolkit/sessions/{sid}.json")
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
        path = os.path.expanduser("~/.deepseek_toolkit/sessions/")
        if not os.path.exists(path):
            return []
        return [os.path.splitext(os.path.basename(f))[0]
                for f in glob.glob(os.path.join(path, "*.json"))]

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
        from deepseek_toolkit.fim import fim_complete
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
        """Filter prompt injection patterns from tool outputs."""
        from deepseek_toolkit.tools.executor import _sanitize_tool_output
        return _sanitize_tool_output(text)

    def run_batch(self, tasks: list[str], poll_interval: int = 30,
                  max_wait: int = 86400) -> list[AgentResult]:
        """Submit multiple tasks via DeepSeek Batch API (50% cost saving)."""
        from deepseek_toolkit.batch_client import BatchClient
        from deepseek_toolkit.client import DeepSeekClient

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
            self._runtime = ToolRuntime(
            tools=self._tools,
            api_key=self._api_key,
            max_steps=self._max_steps,
            max_context_tokens=self._max_context_tokens,
            mcp_servers=[s for s in self._mcp_servers],
        )
        if checkpoint_cb:
            self._runtime._step_callback = checkpoint_cb
        return self._runtime

    def _make_messages(self, task: str) -> list[dict]:
        system = self._build_system_prompt()
        if self._documents_text:
            system += f"\n\n## 参考文档\n{self._documents_text}"

        # Sanitize input + cache sentinel (stable mode only)
        if self._mode == "stable":
            task = self._sanitize_input(task)
            msgs = [
                {"role": "system", "content": system},
                {"role": "user", "content": task},
            ]
            advice = self._cache_sentinel.check(msgs)
            if advice.status == "changed":
                import warnings
                warnings.warn(
                    f"DeepSeek prompt cache INVALIDATED. {advice.message} "
                    f"Uncached input costs ¥1.74/M vs ¥0.028/M cached (62x)."
                )
        # Memory retrieval (stable mode only)
        if self._mode == "stable" and self.memory is not None:
            memories = self.memory.recall(task, top_k=3, min_importance=0.3)
            if memories:
                system += "\n\n## 相关记忆\n" + "\n".join(f"- {m}" for m in memories)

        # Vector store retrieval
        if self._vector_store is not None:
            query_vec = task
            if self._embedding_fn is not None:
                query_vec = self._embedding_fn(task)
            try:
                results = self._vector_store.search(query_vec, top_k=5)
                from deepseek_toolkit.compat.documents import to_agent_text
                system += f"\n\n## 向量检索结果\n{to_agent_text(results)}"
            except Exception:
                pass  # vector search failure should not block Agent
        # DeepSeek json_object mode: must include "json" keyword in prompt
        user_task = task
        if self._response_format == "json_object" and "json" not in task.lower():
            user_task = task + "\n\n请以JSON格式输出。"

        if self._system_at_end:
            # DeepSeek V3/V4: system prompt at END for better adherence
            return [
                {"role": "user", "content": user_task},
                {"role": "system", "content": system},
            ]
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_task},
        ]

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
            from deepseek_toolkit.agent.events import get_event_bus, Event
            get_event_bus().emit(Event("agent.start", {"role": self.role, "task": task[:200]}))

        # Balance check
        if self._check_balance and self._api_key:
            from deepseek_toolkit.balance import get_balance
            bal = get_balance(self._api_key)
            if bal.total_balance <= 0:
                from deepseek_toolkit.errors import InsufficientBalanceError
                raise InsufficientBalanceError(
                    f"账户余额不足 (¥{bal.total_balance:.2f})。请充值后重试。"
                    f"充值地址: https://platform.deepseek.com"
                )

        task = task.strip()[:50000]

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
        from deepseek_toolkit.compat.telemetry import agent_span

        rt = self._make_runtime()
        messages = self._make_messages(task)

        # Context compression (stable mode only)
        if self._mode == "stable":
            if self._compressor is None:
                from deepseek_toolkit.compat.compressor import ContextCompressor
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
            from deepseek_toolkit.agent.events import get_event_bus, Event
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
            from deepseek_toolkit.agent.checkpoint import AgentCheckpoint
            cp = AgentCheckpoint(
                thread_id=thread_id,
                step=1,
                messages=messages + [{"role": "assistant", "content": result.final}],
            )
            checkpoint_store.save(cp)

        return self._result_from_runtime(result, None, output_model=output_model)
