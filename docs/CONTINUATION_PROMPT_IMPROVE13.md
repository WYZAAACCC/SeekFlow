# SeekFlow v0.3.6 → 完全 Level 2 半生产级 继续实施 Prompt

将此文件内容完整复制给新对话中的 Claude Code。

---

## 项目上下文

你正在处理 `WYZAAACCC/SeekFlow` 项目。这是一个 DeepSeek-native secure tool runtime，当前处于 **Level 2 半生产候选级 (v0.3.6)**，目标是从候选级推进到**完全 Level 2 半生产级**。

**代码基线**：commit `3c11978`（或最新 main），版本 v0.3.6
**测试基线**：`829 passed / 52 skipped / 54 xfailed / 0 failed`
**GitHub**：https://github.com/WYZAAACCC/SeekFlow

当前已完成：
- ToolRunner 强制执行（InProcessRunner / ProcessRunner / ContainerRunner）
- PolicyEngine normalized context（_NormalizedPolicyContext）
- close_object_schema（additionalProperties=false 默认）
- max_input_bytes / max_output_bytes 强制限制
- retry idempotency 控制
- ProcessRunner 强化（Queue maxsize=1, exit_code, queue.close）
- container runner fail-closed（无 ContainerSandbox 时拒绝）
- 文档版本 v0.3.6 同步
- xfail 质量提升（strict=True + issue 编号）

本轮 improve13.md 审计发现，**安全语义仍可被配置弱化，少数执行边界不够硬**。需要实施 10 个 PR 完成最后的闭环。

---

## 剩余任务：10 个 PR

### PR-1：Runner override 不得弱化隔离等级（P0）

**当前问题**：[planner.py:49-58](src/seekflow/tools/planner.py#L49-L58)，显式 `policy.runner` 直接覆盖所有风险判断：

```python
# 当前代码 — 不检查风险等级，直接使用用户指定的 runner
if policy is not None and policy.runner != "auto":
    return ExecutionPlan(
        runner=policy.runner,  # ← 可以是 "in_process" 即使是 destructive!
        ...
    )
```

这意味着用户可以配置 `ToolPolicy(risk="destructive", runner="in_process")` 让高危工具在宿主进程运行。

**修复方案**：引入 runner 等级系统。显式 runner 只能**提升**隔离等级，不能降低。

在 planner.py 新增：

```python
RUNNER_ORDER = {"in_process": 0, "process": 1, "container": 2}

def _required_runner(policy) -> str:
    """Minimum isolation level required by this tool's risk/capabilities."""
    caps = policy.capabilities if policy else set()
    risk = policy.risk if policy else "destructive"

    if risk in {"code_exec", "destructive"} or "code.exec" in caps:
        return "container"
    if risk in {"network", "write"} or "network.public_http" in caps or "filesystem.write" in caps:
        return "process"
    if policy and policy.trusted and risk == "read" and policy.parallel_safe:
        return "in_process"
    return "process"
```

修改 `plan_execution()` 中的显式 runner 逻辑（替换第 50-58 行）：

```python
required = _required_runner(policy)

if policy is not None and policy.runner != "auto":
    requested = policy.runner
    if RUNNER_ORDER.get(requested, 0) < RUNNER_ORDER.get(required, 0):
        # 用户请求的 runner 弱于 required → 升级为 required
        return ExecutionPlan(
            runner=required,
            timeout_s=effective_timeout,
            requires_hard_timeout=required != "in_process",
            allow_parallel=False,
            cache_allowed=policy.risk == "read",
            reason=f"policy.runner={requested} upgraded to required runner={required} (minimum isolation)",
        )
    # 用户请求的 runner 等于或强于 required → 可以使用
    return ExecutionPlan(
        runner=requested,
        timeout_s=effective_timeout,
        requires_hard_timeout=requested != "in_process",
        allow_parallel=requested == "in_process" and policy.parallel_safe,
        cache_allowed=policy.risk == "read",
        reason=f"explicit runner={requested}, required={required}",
    )
```

**修改文件**：
- `src/seekflow/tools/planner.py` — 核心修改
- `tests/tools/test_runner_selection.py` — 更新现有测试（如果有显式 runner 测试）
- `tests/tools/test_runner_minimum_isolation.py` — 🆕 新建

**新测试**（tests/tools/test_runner_minimum_isolation.py）：
```python
def test_code_exec_runner_process_upgraded_to_container():
    """code_exec 请求 process runner 自动升级为 container"""
    policy = ToolPolicy(risk="code_exec", capabilities={"code.exec"}, runner="process", trusted=True)
    td = ToolDefinition(name="x", description="", parameters={}, func=lambda: 1, policy=policy)
    plan = plan_execution(td, timeout=30)
    assert plan.runner == "container"

def test_destructive_runner_in_process_upgraded_to_container():
    """destructive 请求 in_process runner 自动升级为 container"""
    policy = ToolPolicy(risk="destructive", runner="in_process", trusted=True)
    td = ToolDefinition(name="x", description="", parameters={}, func=lambda: 1, policy=policy)
    plan = plan_execution(td, timeout=30)
    assert plan.runner == "container"

def test_network_runner_in_process_upgraded_to_process():
    """network 请求 in_process 自动升级为 process"""
    policy = ToolPolicy(risk="network", runner="in_process", trusted=True,
                        capabilities={"network.public_http"},
                        allowed_domains={"example.com"}, url_params=frozenset({"url"}))
    td = ToolDefinition(name="x", description="", parameters={"type":"object","properties":{"url":{"type":"string"}}},
                        func=lambda url: "ok", policy=policy)
    plan = plan_execution(td, timeout=30)
    assert plan.runner == "process"

def test_write_runner_in_process_upgraded_to_process():
    """write 请求 in_process 自动升级为 process"""
    from pathlib import Path
    policy = ToolPolicy(risk="write", runner="in_process", trusted=True,
                        capabilities={"filesystem.write"},
                        workspace_root=Path("/tmp"), path_params=frozenset({"path"}))
    td = ToolDefinition(name="x", description="", parameters={"type":"object","properties":{"path":{"type":"string"}}},
                        func=lambda path: "ok", policy=policy)
    plan = plan_execution(td, timeout=30)
    assert plan.runner == "process"

def test_read_runner_container_allowed_as_stronger_isolation():
    """read 工具可以显式提升到 container（更强的隔离）"""
    policy = ToolPolicy(risk="read", runner="container")
    td = ToolDefinition(name="x", description="", parameters={}, func=lambda: 1, policy=policy)
    plan = plan_execution(td, timeout=30)
    assert plan.runner == "container"

def test_read_runner_process_allowed_as_stronger_isolation():
    """read 工具可以显式提升到 process"""
    policy = ToolPolicy(risk="read", runner="process")
    td = ToolDefinition(name="x", description="", parameters={}, func=lambda: 1, policy=policy)
    plan = plan_execution(td, timeout=30)
    assert plan.runner == "process"
```

---

### PR-2：ContainerRunner 安全语义收口（P0）

**当前问题**：[container_runner.py:46](src/seekflow/tools/container_runner.py#L46)：

```python
# ContainerRunner.run() — 第 46 行
request = func(**arguments)  # ← 在宿主进程中执行 tool function!
```

sandbox 只保护 `func` 返回的 code，不保护 `func` 本身。恶意 tool function 在宿主进程中已经有完全访问权限。

**半生产目标**：ContainerRunner 只接受**显式声明的可信 code-builder 工具**。tool function 只负责生成 `CodeExecutionRequest`，不执行用户代码。

**修复**：

(a) 在 [types.py](src/seekflow/types.py) 中，`ToolPolicy` 新增字段：

```python
container_codegen_trusted: bool = False
```

(b) 在 [executor.py](src/seekflow/tools/executor.py) 的 `_runner_for()` 或 `execute()` 中，当 `plan.runner == "container"` 时增加检查：

```python
# 在 _runner_for("container") 分支中，ContainerRunner 创建前：
policy = tool_def.policy
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
```

(c) 在 [container_runner.py](src/seekflow/tools/container_runner.py) 的 docstring 和错误消息中声明边界。

**修改文件**：
- `src/seekflow/types.py` — 新增字段
- `src/seekflow/tools/executor.py` — 增加 container codegen trusted 检查
- `src/seekflow/tools/container_runner.py` — 文档和错误消息更新
- `tests/tools/test_container_runner_semantics.py` — 🆕 新建
- `docs/security/levels.md` — 更新 ContainerRunner 边界说明

**新测试**（tests/tools/test_container_runner_semantics.py）：
```python
def test_container_runner_requires_trusted_codegen_policy():
    """无 container_codegen_trusted 的 container 工具被拒绝"""
    ...

def test_untrusted_container_codegen_denied():
    """仅 trusted=True 但无 container_codegen_trusted → 拒绝"""
    ...

def test_container_runner_with_codegen_trusted_accepted():
    """trusted + container_codegen_trusted → 接受"""
    ...

def test_container_runner_rejects_plain_object_result():
    """返回非 CodeExecutionRequest/str → 拒绝"""
    ...
```

---

### PR-3：ProcessRunner 对所有结果做 bounded output（P1）

**当前问题**：[runners.py:28-37](src/seekflow/tools/runners.py#L28-L37)，`_run_in_subprocess` 只对字符串做 bounded：

```python
if isinstance(result, str):
    bounded, truncated = serialize_bounded(result, max_output_bytes)
    ...
else:
    queue.put({"ok": True, "result": result, ...})  # ← dict/list 原样通过 Queue
```

大 dict/list（如 100MB JSON）会原样跨进程传输，打爆父进程内存。

**修复方案**（方案 B：小对象保真，大对象字符串化）：

在 `_run_in_subprocess` 中：

```python
from seekflow.tools.limits import estimate_json_bytes, serialize_bounded

result = func(**args)
size = estimate_json_bytes(result)

if size <= max_output_bytes:
    queue.put({"ok": True, "result": result, "output_truncated": False})
else:
    serialized, truncated = serialize_bounded(result, max_output_bytes)
    queue.put({"ok": True, "result": serialized, "output_truncated": truncated})
```

同时给 `queue.put()` 添加失败兜底：

```python
try:
    queue.put(payload)
except Exception as e:
    fallback, _ = serialize_bounded(
        {"error": f"failed to serialize tool result: {e}"}, max_output_bytes
    )
    queue.put({"ok": False, "error": fallback})
```

**修改文件**：
- `src/seekflow/tools/runners.py` — `_run_in_subprocess` 中的 output bounding 逻辑
- `tests/tools/test_process_runner_output_bounds.py` — 🆕 新建

**新测试**（tests/tools/test_process_runner_output_bounds.py）：
```python
def test_large_dict_output_bounded_in_child():
    """大 dict 在子进程中被截断，不跨进程原样传输"""
    def big_dict():
        return {"data": "x" * 200_000}
    runner = ProcessRunner()
    result = runner.run(big_dict, {}, timeout_s=5.0, max_output_bytes=100_000)
    assert result.ok
    assert result.output_truncated
    # 结果长度应 ≤ max_output_bytes + truncation notice
    assert len(str(result.result)) <= 100_000 + 100

def test_small_dict_output_preserved():
    """小 dict 保持原始类型"""
    def small_dict():
        return {"a": 1, "b": 2}
    runner = ProcessRunner()
    result = runner.run(small_dict, {}, timeout_s=5.0, max_output_bytes=100_000)
    assert result.ok
    assert not result.output_truncated
    assert result.result == {"a": 1, "b": 2}

def test_large_list_output_bounded():
    """大 list 在子进程中被截断"""
    def big_list():
        return ["x" * 100_000] * 100
    runner = ProcessRunner()
    result = runner.run(big_list, {}, timeout_s=5.0, max_output_bytes=50_000)
    assert result.ok
    assert result.output_truncated

def test_unserializable_result_graceful_error():
    """不可序列化的结果返回错误，不 hang"""
    ...
```

---

### PR-4：Cache 策略限定 read-only / explicit opt-in（P1）

**当前问题**：[executor.py:443-445](src/seekflow/tools/executor.py#L443-L445) — cache write 只检查 `metadata["cache"]`，不限工具类型：

```python
# 当前 cache write（第 443-445 行）
if self._cache is not None:
    cache_enabled = tool_def.metadata.get("cache", True)
    if cache_enabled:  # ← write/network/destructive 也会进入
        self._cache.put(cache_key, exec_result)
```

cache lookup（第 267-268 行）已限制 read，但 cache write 未限制。write/network 工具的结果会被写入缓存。

**修复**：新增 `_cache_allowed(tool_def)` 统一用于 lookup 和 write：

```python
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
```

然后在 executor 中用 `_cache_allowed(tool_def)` 替换两处 `cache_enabled` 检查（lookup 和 write）。

**修改文件**：
- `src/seekflow/tools/executor.py` — 添加 `_cache_allowed`，替换两处 cache check
- `tests/tools/test_executor_cache_policy.py` — 🆕 新建

**新测试**（tests/tools/test_executor_cache_policy.py）：
```python
def test_write_tool_result_not_cached():
    """write 工具结果不缓存，即使 metadata.cache=True"""
    ...

def test_network_tool_not_cached_by_default():
    """network 工具默认不缓存"""
    ...

def test_idempotent_network_cache_with_explicit_opt_in():
    """idempotent=True + cache_network=True 才允许 network 缓存"""
    ...

def test_no_policy_tool_not_cached():
    """无 policy 工具不缓存"""
    ...
```

---

### PR-5：Trusted output 从 metadata 收口到 ToolPolicy（P1）

**当前问题**：[executor.py:415](src/seekflow/tools/executor.py#L415)：

```python
trusted = (tool_def.metadata or {}).get("trusted", False)
if not trusted:
    # redact + wrap_untrusted
```

这有两个问题：
1. `metadata.trusted` 是旧路径，与 `ToolPolicy.trusted`（执行可信）概念混淆
2. **执行可信 ≠ 输出可信**。即使工具在 in_process 执行，其输出仍可能是不可信的

**修复**：

(a) 在 [types.py](src/seekflow/types.py) 中，`ToolPolicy` 新增字段：

```python
trusted_output: bool = False
```

(b) 在 executor 中将 metadata.trusted 检查改为 policy.trusted_output：

```python
policy = tool_def.policy
trusted_output = bool(policy and policy.trusted_output)

if not trusted_output:
    # redact + wrap_untrusted
    from seekflow.security import wrap_untrusted, redact_secrets
    if isinstance(raw_result, str):
        content = redact_secrets(raw_result)
    else:
        content = redact_secrets(json.dumps(raw_result, ensure_ascii=False, default=str))
    raw_result = wrap_untrusted(tool_call.name, content).format_for_model()
else:
    # trusted output: still redact secrets by default
    from seekflow.security import redact_secrets
    if isinstance(raw_result, str):
        raw_result = redact_secrets(raw_result)
```

(c) 如果旧 metadata.trusted 存在且 policy.trusted_output 未设置，发出 DeprecationWarning（兼容迁移）。

**修改文件**：
- `src/seekflow/types.py` — 新增 `trusted_output` 字段
- `src/seekflow/tools/executor.py` — 替换 trusted 判断逻辑
- `tests/tools/test_trusted_output_policy.py` — 🆕 新建

**新测试**（tests/tools/test_trusted_output_policy.py）：
```python
def test_metadata_trusted_does_not_skip_untrusted_wrap():
    """metadata.trusted 不再决定是否跳过 untrusted wrapping"""
    ...

def test_policy_trusted_execution_still_wraps_output_by_default():
    """trusted=True (执行可信) 不自动 trusted_output"""
    ...

def test_policy_trusted_output_skips_wrap_but_still_redacts():
    """trusted_output=True 跳过 wrap 但仍做 redaction"""
    ...

def test_default_output_is_wrapped_and_redacted():
    """默认所有工具输出都 redact + wrap_untrusted"""
    ...
```

---

### PR-6：No-policy execution 默认拒绝（P1）

**当前问题**：[executor.py:158](src/seekflow/tools/executor.py#L158)，当 `policy_engine=None` 时：

```python
if self.policy_engine is not None:  # ← 没有 policy_engine 就跳过
    decision = self.policy_engine.authorize(...)
```

这意味着直接构造 `ToolExecutor(registry)` 不传 policy_engine 时，无 policy 工具可以执行。这是 legacy escape hatch。

**修复**：

(a) `ToolExecutor.__init__()` 新增参数：

```python
allow_unsafe_no_policy_execution: bool = False
```

(b) 在 execute() 中，policy gate 之前添加：

```python
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
```

**重要**：这个检查必须同时适用于有 policy_engine 和无 policy_engine 的情况。

**修改文件**：
- `src/seekflow/tools/executor.py` — __init__ + execute() 检查
- `tests/tools/test_no_policy_execution.py` — 🆕 新建
- `docs/security/levels.md` — 标注 unsafe mode 不属于 Level 2

**新测试**（tests/tools/test_no_policy_execution.py）：
```python
def test_no_policy_tool_denied_by_default():
    """无 policy 工具默认拒绝，即使没有 policy_engine"""
    reg = ToolRegistry()
    def read(): return "data"
    reg.register(_make_tool_definition(read))
    executor = ToolExecutor(reg)  # 无 policy_engine
    result = executor.execute(ToolCall(name="read", arguments={}))
    assert not result.ok
    assert "ToolPolicy required" in result.error

def test_no_policy_tool_allowed_with_unsafe_flag():
    """allow_unsafe_no_policy_execution=True 时允许执行"""
    ...

def test_unsafe_flag_emits_runtime_warning():
    """开启 unsafe flag 时发出 RuntimeWarning"""
    ...
```

**注意**：这个修改会影响所有使用 registry.register(raw_function) 的旧测试。这些测试需要：
- 要么给工具添加 ToolPolicy，要么
- 在 executor 构造时传 `allow_unsafe_no_policy_execution=True`，要么
- 标记为 xfail（若为预存行为）

类似地，`execute_batch` 也会受影响。请确保批量执行也走同样的检查。

---

### PR-7：Deprecate `authorize_with_context()`（P1）

**当前问题**：[policy.py:57-81](src/seekflow/policy.py#L57-L81)，`authorize_with_context(policy, context)` 只检查 risk/capability/approval，不验证 args（URLs、paths、workspace 等）。

外部调用者可能误以为它等价于完整授权。

**修复**：

在 `authorize_with_context` 方法体开头添加：

```python
import warnings
warnings.warn(
    "authorize_with_context() is deprecated — it does not validate tool arguments "
    "(URLs, paths, workspace). Use authorize(tool_def, args, context) for full "
    "policy enforcement.",
    DeprecationWarning,
    stacklevel=2,
)
```

并在 docstring 中标注"不验证 tool arguments，不适用于完整 tool execution 授权"。

**修改文件**：
- `src/seekflow/policy.py` — 添加 DeprecationWarning
- `tests/security/test_policy_deprecated_api.py` — 🆕 新建
- `docs/security/levels.md` — 标注 API 状态

**新测试**：
```python
def test_authorize_with_context_emits_deprecation_warning():
    """调用 authorize_with_context 发出 DeprecationWarning"""
    engine = PolicyEngine()
    policy = ToolPolicy(risk="read")
    ctx = ToolPolicyContext()
    with pytest.warns(DeprecationWarning, match="does not validate tool arguments"):
        engine.authorize_with_context(policy, ctx)
```

---

### PR-8：ContainerSandbox timeout 显式 docker kill/rm（P1）

**当前问题**：[sandbox.py:133 + 149](src/seekflow/sandbox.py#L133-L149)，ContainerSandbox 使用：

```python
cmd = ["docker", "run", "--rm", ...]
result = subprocess.run(cmd, timeout=timeout + 5)
```

`--rm` flag 依赖 docker CLI 正常退出。如果 Python 进程被 timeout 杀死，`--rm` 可能不触发，留下僵尸容器。

**修复**：

(a) 生成唯一 container name：

```python
import uuid
container_name = f"seekflow-sandbox-{uuid.uuid4().hex[:12]}"
cmd = ["docker", "run", "--rm", "--name", container_name, ...]
```

(b) 用 `subprocess.Popen` + `communicate(timeout=...)` 代替 `subprocess.run`：

```python
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    stdout, stderr = proc.communicate(timeout=timeout_s + 5)
except subprocess.TimeoutExpired:
    # 显式清理
    subprocess.run(["docker", "kill", container_name], timeout=3, capture_output=True)
    subprocess.run(["docker", "rm", "-f", container_name], timeout=3, capture_output=True)
    proc.kill()
    proc.wait(timeout=2)
    return SandboxResult(ok=False, error=f"timeout after {timeout_s}s", killed=True, ...)
finally:
    # 兜底清理
    subprocess.run(["docker", "rm", "-f", container_name], timeout=3, capture_output=True)
    try: os.unlink(tmp.name)
    except: pass
```

(c) `SandboxResult` 新增字段：

```python
@dataclass
class SandboxResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    elapsed_ms: int = 0
    killed: bool = False          # 新增
    container_name: str | None = None  # 新增
```

**修改文件**：
- `src/seekflow/sandbox.py` — ContainerSandbox.execute() 重写清理逻辑；SandboxResult 新增字段
- `tests/security/test_container_sandbox_cleanup.py` — 🆕 新建

**新测试**（使用 monkeypatch mock subprocess）：
```python
def test_container_timeout_calls_docker_kill_and_rm():
    """timeout 时显式调用 docker kill + docker rm -f"""
    ...

def test_container_cleanup_called_in_finally():
    """正常执行后 finally 中也执行 docker rm -f 清理"""
    ...

def test_container_name_recorded_in_result():
    """container_name 记录在 SandboxResult 中"""
    ...
```

---

### PR-9：核心 xfail 收敛 — release gate（P2）

**当前状态**：14 个核心路径 xfail（strict=True + issue 编号）。`scripts/check_xfail_policy.py` 对核心 xfail 只发 WARNING。

**修复**：

(a) 在 `scripts/check_xfail_policy.py` 中添加 `--strict-core` CLI flag：

```python
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--strict-core", action="store_true",
    help="Treat core-path xfail as ERROR instead of WARNING")
args = parser.parse_args()
```

当 `--strict-core` 时，核心路径 xfail 从 WARNING 升级为 ERROR（exit code 1）。

(b) 在 `docs/production-readiness.md`（或新建）中写清楚 release checklist，其中包含 `python scripts/check_xfail_policy.py --strict-core` 必须通过。

(c) 不要在当前会话中试图修复这 14 个核心 xfail——它们来自 v0.3.0–v0.3.5 用户业务变更，不了解意图无法正确修复。只做闸门工具。

**修改文件**：
- `scripts/check_xfail_policy.py` — 添加 --strict-core
- `docs/production-readiness.md` — 🆕 新建 release checklist

---

### PR-10：最终文档与 release checklist（P2）

**修改**：

(a) README.md 增加准确的安全边界：

```markdown
## Security Status (v0.3.x)

SeekFlow v0.3.x supports **Level 2 semi-production** under these conditions:
- All tools must have ToolPolicy.
- `code_exec` and `destructive` require ContainerRunner / ContainerSandbox.
- ProcessRunner provides **timeout isolation**, not a full security sandbox.
- Tool outputs are untrusted by default.
- Network tools require allowed_domains.
- Filesystem tools require workspace_root.
- Untrusted third-party tools and arbitrary MCP servers are not supported.
```

(b) `docs/security/levels.md`——更新 ContainerRunner 边界说明（host-side codegen vs declarative spec）。

(c) `docs/production-readiness.md`——release checklist：

```markdown
- [ ] pytest 0 failed
- [ ] python scripts/check_xfail_policy.py --strict-core exits 0
- [ ] ruff pass
- [ ] README version == pyproject version
- [ ] No known P0/P1 security gaps
```

(d) pyproject.toml：如果 classifier 还是 `4 - Beta` 且代码已达到半生产，可以考虑保持 Beta（半生产 != Stable）。

**修改文件**：
- `README.md`
- `docs/security/levels.md`
- `docs/production-readiness.md` — 🆕 新建
- `CHANGELOG.md` — 更新（如果存在）

---

## 关键架构决策（请遵守）

1. **不重写已有模块**：planner、runners、executor、policy、container_runner、sandbox、limits、validation 的核心逻辑保留，只做边界硬化
2. **安全默认拒绝**：PR-1（runner 不降级）、PR-2（container codegen trusted）、PR-6（no-policy deny）都是 fail-closed
3. **执行可信 ≠ 输出可信**：PR-5 明确分离两个概念。`trusted_output` 默认 False
4. **进程边界不可信**：PR-3 假设子进程可能返回巨大对象，必须在子进程内 bounded
5. **缓存只读**：PR-4 默认只缓存 read 工具结果
6. **每个 PR 至少 3 个测试**：不写测试的改动 = 不完整

## 执行链路（当前已知正确，请勿破坏）

```
Agent.run()
  → _make_runtime()
    → ToolRuntime(policy_engine, context)
      → ToolExecutor(policy_engine, context, approval_handler, sandbox)
        → execute():
          parse → repair → input_limit → policy → coerce → schema_validate
          → cache_lookup → plan_execution → _runner_for → runner.run()
          → bounded_output → redact → wrap_untrusted → truncate
          → cache_write → audit
```

## 关键文件清单

| 文件 | 作用 | 需修改？ |
|------|------|:--:|
| `src/seekflow/types.py` | 新增 container_codegen_trusted, trusted_output | ✅ |
| `src/seekflow/tools/planner.py` | Runner 等级系统 + _required_runner | ✅ |
| `src/seekflow/tools/executor.py` | PR-2/4/5/6: cache+trusted output+no-policy+container check | ✅ |
| `src/seekflow/tools/container_runner.py` | Docstring/错误消息更新 | ✅ |
| `src/seekflow/tools/runners.py` | PR-3: 非字符串 bounded output | ✅ |
| `src/seekflow/policy.py` | PR-7: authorize_with_context deprecation warning | ✅ |
| `src/seekflow/sandbox.py` | PR-8: docker kill/rm, SandboxResult 字段 | ✅ |
| `scripts/check_xfail_policy.py` | PR-9: --strict-core flag | ✅ |
| `README.md` | PR-10: 安全边界 | ✅ |
| `docs/security/levels.md` | PR-2/10: ContainerRunner 边界 | ✅ |
| `tests/tools/test_runner_minimum_isolation.py` | PR-1 测试 | 🆕 |
| `tests/tools/test_container_runner_semantics.py` | PR-2 测试 | 🆕 |
| `tests/tools/test_process_runner_output_bounds.py` | PR-3 测试 | 🆕 |
| `tests/tools/test_executor_cache_policy.py` | PR-4 测试 | 🆕 |
| `tests/tools/test_trusted_output_policy.py` | PR-5 测试 | 🆕 |
| `tests/tools/test_no_policy_execution.py` | PR-6 测试 | 🆕 |
| `tests/security/test_policy_deprecated_api.py` | PR-7 测试 | 🆕 |
| `tests/security/test_container_sandbox_cleanup.py` | PR-8 测试 | 🆕 |
| `docs/production-readiness.md` | PR-9/10 | 🆕 |

---

## 参考资料

- `docs/improve13.md` — 本轮审计报告（10 个 PR 完整方案）
- `docs/Improve13_SKIP_REPORT.md` — 审核验证记录（所有 PR 均为真实问题）
- `docs/Improve12_SKIP_REPORT.md` — 上一轮搁置项说明
- `docs/security/levels.md` — 安全等级定义
- `scripts/check_xfail_policy.py` — xfail 合规检查脚本

---

## 实施顺序建议

1. **PR-1** → PR-2 → PR-3（核心安全硬化，无依赖）
2. **PR-4** → PR-5（executor 修改，彼此独立但同文件）
3. **PR-6**（executor，可能在测试中造成广泛影响，需要批量适配测试）
4. **PR-7** → PR-8 → PR-9 → PR-10（独立修改，可并行）

PR-6 预计会影响最多的现有测试（旧测试直接构造 ToolExecutor 无 policy_engine 和无 policy 工具）。处理策略：
- 读取每个受影响的测试
- 如果测试工具是简单纯函数 → 添加 `ToolPolicy(risk="read", trusted=True)` 
- 如果测试明确测试 no-policy 行为 → 更新为测试"拒绝"行为
- 如果测试无法简单修复（需理解业务意图）→ xfail

---

## 最终验收标准

```text
代码闸门：
[ ] policy.runner 不能降低 required runner（PR-1）
[ ] code_exec/destructive 工具无 container_codegen_trusted 必拒绝（PR-2）
[ ] ProcessRunner 对所有大结果做 bounded output（PR-3）
[ ] cache read/write 统一使用 _cache_allowed（PR-4）
[ ] metadata.trusted 不再控制 output wrapping（PR-5）
[ ] no-policy 工具默认拒绝（PR-6）
[ ] authorize_with_context 有 DeprecationWarning（PR-7）
[ ] ContainerSandbox timeout 显式 docker kill/rm（PR-8）
[ ] check_xfail_policy.py --strict-core 可用（PR-9）
[ ] 文档写清 Level 2 边界（PR-10）

测试闸门：
[ ] pytest 0 failed
[ ] 10 个 PR 各有 ≥3 个测试
[ ] runner minimum isolation 测试全过
[ ] container semantics 测试全过
[ ] process large output 测试全过
[ ] cache policy 测试全过
[ ] trusted output 测试全过
[ ] no-policy execution 测试全过
```
