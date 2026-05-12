"""Comprehensive runtime data saver — preserves ALL agent execution data.

Captures for every agent run:
  - Full message history (every API call + response)
  - Token usage timeline (per-step breakdown)
  - Tool call timeline (name, args, result, latency per call)
  - Latency breakdown (total, per-API-call, per-tool-execution)
  - Error details (full traceback, framework-specific error type)
  - Framework metadata (version, features available/missing)
  - Raw API responses where available
"""
import json
import sys
import time
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any
from datetime import datetime, timezone

BENCH_DIR = Path(__file__).parent
RUNTIME_DUMP_DIR = BENCH_DIR / "output" / "runtime_dumps"
RUNTIME_DUMP_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class TokenUsageSnapshot:
    """Token usage for a single model call."""
    step: int = 0
    timestamp_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    cost_cny: float = 0.0


@dataclass
class ToolCallSnapshot:
    """A single tool invocation record."""
    step: int
    name: str
    arguments: dict = field(default_factory=dict)
    result: str = ""
    ok: bool = True
    error: str | None = None
    elapsed_ms: float = 0
    repaired: bool = False


@dataclass
class StepSnapshot:
    """Complete record of one agent loop iteration."""
    step: int
    model_call_start_ms: float
    model_call_end_ms: float
    model_call_latency_ms: float
    messages_sent_count: int
    messages_received_count: int
    content: str = ""
    reasoning_content: str = ""
    finish_reason: str = ""
    tool_calls: list[ToolCallSnapshot] = field(default_factory=list)
    token_usage: TokenUsageSnapshot | None = None


@dataclass
class FrameworkFeatures:
    """Which features this framework provides for DeepSeek usage."""
    framework: str
    version: str = ""
    features_available: list[str] = field(default_factory=list)
    features_missing: list[str] = field(default_factory=list)
    deepseek_specific_features: list[str] = field(default_factory=list)


@dataclass
class RuntimeDump:
    """Complete runtime data for a single agent execution."""
    framework: str
    framework_version: str
    agent_type: str
    model: str
    task: str = ""
    system_prompt: str = ""
    started_at: str = ""
    finished_at: str = ""
    total_latency_ms: float = 0
    success: bool = True
    error: str | None = None
    error_type: str | None = None
    steps: list[StepSnapshot] = field(default_factory=list)
    token_usage_total: TokenUsageSnapshot = field(default_factory=TokenUsageSnapshot)
    total_cost_cny: float = 0.0
    final_output: str = ""
    messages: list[dict] = field(default_factory=list)
    features: FrameworkFeatures | None = None
    extra: dict = field(default_factory=dict)


class RuntimeSaver:
    """Collects and persists runtime data during agent execution."""

    def __init__(self, framework: str, agent_type: str, model: str = "deepseek-v4-pro"):
        self.dump = RuntimeDump(
            framework=framework,
            framework_version=self._get_framework_version(framework),
            agent_type=agent_type,
            model=model,
        )
        self._step_start: float = 0
        self._current_step: int = 0
        self._overall_start: float = 0

    @staticmethod
    def _get_framework_version(framework: str) -> str:
        try:
            if framework == "DeepSeekToolkit":
                from deepseek_toolkit import __version__
                return __version__
            elif framework == "LangChain":
                import langchain
                return getattr(langchain, "__version__", "unknown")
            elif framework == "CrewAI":
                import crewai
                return getattr(crewai, "__version__", "unknown")
            elif framework == "OpenAI-Raw":
                import openai
                return getattr(openai, "__version__", "unknown")
        except Exception:
            pass
        return "unknown"

    # ── lifecycle ────────────────────────────────────────────────────────

    def start(self, task: str = "", system_prompt: str = ""):
        self._overall_start = time.time()
        self.dump.started_at = datetime.now(timezone.utc).isoformat()
        self.dump.task = task
        self.dump.system_prompt = system_prompt

    def begin_step(self) -> int:
        self._step_start = time.time()
        self._current_step += 1
        return self._current_step

    def finish(self, final_output: str = "", error: str | None = None,
               error_type: str | None = None, messages: list[dict] | None = None):
        self.dump.total_latency_ms = (time.time() - self._overall_start) * 1000
        self.dump.finished_at = datetime.now(timezone.utc).isoformat()
        self.dump.final_output = final_output
        self.dump.success = error is None
        self.dump.error = error
        self.dump.error_type = error_type
        if messages:
            self.dump.messages = self._sanitize_messages(messages)

    # ── recording ────────────────────────────────────────────────────────

    def record_model_call(self, step: int, messages_count: int,
                          content: str = "", reasoning: str = "",
                          finish_reason: str = "") -> float:
        """Called after model response. Returns elapsed ms."""
        elapsed = (time.time() - self._step_start) * 1000
        snap = StepSnapshot(
            step=step,
            model_call_start_ms=self._step_start * 1000,
            model_call_end_ms=time.time() * 1000,
            model_call_latency_ms=elapsed,
            messages_sent_count=messages_count,
            messages_received_count=messages_count + 1,
            content=content,
            reasoning_content=reasoning,
            finish_reason=finish_reason,
        )
        self.dump.steps.append(snap)
        self._step_start = time.time()  # Reset for next step
        return elapsed

    def record_token_usage(self, step: int, usage: dict, cost_cny: float = 0.0):
        snap = TokenUsageSnapshot(
            step=step,
            timestamp_ms=time.time() * 1000,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            cached_tokens=(usage.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0),
            reasoning_tokens=(usage.get("completion_tokens_details", {}) or {}).get("reasoning_tokens", 0),
            cost_cny=cost_cny,
        )
        self.dump.token_usage_total.prompt_tokens += snap.prompt_tokens
        self.dump.token_usage_total.completion_tokens += snap.completion_tokens
        self.dump.token_usage_total.total_tokens += snap.total_tokens
        self.dump.token_usage_total.cached_tokens += snap.cached_tokens
        self.dump.token_usage_total.reasoning_tokens += snap.reasoning_tokens
        self.dump.total_cost_cny += cost_cny

        if self.dump.steps:
            self.dump.steps[-1].token_usage = snap
        else:
            dummy = StepSnapshot(
                step=step,
                model_call_start_ms=0, model_call_end_ms=0,
                model_call_latency_ms=0,
                messages_sent_count=0, messages_received_count=0,
            )
            dummy.token_usage = snap
            self.dump.steps.append(dummy)

    def record_tool_call(self, step: int, name: str, arguments: dict,
                         result: str, ok: bool = True, error: str | None = None,
                         elapsed_ms: float = 0, repaired: bool = False):
        snap = ToolCallSnapshot(
            step=step, name=name, arguments=arguments,
            result=str(result)[:2000], ok=ok, error=error,
            elapsed_ms=elapsed_ms, repaired=repaired,
        )
        if self.dump.steps:
            self.dump.steps[-1].tool_calls.append(snap)

    def set_features(self, features: FrameworkFeatures):
        self.dump.features = features

    def set_extra(self, key: str, value: Any):
        self.dump.extra[key] = value

    # ── persistence ──────────────────────────────────────────────────────

    def save(self):
        """Save runtime dump to output/runtime_dumps/{framework}/{agent_type}/"""
        out_dir = RUNTIME_DUMP_DIR / self.dump.framework / self.dump.agent_type
        out_dir.mkdir(parents=True, exist_ok=True)

        # Main runtime dump
        path = out_dir / "runtime_dump.json"
        path.write_text(
            json.dumps(self._to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Separate message trace (can be very large)
        msg_path = out_dir / "message_trace.json"
        msg_path.write_text(
            json.dumps(self.dump.messages, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Summary (compact, for quick comparison)
        summary_path = out_dir / "summary.json"
        summary = {
            "framework": self.dump.framework,
            "agent_type": self.dump.agent_type,
            "success": self.dump.success,
            "total_latency_ms": self.dump.total_latency_ms,
            "total_cost_cny": self.dump.total_cost_cny,
            "total_tokens": self.dump.token_usage_total.total_tokens,
            "prompt_tokens": self.dump.token_usage_total.prompt_tokens,
            "completion_tokens": self.dump.token_usage_total.completion_tokens,
            "cached_tokens": self.dump.token_usage_total.cached_tokens,
            "reasoning_tokens": self.dump.token_usage_total.reasoning_tokens,
            "steps": len(self.dump.steps),
            "tool_calls": sum(len(s.tool_calls) for s in self.dump.steps),
            "error": self.dump.error,
            "features_available": self.dump.features.features_available if self.dump.features else [],
            "features_missing": self.dump.features.features_missing if self.dump.features else [],
        }
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return str(out_dir)

    def _to_dict(self) -> dict:
        """Convert to JSON-safe dict, handling dataclasses."""
        def convert(obj):
            if hasattr(obj, '__dataclass_fields__'):
                return {k: convert(v) for k, v in asdict(obj).items()}
            elif isinstance(obj, list):
                return [convert(i) for i in obj]
            elif isinstance(obj, dict):
                return {k: convert(v) for k, v in obj.items()}
            return obj
        return convert(self.dump)

    @staticmethod
    def _sanitize_messages(messages: list[dict]) -> list[dict]:
        """Truncate long message content for storage."""
        cleaned = []
        for m in messages:
            c = dict(m)
            for key in ("content", "reasoning_content", "tool_result"):
                if key in c and isinstance(c[key], str) and len(c[key]) > 2000:
                    c[key] = c[key][:2000] + f"\n... [truncated, total {len(c[key])} chars]"
            cleaned.append(c)
        return cleaned


# ═══════════════════════════════════════════════════════════════════════════════
# DeepSeek-specific feature definitions
# ═══════════════════════════════════════════════════════════════════════════════

DEEPSEEK_SPECIFIC_FEATURES = [
    "thinking_mode_param",     # thinking_mode="enabled"|"disabled"|"max"
    "balance_query",           # get_balance() — check account before running
    "deepseek_pricing_table",  # Built-in CNY pricing for cost tracking
    "error_classification",    # 6 typed errors with Chinese suggestions
    "fim_completions",         # Fill-in-the-Middle via /beta endpoint
    "prompt_cache_observation",# CacheSentinel + extract_cached_tokens
    "rate_limit_awareness",    # Parse X-RateLimit-* headers
    "json_repair",             # Automatic repair of malformed JSON arguments
    "trace_recording",         # TraceRecorder with structured events
    "anthropic_compat",        # Anthropic Messages API → DeepSeek format adapter
    "session_persistence",     # Session.save()/load() conversation state
    "strict_tools",            # check_strict_compatibility() for strict mode
]


def get_framework_features(framework: str) -> FrameworkFeatures:
    """Return the feature matrix for a given framework."""

    if framework == "DeepSeekToolkit":
        return FrameworkFeatures(
            framework="DeepSeekToolkit",
            version="local",
            features_available=[
                "thinking_mode_param", "balance_query", "deepseek_pricing_table",
                "error_classification", "fim_completions", "prompt_cache_observation",
                "rate_limit_awareness", "json_repair", "trace_recording",
                "anthropic_compat", "session_persistence", "strict_tools",
                "streaming", "parallel_execution", "tool_cache",
                "context_management", "truncation_strategy", "structured_output",
                "fallback_chain", "async_runtime", "batch_api",
                "tool_decorator", "cost_tracking", "token_counter",
                "retry_executor", "circuit_breaker",
            ],
            features_missing=[],
            deepseek_specific_features=DEEPSEEK_SPECIFIC_FEATURES,
        )

    elif framework == "LangChain":
        return FrameworkFeatures(
            framework="LangChain",
            version="1.2.18",
            features_available=[
                "streaming", "tool_decorator", "retry_middleware",
                "langgraph_checkpointer", "langgraph_tracing",
                "model_fallback", "summarization",
                "todo_list_middleware", "human_in_the_loop",
                "structured_output", "parallel_tool_calls",
            ],
            features_missing=[
                "balance_query", "deepseek_pricing_table",
                "error_classification", "fim_completions",
                "prompt_cache_observation", "rate_limit_awareness",
                "json_repair", "anthropic_compat",
                "session_persistence", "strict_tools",
                "thinking_mode_param", "truncation_strategy",
            ],
            deepseek_specific_features=[
                # Only via extra_body/manual work
            ],
        )

    elif framework == "CrewAI":
        return FrameworkFeatures(
            framework="CrewAI",
            version="1.14.4",
            features_available=[
                "streaming", "token_tracking", "tool_decorator",
                "crew_orchestration", "task_model",
                "hierarchical_process", "agent_delegation",
                "structured_output", "guardrails",
            ],
            features_missing=[
                "balance_query", "deepseek_pricing_table",
                "error_classification", "fim_completions",
                "prompt_cache_observation", "rate_limit_awareness",
                "json_repair", "anthropic_compat",
                "session_persistence", "strict_tools",
                "thinking_mode_param", "truncation_strategy",
                "retry_executor", "circuit_breaker",
                "parallel_execution", "tool_cache",
                "context_management", "cost_tracking",
                "token_counter", "trace_recording",
            ],
            deepseek_specific_features=[
                # No DeepSeek-specific features
            ],
        )

    else:
        return FrameworkFeatures(
            framework=framework,
            version="unknown",
            features_available=["manual_tool_loop"],
            features_missing=DEEPSEEK_SPECIFIC_FEATURES,
            deepseek_specific_features=[],
        )


def generate_runtime_comparison():
    """Aggregate all runtime dumps into a single comparison file."""
    import glob

    all_summaries = []
    for summary_path in RUNTIME_DUMP_DIR.glob("*/*/summary.json"):
        try:
            all_summaries.append(json.loads(summary_path.read_text(encoding="utf-8")))
        except Exception:
            pass

    if not all_summaries:
        return

    comparison = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_runs": len(all_summaries),
        "by_framework": {},
        "by_agent_type": {},
    }

    for s in all_summaries:
        fw = s["framework"]
        at = s["agent_type"]

        if fw not in comparison["by_framework"]:
            comparison["by_framework"][fw] = []
        comparison["by_framework"][fw].append(s)

        if at not in comparison["by_agent_type"]:
            comparison["by_agent_type"][at] = []
        comparison["by_agent_type"][at].append(s)

    out_path = RUNTIME_DUMP_DIR / "runtime_comparison.json"
    out_path.write_text(
        json.dumps(comparison, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Runtime comparison saved to {out_path}")


if __name__ == "__main__":
    generate_runtime_comparison()
