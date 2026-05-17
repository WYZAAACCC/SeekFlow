"""Tool executor for unified local tool execution."""
from __future__ import annotations


import concurrent.futures
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from seekflow.audit.store import AuditStoreError
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
    runner_name: str = ""
from seekflow.repair.json_repair import repair_json_arguments
from seekflow.tool_cache import ToolCallCache, make_cache_key
from seekflow.tools.registry import ToolRegistry
from seekflow.truncation import TruncationStrategy, truncate_result
from seekflow.types import ToolCall, ToolExecutionResult

if TYPE_CHECKING:
    pass


DANGEROUS_REPAIR_CONFIDENCE_THRESHOLD = 0.95


def _cache_allowed(tool_def) -> bool:
    """Cache only read tools, or idempotent network with explicit opt-in."""
    policy = tool_def.policy
    if policy is None:
        return False
    if not tool_def.metadata.get("cache", True):
        return False
    if policy.risk == "read":
        return True
    if policy.risk == "network" and policy.idempotent and tool_def.metadata.get("cache_network", False):
        return True
    return False


class RunnerUnavailableError(RuntimeError):
    """Raised when a required runner cannot be provided (e.g. container without sandbox)."""

_PICKLE_ERROR_SIGNATURES = (
    "Can't get local object",
    "Can't pickle",
    "cannot pickle",
    "PicklingError",
    "AttributeError",
)


def _is_pickle_error(error: str | None) -> bool:
    """Return True if *error* is a pickle/serialization failure."""
    if not error:
        return False
    return any(sig in error for sig in _PICKLE_ERROR_SIGNATURES)


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
        allow_unsafe_no_policy_execution: bool = False,
        secret_broker: Any | None = None,
        audit_store: Any | None = None,
        egress_sidecar: Any | None = None,
        mcp_gateway_registry: Any | None = None,
        audit_required: bool = False,
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
        self.allow_unsafe_no_policy_execution = allow_unsafe_no_policy_execution
        self.secret_broker = secret_broker
        self.audit_store = audit_store
        self.egress_sidecar = egress_sidecar
        self.mcp_gateway_registry = mcp_gateway_registry
        self.audit_required = audit_required
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

        # ── No-policy gate: deny tools without ToolPolicy ──────
        if tool_def.policy is None:
            if not self.allow_unsafe_no_policy_execution:
                elapsed = int((time.time() - start) * 1000)
                return ToolExecutionResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    arguments=arguments if isinstance(arguments, dict) else {},
                    ok=False,
                    error="ToolPolicy required for execution. Set a ToolPolicy on the tool, "
                          "or use allow_unsafe_no_policy_execution=True (not Level 2 compliant).",
                    elapsed_ms=elapsed,
                )
            import warnings
            warnings.warn(
                "allow_unsafe_no_policy_execution=True disables semi-production safety guarantees",
                RuntimeWarning,
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

        # Input size limit (PR-6: enforced before any heavy work)
        if tool_def.policy is not None:
            from seekflow.tools.limits import enforce_input_limit
            try:
                enforce_input_limit(arguments, tool_def.policy.max_input_bytes)
            except Exception as e:
                elapsed = int((time.time() - start) * 1000)
                return ToolExecutionResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    arguments=arguments if isinstance(arguments, dict) else {},
                    ok=False, error=str(e),
                    elapsed_ms=elapsed,
                )

        # Coerce argument types
        if self.repair:
            arguments, coercion_notes = coerce_arguments(arguments, tool_def.parameters)
            repair_notes.extend(coercion_notes)
            if coercion_notes:
                repaired = True

        # Schema validate — deny execution if args don't match schema
        if tool_def.parameters:
            from seekflow.tools.validation import validate_tool_arguments
            issues = validate_tool_arguments(tool_def.parameters, arguments)
            if issues:
                elapsed = int((time.time() - start) * 1000)
                joined = "; ".join(f"{i.path}: {i.message}" for i in issues[:3])
                self._record_audit(
                    tool_def, tool_call.id or "", arguments,
                    result=None, latency_ms=elapsed, ok=False,
                    error=f"Schema validation: {joined}",
                    policy_decision=policy_decision, policy_reason="schema_invalid",
                    risk=tool_def.policy.risk if tool_def.policy else "read",
                )
                return ToolExecutionResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    arguments=arguments, ok=False,
                    error=f"Argument validation failed: {joined}",
                    elapsed_ms=elapsed, repaired=repaired,
                    repair_notes=repair_notes + ["schema_validation_failed"],
                )

        # Cache lookup AFTER schema validation + policy (no bypass)
        if self._cache is not None and _cache_allowed(tool_def):
            cache_key = make_cache_key(tool_call.name, arguments)
            cached = self._cache.get(cache_key)
            if cached is not None:
                cached.repair_notes = list(cached.repair_notes) + ["cache_hit"]
                return cached

        # Execute via runner (NEVER call tool_def.func directly)
        try:
            raw_max_retries = (tool_def.metadata or {}).get("max_retries", 0)
            retry_delay = (tool_def.metadata or {}).get("retry_delay", 1.0)

            # PR-7: only read tools and explicitly idempotent tools may retry
            policy = tool_def.policy
            if policy is not None and policy.risk == "read":
                max_retries = raw_max_retries
            elif policy is not None and policy.idempotent:
                max_retries = raw_max_retries
            elif policy is None:
                max_retries = raw_max_retries  # no policy → caller's responsibility
            else:
                max_retries = 0  # write/network/destructive: no retry without idempotent

            last_error = None
            fallback_used = False

            effective_timeout = timeout
            if (tool_def.metadata or {}).get("timeout") is not None:
                effective_timeout = tool_def.metadata["timeout"]

            # Plan: select runner based on risk/capabilities/trust
            from seekflow.tools.planner import plan_execution
            plan = plan_execution(tool_def, effective_timeout)

            # PR-2: container fail-closed
            try:
                runner = self._runner_for(plan, tool_def)
            except RunnerUnavailableError as e:
                elapsed = int((time.time() - start) * 1000)
                self._record_audit(
                    tool_def, tool_call.id or "", arguments,
                    result=None, latency_ms=elapsed, ok=False,
                    error=str(e),
                    policy_decision=policy_decision, policy_reason=policy_reason,
                    risk=policy.risk if policy else "destructive",
                    runner_name=plan.runner,
                )
                return ToolExecutionResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    arguments=arguments if isinstance(arguments, dict) else {},
                    ok=False, error=f"Runner unavailable: {e}",
                    elapsed_ms=elapsed,
                )

            # Lv3 gate: func=None is valid for external_container and mcp_gateway.
            # Local tools (in_process/process/container) still require a callable.
            if plan.runner not in {"external_container", "mcp_gateway"} and tool_def.func is None:
                elapsed = int((time.time() - start) * 1000)
                return ToolExecutionResult(
                    tool_call_id=tool_call.id,
                    name=tool_call.name,
                    arguments=arguments,
                    ok=False,
                    error=f"Tool '{tool_call.name}' has no callable function",
                    elapsed_ms=elapsed,
                )

            run_result = None
            for attempt in range(max_retries + 1):
                try:
                    if plan.runner == "external_container":
                        # External tools: pass manifest from metadata, not Python func
                        manifest_data = (tool_def.metadata or {}).get("_manifest_data")
                        if manifest_data is None:
                            raise RunnerUnavailableError(
                                "External tool requires _manifest_data in metadata"
                            )
                        from seekflow.tools.manifest import ToolManifest
                        from seekflow.secrets.types import SecretRef
                        manifest = ToolManifest.model_validate(manifest_data)

                        # Resolve secrets via SecretBroker if configured
                        secret_env: dict[str, str] = {}
                        secret_ref_names: list[str] = []
                        run_id = getattr(self.context, "run_id", "") if self.context else ""
                        if self.secret_broker and manifest.env.secrets:
                            refs = [
                                SecretRef(name=s, scope="tool")
                                for s in manifest.env.secrets
                            ]
                            secret_env = self.secret_broker.resolve_for_tool(
                                manifest.name, refs, run_id=run_id,
                            )
                            # Collect secret ref names for audit (never the values)
                            secret_ref_names = [s for s in manifest.env.secrets]

                        run_result = runner.run(
                            manifest, arguments, plan.timeout_s,
                            max_output_bytes=policy.max_output_bytes if policy else 100_000,
                            env_profile=secret_env,
                            run_id=run_id,
                        )
                        # Inject secret_refs into run_result for audit data flow
                        if secret_ref_names:
                            run_result.secret_refs = list(run_result.secret_refs) + secret_ref_names
                    elif plan.runner == "mcp_gateway":
                        # MCP gateway tools: pass tool_def (func=None is expected)
                        run_result = runner.run(
                            tool_def, arguments, plan.timeout_s,
                            max_output_bytes=policy.max_output_bytes if policy else 100_000,
                        )
                    else:
                        run_result = runner.run(
                            tool_def.func, arguments, plan.timeout_s,
                            max_output_bytes=policy.max_output_bytes if policy else 100_000,
                        )
                    last_error = None
                    break
                except Exception as e:
                    last_error = e
                    # PR-3: pickle fallback — only with explicit opt-in
                    if _is_pickle_error(str(e)):
                        allow_fallback = (
                            policy is not None
                            and policy.risk == "read"
                            and policy.trusted is True
                            and policy.allow_in_process_fallback is True
                            and plan.runner != "in_process"
                        )
                        if allow_fallback:
                            from seekflow.tools.runners import InProcessRunner
                            fallback = InProcessRunner()
                            try:
                                run_result = fallback.run(
                                    tool_def.func, arguments, plan.timeout_s,
                                    max_output_bytes=policy.max_output_bytes if policy else 100_000,
                                )
                                last_error = None
                                fallback_used = True
                                break
                            except Exception as fe:
                                last_error = fe
                        else:
                            last_error = RuntimeError(
                                "Tool is not pickleable and cannot run in ProcessRunner. "
                                "Use a module-level function, or explicitly set "
                                "ToolPolicy(trusted=True, allow_in_process_fallback=True) "
                                "for trusted local-only tools."
                            )
                            break
                    if attempt < max_retries:
                        time.sleep(retry_delay * (attempt + 1))

            if last_error is not None or run_result is None:
                elapsed = int((time.time() - start) * 1000)
                err_msg = f"Tool failed after {max_retries+1} attempts: {last_error}" if last_error else "Tool runner returned no result"
                return ToolExecutionResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    arguments=arguments if isinstance(arguments, dict) else {},
                    ok=False, error=err_msg,
                    elapsed_ms=elapsed,
                )

            # Handle runner-level failure
            if not run_result.ok:
                elapsed = int((time.time() - start) * 1000)
                error_msg = run_result.error or "Tool execution failed"
                if run_result.killed:
                    error_msg = f"Tool killed: {error_msg}"
                self._record_audit(
                    tool_def, tool_call.id or "", arguments,
                    result=None, latency_ms=elapsed, ok=False,
                    error=error_msg,
                    policy_decision=policy_decision, policy_reason=policy_reason,
                    risk=tool_def.policy.risk if tool_def.policy else "read",
                    runner_name=run_result.runner_name,
                    egress_entries=getattr(run_result, "egress_entries", None) if run_result else None,
                    secret_refs=getattr(run_result, "secret_refs", None) if run_result else None,
                )
                return ToolExecutionResult(
                    tool_call_id=tool_call.id, name=tool_call.name,
                    arguments=arguments if isinstance(arguments, dict) else {},
                    ok=False, error=error_msg,
                    elapsed_ms=elapsed,
                )

            raw_result = run_result.result

            # Record output truncation from runner
            if run_result.output_truncated:
                repair_notes.append("output_truncated_by_max_bytes")

            # Wrap untrusted tool output + redact secrets before model sees it
            policy = tool_def.policy
            trusted_output = bool(policy and policy.trusted_output)

            # Emit deprecation warning if old metadata.trusted path is used
            if not trusted_output and (tool_def.metadata or {}).get("trusted", False):
                import warnings
                warnings.warn(
                    "metadata.trusted is deprecated for output wrapping. "
                    "Use ToolPolicy(trusted_output=True) instead.",
                    DeprecationWarning,
                    stacklevel=2,
                )

            if not trusted_output:
                from seekflow.security import wrap_untrusted, redact_secrets
                if isinstance(raw_result, str):
                    content = redact_secrets(raw_result)
                else:
                    content = redact_secrets(
                        json.dumps(raw_result, ensure_ascii=False, default=str)
                    )
                raw_result = wrap_untrusted(tool_call.name, content).format_for_model()
            else:
                # trusted output: still redact secrets by default
                from seekflow.security import redact_secrets
                if isinstance(raw_result, str):
                    raw_result = redact_secrets(raw_result)

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
            if self._cache is not None and _cache_allowed(tool_def):
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
                runner_name=run_result.runner_name,
                egress_entries=getattr(run_result, "egress_entries", None) if run_result else None,
                secret_refs=getattr(run_result, "secret_refs", None) if run_result else None,
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

    def _runner_for(self, plan, tool_def=None):
        """Resolve an ExecutionPlan to a runner instance.

        "container" plans REQUIRE a real ContainerSandbox — no silent fallback.
        code_exec/destructive tools without a container sandbox are DENIED.
        ContainerRunner also requires the tool to have
        ToolPolicy(trusted=True, container_codegen_trusted=True).
        """
        from seekflow.tools.runners import InProcessRunner, ProcessRunner

        if plan.runner == "in_process":
            return InProcessRunner()

        if plan.runner == "process":
            return ProcessRunner()

        if plan.runner == "container":
            if self.sandbox is None:
                raise RunnerUnavailableError(
                    "Container runner required for code_exec/destructive tool, "
                    "but no sandbox is configured."
                )
            sandbox_name = getattr(self.sandbox, "name", "")
            if sandbox_name != "container":
                raise RunnerUnavailableError(
                    f"Container runner required, but sandbox is '{sandbox_name}'. "
                    "Configure a ContainerSandbox for code_exec/destructive tools."
                )
            # ContainerRunner only accepts trusted code-generation tools.
            # The tool function runs in-process to produce a CodeExecutionRequest;
            # arbitrary tool functions must not run in-process.
            policy = tool_def.policy if tool_def else None
            if policy is None:
                raise RunnerUnavailableError(
                    "ContainerRunner requires ToolPolicy with container_codegen_trusted=True"
                )
            if not (policy.trusted and policy.container_codegen_trusted):
                raise RunnerUnavailableError(
                    "ContainerRunner requires a trusted code-generation tool. "
                    "Set ToolPolicy(trusted=True, container_codegen_trusted=True) "
                    "only for safe code-builder functions that return CodeExecutionRequest."
                )
            from seekflow.tools.container_runner import ContainerRunner
            return ContainerRunner(self.sandbox)

        if plan.runner == "external_container":
            # Lv3: external tools run in isolated containers via their manifest
            from seekflow.tools.external_runner import ExternalToolRunner
            return ExternalToolRunner(egress_sidecar=getattr(self, "egress_sidecar", None))

        if plan.runner == "mcp_gateway":
            # Lv3: MCP tools run through MCPGatewayRunner — no local callable
            from seekflow.mcp.runner import MCPGatewayRunner
            return MCPGatewayRunner(self.mcp_gateway_registry)

        raise RunnerUnavailableError(f"Unknown runner: {plan.runner}")

    def _record_audit(self, tool_def, call_id: str, args: dict,
                      result: str | None = None, *, latency_ms: int = 0,
                      ok: bool = False, error: str | None = None,
                      policy_decision: str = "allowed", policy_reason: str = "",
                      repair_attempted: bool = False, repair_confidence: float = 1.0,
                      risk: str = "read", runner_name: str = "",
                      egress_entries=None, secret_refs=None) -> None:
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
            runner_name=runner_name,
        ))

        # ── Durable audit (Lv3): write to append-only store if configured ──
        if self.audit_store is not None:
            self._write_durable_audit(
                tool_def, call_id, args, args_hash, result_hash,
                latency_ms, ok, error, runner_name, risk,
                egress_entries=egress_entries, secret_refs=secret_refs,
            )

    def _write_durable_audit(self, tool_def, call_id: str, args: dict,
                              args_hash: str, result_hash: str | None,
                              latency_ms: int, ok: bool, error: str | None,
                              runner_name: str, risk: str,
                              egress_entries=None, secret_refs=None) -> None:
        """Write a durable AuditEvent to the configured audit store."""
        import logging
        import uuid
        from datetime import datetime, timezone

        try:
            from seekflow.audit.model import AuditEvent, EgressAudit

            meta = tool_def.metadata or {}
            policy = tool_def.policy
            policy_digest = None
            if policy is not None:
                import json as _json
                policy_canonical = _json.dumps(
                    policy.model_dump(mode="json", exclude_none=True),
                    sort_keys=True, ensure_ascii=False,
                )
                policy_digest = hashlib.sha256(
                    policy_canonical.encode("utf-8")
                ).hexdigest()[:16]

            # Convert egress entries to EgressAudit models
            egress_audits: list[EgressAudit] = []
            if egress_entries:
                for entry in egress_entries:
                    if isinstance(entry, EgressAudit):
                        egress_audits.append(entry)
                    elif isinstance(entry, dict):
                        egress_audits.append(EgressAudit(**entry))
                    elif hasattr(entry, "domain"):
                        egress_audits.append(EgressAudit(
                            url=getattr(entry, "url", ""),
                            domain=getattr(entry, "domain", ""),
                            method=getattr(entry, "method", "GET"),
                            status_code=getattr(entry, "status_code", 0),
                            request_hash=getattr(entry, "request_hash", ""),
                            response_hash=getattr(entry, "response_hash", ""),
                            bytes_sent=getattr(entry, "bytes_sent", 0),
                            bytes_received=getattr(entry, "bytes_received", 0),
                            allowed=getattr(entry, "allowed", True),
                            block_reason=getattr(entry, "block_reason", None),
                        ))

            event = AuditEvent(
                event_id=str(uuid.uuid4()),
                ts=datetime.now(timezone.utc),
                run_id=getattr(self.context, "run_id", "") if self.context else "",
                step=getattr(self.context, "step", 0) if self.context else 0,
                event_type="tool_execution",
                tool_name=tool_def.name,
                tool_version=meta.get("manifest_version"),
                tool_digest=meta.get("manifest_digest"),
                manifest_digest=meta.get("manifest_digest"),
                policy_digest=policy_digest,
                input_hash=args_hash,
                output_hash=result_hash,
                runner=runner_name,
                sandbox_image_digest=(
                    meta.get("_manifest_data", {}).get("sandbox", {}).get("image_digest")
                    if isinstance(meta.get("_manifest_data"), dict) else None
                ),
                egress=egress_audits,
                secret_refs=list(secret_refs) if secret_refs else [],
                ok=ok,
                error=error,
                elapsed_ms=latency_ms,
            )
            self.audit_store.append(event)
        except Exception as e:
            if self.audit_required:
                raise AuditStoreError(f"Durable audit write failed: {e}") from e
            logging.getLogger("seekflow.executor").warning(
                "Durable audit write failed (non-required mode): %s", e
            )

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
