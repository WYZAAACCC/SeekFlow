"""Tool executor for unified local tool execution."""
from __future__ import annotations


import concurrent.futures
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from seekflow.repair.coercion import coerce_arguments


@dataclass
class ToolAuditRecord:
    """Immutable record of a single tool execution."""

    timestamp: float = 0.0
    tool_name: str = ""
    tool_call_id: str = ""
    args_hash: str = ""
    result_hash: str | None = None
    latency_ms: int = 0
    ok: bool = False
    error: str | None = None
    policy_decision: str = "allowed"
    policy_reason: str = ""
    risk_level: str = "read"
    repair_attempted: bool = False
    repair_confidence: float | None = None
    cache_hit: bool = False
    redactions: int = 0
    run_id: str = ""
    step: int = 0
from seekflow.repair.json_repair import repair_json_arguments
from seekflow.tool_cache import ToolCallCache, make_cache_key
from seekflow.tools.registry import ToolRegistry
from seekflow.truncation import TruncationStrategy, truncate_result
from seekflow.types import ToolCall, ToolExecutionResult

if TYPE_CHECKING:
    pass


DANGEROUS_REPAIR_CONFIDENCE_THRESHOLD = 0.95


class ToolExecutor:
    """Executes tool calls with policy-enforced security gate.

    Execution order: parse → repair → lookup → coerce → policy →
    approval → sandbox → execute → sanitize → truncate → audit.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        repair: bool = True,
        max_result_chars: int = 12000,
        cache: ToolCallCache | None = None,
        truncation_strategy: TruncationStrategy = TruncationStrategy.JSON_AWARE,
        max_parallel: int = 5,
        policy_engine: Any | None = None,
        context: Any | None = None,
        approval_handler: Any | None = None,
        sandbox: Any | None = None,
    ):
        self.registry = registry
        self.repair = repair
        self.max_result_chars = max_result_chars
        self._cache = cache
        self.truncation_strategy = truncation_strategy
        self.max_parallel = max_parallel
        self.policy_engine = policy_engine
        self.context = context
        self.approval_handler = approval_handler
        self.sandbox = sandbox
        self.audit_trail: list[ToolAuditRecord] = []

    def execute(self, tool_call: ToolCall, timeout: float | None = 30.0) -> ToolExecutionResult:
        start = time.time()
        repair_notes: list[str] = []
        repaired = False

        arguments = tool_call.arguments

        # Look up tool first (needed for policy check)
        if not self.registry.has(tool_call.name):
            elapsed = int((time.time() - start) * 1000)
            return ToolExecutionResult(
                tool_call_id=tool_call.id, name=tool_call.name,
                arguments={}, ok=False,
                error=f"Tool not found: {tool_call.name}",
                elapsed_ms=elapsed,
            )
        tool_def = self.registry.get(tool_call.name)
        # Defensive: arguments normalized to dict at API boundary (client.py),
        # but legacy callers may still pass raw strings.
        repair_confidence = 1.0
        repair_level = 0
        if isinstance(arguments, str):
            parsed, ok, notes, conf, level = self._parse_arguments(arguments)
            repair_confidence = conf
            repair_level = level
            repair_notes.extend(notes)
            if ok:
                arguments = parsed
                if notes:
                    repaired = True
            else:
                elapsed = int((time.time() - start) * 1000)
                return ToolExecutionResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    arguments={}, ok=False,
                    error=f"Failed to parse arguments: {arguments}",
                    elapsed_ms=elapsed, repaired=repaired,
                    repair_notes=repair_notes,
                )

        # Dangerous-tool gating: syntactically repaired arguments must have
        # high confidence for tools with write/network/code_exec/destructive risk
        if repaired and repair_level == 1:
            td = self.registry.get(tool_call.name) if self.registry.has(tool_call.name) else None
            if td and td.policy and td.policy.risk in ("write", "network", "code_exec", "destructive"):
                if repair_confidence < DANGEROUS_REPAIR_CONFIDENCE_THRESHOLD:
                    elapsed = int((time.time() - start) * 1000)
                    return ToolExecutionResult(
                        tool_call_id=tool_call.id, name=tool_call.name,
                        arguments={}, ok=False,
                        error=(
                            f"Repaired arguments confidence ({repair_confidence:.2f}) "
                            f"below threshold ({DANGEROUS_REPAIR_CONFIDENCE_THRESHOLD}) for dangerous tool '{tool_call.name}'"
                        ),
                        elapsed_ms=elapsed, repaired=True,
                        repair_notes=repair_notes + ["repair_denied_for_dangerous_tool"],
                    )

        # ── Policy gate: enforce authorization before execution ──────
        policy_decision = "allowed"
        policy_reason = ""
        if self.policy_engine is not None:
            decision = self.policy_engine.authorize(
                tool_def,
                arguments if isinstance(arguments, dict) else {},
                context=self.context,
            )
            if not decision.allowed:
                elapsed = int((time.time() - start) * 1000)
                self._record_audit(
                    tool_def, tool_call.id or "", arguments if isinstance(arguments, dict) else {},
                    result=None, latency_ms=elapsed, ok=False,
                    error=decision.reason,
                    policy_decision="denied", policy_reason=decision.reason,
                    risk=tool_def.policy.risk if tool_def.policy else "destructive",
                )
                return ToolExecutionResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    arguments=arguments if isinstance(arguments, dict) else {},
                    ok=False, error=f"Policy denied: {decision.reason}",
                    elapsed_ms=elapsed,
                )
            if decision.requires_approval:
                if self.approval_handler is not None:
                    from seekflow.execution.approval import ApprovalRequest
                    p = tool_def.policy  # resolve once
                    approval = self.approval_handler.request_approval(ApprovalRequest(
                        tool=tool_def,
                        arguments=arguments if isinstance(arguments, dict) else {},
                        reason=decision.reason,
                        risk=p.risk if p else "destructive",
                        capability=p.capabilities if p else set(),
                        run_id=getattr(self.context, "run_id", None) if self.context else None,
                    ))
                    if not approval.approved:
                        elapsed = int((time.time() - start) * 1000)
                        return ToolExecutionResult(
                            tool_call_id=tool_call.id, name=tool_call.name,
                            arguments=arguments if isinstance(arguments, dict) else {},
                            ok=False, error=f"Approval denied: {approval.reason}",
                            elapsed_ms=elapsed,
                        )
                else:
                    elapsed = int((time.time() - start) * 1000)
                    self._record_audit(
                        tool_def, tool_call.id or "", arguments if isinstance(arguments, dict) else {},
                        result=None, latency_ms=elapsed, ok=False,
                        error="No approval handler configured",
                        policy_decision="approval_required", policy_reason=decision.reason,
                        risk=tool_def.policy.risk if tool_def.policy else "destructive",
                    )
                    return ToolExecutionResult(
                        tool_call_id=tool_call.id, name=tool_call.name,
                        arguments=arguments if isinstance(arguments, dict) else {},
                        ok=False, error=f"Approval required but no handler: {decision.reason}",
                        elapsed_ms=elapsed,
                    )
            policy_decision = "allowed"
            policy_reason = decision.reason
        # ── End policy gate ──────────────────────────────────────────

        # Cache lookup AFTER policy (policy decisions affect cache validity)
        if self._cache is not None:
            cache_enabled = tool_def.metadata.get("cache", True)
            # Only cache read-level tools
            if cache_enabled and (tool_def.policy is None or tool_def.policy.risk == "read"):
                cache_key = make_cache_key(tool_call.name, arguments)
                cached = self._cache.get(cache_key)
                if cached is not None:
                    cached.repair_notes = list(cached.repair_notes) + ["cache_hit"]
                    return cached

        # Coerce argument types
        if self.repair:
            arguments, coercion_notes = coerce_arguments(arguments, tool_def.parameters)
            repair_notes.extend(coercion_notes)
            if coercion_notes:
                repaired = True

        # Execute
        try:
            if tool_def.func is None:
                elapsed = int((time.time() - start) * 1000)
                return ToolExecutionResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    arguments=arguments,
                    ok=False,
                    error=f"Tool '{tool_call.name}' has no callable function",
                    elapsed_ms=elapsed,
                )

            max_retries = (tool_def.metadata or {}).get("max_retries", 0)
            retry_delay = (tool_def.metadata or {}).get("retry_delay", 1.0)
            last_error = None

            effective_timeout = timeout
            if (tool_def.metadata or {}).get("timeout") is not None:
                effective_timeout = tool_def.metadata["timeout"]

            for attempt in range(max_retries + 1):
                try:
                    if effective_timeout and effective_timeout > 0:
                        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                            future = pool.submit(tool_def.func, **arguments)
                            raw_result = future.result(timeout=effective_timeout)
                    else:
                        raw_result = tool_def.func(**arguments)
                    last_error = None
                    break
                except concurrent.futures.TimeoutError:
                    last_error = TimeoutError(
                        f"Tool '{tool_call.name}' timed out after {effective_timeout}s"
                    )
                    break
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        time.sleep(retry_delay * (attempt + 1))

            if last_error is not None:
                elapsed = int((time.time() - start) * 1000)
                return ToolExecutionResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    arguments=arguments if isinstance(arguments, dict) else {},
                    ok=False, error=f"Tool failed after {max_retries+1} attempts: {last_error}",
                    elapsed_ms=elapsed,
                )

            # Wrap untrusted tool output + redact secrets before model sees it
            trusted = (tool_def.metadata or {}).get("trusted", False)
            if not trusted:
                from seekflow.security import wrap_untrusted, redact_secrets
                if isinstance(raw_result, str):
                    content = redact_secrets(raw_result)
                else:
                    content = redact_secrets(
                        json.dumps(raw_result, ensure_ascii=False, default=str)
                    )
                raw_result = wrap_untrusted(tool_call.name, content).format_for_model()

            # Truncate if string result is too long
            keep_fields = tool_def.metadata.get("keep_fields") if tool_def.metadata else None
            final_result = self._maybe_truncate(raw_result, keep_fields=keep_fields)

            elapsed = int((time.time() - start) * 1000)
            exec_result = ToolExecutionResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                arguments=arguments,
                ok=True,
                result=final_result,
                elapsed_ms=elapsed,
                repaired=repaired,
                repair_notes=repair_notes,
            )

            # Write to cache
            if self._cache is not None:
                cache_enabled = tool_def.metadata.get("cache", True)
                if cache_enabled:
                    cache_key = make_cache_key(tool_call.name, arguments)
                    self._cache.put(cache_key, exec_result)

            self._record_audit(
                tool_def, tool_call.id or "", arguments,
                result=str(exec_result.result)[:500] if exec_result.result else None,
                latency_ms=elapsed, ok=exec_result.ok,
                error=exec_result.error,
                policy_decision=policy_decision, policy_reason=policy_reason,
                repair_attempted=repaired, repair_confidence=repair_confidence,
                risk=(tool_def.policy.risk if tool_def.policy else "read"),
            )
            return exec_result
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            return ToolExecutionResult(
                tool_call_id=tool_call.id,
                name=tool_call.name,
                arguments=arguments,
                ok=False,
                error=str(e),
                elapsed_ms=elapsed,
                repaired=repaired,
                repair_notes=repair_notes,
            )

    def _parse_arguments(self, raw: str) -> tuple[dict, bool, list[str], float, int]:
        """Try to parse JSON arguments. Returns (parsed, ok, notes, confidence, level)."""
        # Try direct parse first
        try:
            return json.loads(raw), True, [], 1.0, 0
        except json.JSONDecodeError:
            pass

        # Try repair if enabled
        if self.repair:
            repair_result = repair_json_arguments(raw)
            if repair_result.ok and repair_result.value is not None:
                return (repair_result.value, True, repair_result.applied_rules,
                        repair_result.confidence, repair_result.repair_level)
            return {}, False, repair_result.applied_rules, repair_result.confidence, repair_result.repair_level

        return {}, False, [], 0.0, 3

    def execute_batch(self, tool_calls: list[ToolCall]) -> list[ToolExecutionResult]:
        """Execute multiple tool calls with side-effect awareness.

        Phase 1: all parallel-safe read tools execute concurrently.
        Phase 2: side-effect tools (write/network/code_exec/destructive
        or parallel_safe=False) execute sequentially in original order.
        Results are returned in the same order as the input tool_calls.
        """
        if len(tool_calls) == 0:
            return []
        if len(tool_calls) == 1:
            return [self.execute(tool_calls[0])]

        # Classify: parallel-safe reads vs sequential
        parallel_indices: list[int] = []
        sequential_indices: list[int] = []
        for idx, tc in enumerate(tool_calls):
            td = self.registry.get(tc.name) if self.registry.has(tc.name) else None
            policy = td.policy if td else None
            # No policy → NOT parallel safe, requires explicit policy
            is_parallel_safe = (
                policy.parallel_safe and policy.risk == "read"
            ) if policy is not None else False
            if is_parallel_safe:
                parallel_indices.append(idx)
            else:
                sequential_indices.append(idx)

        ordered: list[ToolExecutionResult | None] = [None] * len(tool_calls)

        # Phase 1: parallel reads
        if parallel_indices:
            max_workers = min(self.max_parallel, len(parallel_indices))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures: dict[concurrent.futures.Future, int] = {}
                for idx in parallel_indices:
                    f = pool.submit(self.execute, tool_calls[idx])
                    futures[f] = idx
                for future in concurrent.futures.as_completed(futures):
                    idx = futures[future]
                    try:
                        ordered[idx] = future.result()
                    except Exception as e:
                        ordered[idx] = ToolExecutionResult(
                            tool_call_id=tool_calls[idx].id,
                            name=tool_calls[idx].name,
                            arguments={}, ok=False,
                            error=f"Parallel execution error: {e}",
                            elapsed_ms=0,
                        )

        # Phase 2: sequential (original order)
        for idx in sequential_indices:
            ordered[idx] = self.execute(tool_calls[idx])

        return [r for r in ordered if r is not None]

    def _record_audit(self, tool_def, call_id: str, args: dict,
                      result: str | None = None, *, latency_ms: int = 0,
                      ok: bool = False, error: str | None = None,
                      policy_decision: str = "allowed", policy_reason: str = "",
                      repair_attempted: bool = False, repair_confidence: float = 1.0,
                      risk: str = "read") -> None:
        """Append an audit record for this tool execution."""
        try:
            args_canonical = json.dumps(args, sort_keys=True, ensure_ascii=False,
                                        separators=(",", ":"), default=str)
        except Exception:
            args_canonical = str(args)
        args_hash = hashlib.sha256(args_canonical.encode()).hexdigest()[:16]
        result_hash = None
        if result is not None:
            result_hash = hashlib.sha256(result.encode()).hexdigest()[:16]

        self.audit_trail.append(ToolAuditRecord(
            timestamp=time.time(),
            tool_name=tool_def.name,
            tool_call_id=call_id,
            args_hash=args_hash,
            result_hash=result_hash,
            latency_ms=latency_ms,
            ok=ok,
            error=error,
            policy_decision=policy_decision,
            policy_reason=policy_reason,
            risk_level=risk,
            repair_attempted=repair_attempted,
            repair_confidence=repair_confidence,
        ))

    def _maybe_truncate(self, result, keep_fields: list[str] | None = None):
        """Truncate string result if too long, using configured strategy."""
        if isinstance(result, str):
            return truncate_result(
                result,
                max_result_chars=self.max_result_chars,
                strategy=self.truncation_strategy,
                keep_fields=keep_fields,
            )
        return result
