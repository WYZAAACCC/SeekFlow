下面是一份可以直接给 Claude Code 执行的 **SeekFlow v0.3.6 → 完全 Level 2 半生产级工程修复 RFC**。
它不是泛泛建议，而是基于最新已推送代码、Improve12 审核差异报告、以及上一轮代码审计结论整理出的**可实现、可验收、可拆 PR 的修复方案**。

---

# SeekFlow 完全半生产级修复 RFC

## 0. 目标

当前 SeekFlow v0.3.6 已经达到 **Level 2 半生产候选级**：ToolRunner、ProcessRunner、ContainerRunner、Policy normalized context、close schema、resource limits、idempotent retry、文档版本同步都已经落地。Improve12 审核差异报告也说明 10 个 PR 中 9 个已修复，PR-9 的核心路径零 xfail 要求被部分搁置。

本 RFC 的目标是把它从：

> **Level 2 半生产候选级**

推进到：

> **完全 Level 2 半生产级**

完成后，SeekFlow 可以诚实支持：

```text
非完全可信 prompt
+ 可信注册工具
+ 强制 ToolPolicy
+ 受限网络/文件访问
+ ProcessRunner timeout isolation
+ code_exec/destructive fail-closed or ContainerSandbox
+ schema validation
+ resource limits
+ audit/trace 安全边界
```

仍不支持：

```text
非可信第三方工具市场
任意 MCP server
任意用户上传 Python tool
多租户 SaaS
强合规审计
ProcessRunner 作为强安全 sandbox
```

---

# 1. 当前剩余阻塞项

上一轮审计确认，v0.3.6 的主要剩余问题不是“没有安全机制”，而是**安全语义仍可被配置弱化**，以及少数执行边界不够硬。

必须修复的关键点：

| 优先级 | 问题                                                      | 影响                                                        |
| --- | ------------------------------------------------------- | --------------------------------------------------------- |
| P0  | 显式 `policy.runner` 可以弱化高风险工具 runner                     | `code_exec/destructive/network/write` 可能被配置成 `in_process` |
| P0  | `ContainerRunner` 先在宿主进程调用 tool function，再 sandbox code | sandbox 只保护返回的 code，不保护 tool function 本身                  |
| P1  | `ProcessRunner` 只限制字符串输出，非字符串大对象可能跨进程返回                 | 大 dict/list 可能打爆父进程内存                                     |
| P1  | cache 写入可能缓存非 read 工具结果                                 | side-effect / network 结果进入 cache                          |
| P1  | trusted output 仍可能受 metadata 控制                         | metadata 可绕过 untrusted wrapping                           |
| P1  | no-policy executor legacy path 仍可执行                     | 直接构造 executor 时绕过 policy model                            |
| P1  | `authorize_with_context()` 是不完整授权 API                   | 外部误用会绕过 path/url args 校验                                  |
| P1  | ContainerSandbox timeout 未显式 docker kill/rm             | 容器清理不够强                                                   |
| P2  | 核心 xfail 仍未清零                                           | 候选级可接受，完全半生产级不够                                           |

---

# 2. PR 拆分总览

建议按以下 PR 顺序执行：

| PR    | 标题                                         | 阻塞级别 |
| ----- | ------------------------------------------ | ---- |
| PR-1  | Runner override 不得弱化隔离等级                   | P0   |
| PR-2  | ContainerRunner 安全语义收口                     | P0   |
| PR-3  | ProcessRunner 对所有结果做 bounded output        | P1   |
| PR-4  | Cache 策略限定 read-only / explicit opt-in     | P1   |
| PR-5  | Trusted output 语义从 metadata 收口到 ToolPolicy | P1   |
| PR-6  | No-policy execution 默认拒绝                   | P1   |
| PR-7  | Deprecate `authorize_with_context()`       | P1   |
| PR-8  | ContainerSandbox 显式 docker kill/rm         | P1   |
| PR-9  | 核心 xfail 收敛策略                              | P2   |
| PR-10 | 半生产级最终文档和 release checklist                | P2   |

---

# PR-1：Runner override 不得弱化隔离等级

## 1.1 问题

当前 `planner.py` 的规则中，显式 `policy.runner != "auto"` 优先于所有风险判断。这意味着用户可以写：

```python
ToolPolicy(
    risk="destructive",
    runner="in_process",
    trusted=True,
)
```

如果 approval 通过，该 destructive 工具仍可能在宿主进程内执行。

这是完全半生产级不能接受的。
**显式 runner 只能提升隔离等级，不能降低隔离等级。**

## 1.2 修改文件

```text
src/seekflow/tools/planner.py
tests/tools/test_runner_selection.py
tests/tools/test_runner_minimum_isolation.py
```

## 1.3 修改方案

在 `planner.py` 中引入 runner 等级：

```python
RUNNER_ORDER = {
    "in_process": 0,
    "process": 1,
    "container": 2,
}
```

新增函数：

```python
def required_runner_for_policy(policy: ToolPolicy) -> RunnerKind:
    caps = policy.capabilities
    risk = policy.risk

    if risk in {"code_exec", "destructive"} or "code.exec" in caps:
        return "container"

    if (
        risk in {"network", "write"}
        or "network.public_http" in caps
        or "filesystem.write" in caps
    ):
        return "process"

    if policy.trusted and risk == "read" and policy.parallel_safe:
        return "in_process"

    return "process"
```

在 `plan_execution()` 中替换显式 runner 逻辑：

```python
required = required_runner_for_policy(policy)

if policy.runner != "auto":
    requested = policy.runner

    if RUNNER_ORDER[requested] < RUNNER_ORDER[required]:
        # Fail-closed by upgrading to required runner.
        return ExecutionPlan(
            runner=required,
            timeout_s=effective_timeout,
            requires_hard_timeout=required != "in_process",
            allow_parallel=False,
            cache_allowed=policy.risk == "read",
            reason=(
                f"policy.runner={requested} is weaker than required "
                f"runner={required}; upgraded fail-closed"
            ),
        )

    return ExecutionPlan(
        runner=requested,
        timeout_s=effective_timeout,
        requires_hard_timeout=requested != "in_process",
        allow_parallel=requested == "in_process" and policy.parallel_safe,
        cache_allowed=policy.risk == "read",
        reason=f"explicit runner={requested}, required={required}",
    )
```

## 1.4 测试

新增 `tests/tools/test_runner_minimum_isolation.py`：

```python
def test_code_exec_runner_process_upgraded_to_container():
    policy = ToolPolicy(risk="code_exec", runner="process")
    tool = make_tool(policy)
    plan = plan_execution(tool, timeout=None)
    assert plan.runner == "container"


def test_destructive_runner_in_process_upgraded_to_container():
    policy = ToolPolicy(risk="destructive", runner="in_process", trusted=True)
    tool = make_tool(policy)
    plan = plan_execution(tool, timeout=None)
    assert plan.runner == "container"


def test_network_runner_in_process_upgraded_to_process():
    policy = ToolPolicy(
        risk="network",
        runner="in_process",
        trusted=True,
        capabilities={"network.public_http"},
        allowed_domains={"example.com"},
        url_params=frozenset({"url"}),
    )
    tool = make_tool(policy)
    plan = plan_execution(tool, timeout=None)
    assert plan.runner == "process"


def test_write_runner_in_process_upgraded_to_process():
    policy = ToolPolicy(
        risk="write",
        runner="in_process",
        trusted=True,
        capabilities={"filesystem.write"},
        workspace_root=Path("/tmp"),
        path_params=frozenset({"path"}),
    )
    tool = make_tool(policy)
    plan = plan_execution(tool, timeout=None)
    assert plan.runner == "process"


def test_read_runner_container_allowed_as_stronger_isolation():
    policy = ToolPolicy(risk="read", runner="container")
    tool = make_tool(policy)
    plan = plan_execution(tool, timeout=None)
    assert plan.runner == "container"
```

## 1.5 验收标准

```text
- 显式 runner 不得降低 required runner 等级
- code_exec/destructive 永远 container
- network/write 至少 process
- read 工具可以显式提升到 process/container
```

---

# PR-2：ContainerRunner 安全语义收口

## 2.1 问题

当前 `ContainerRunner.run()` 会先在宿主进程中执行：

```python
request = func(**arguments)
```

然后才将返回的 `CodeExecutionRequest` 或 code string 放入 sandbox。

这意味着 sandbox 只保护返回的 code，不保护 tool function 本身。对于真正不可信代码执行工具，这是不够的。

## 2.2 半生产目标

Level 2 半生产可以接受：

```text
ContainerRunner 只支持可信 code-builder 工具；
tool function 只负责生成 CodeExecutionRequest；
真正不可信 code 在 ContainerSandbox 中执行。
```

但必须明确、强制、测试。

## 2.3 修改文件

```text
src/seekflow/types.py
src/seekflow/tools/container_runner.py
src/seekflow/tools/executor.py
tests/tools/test_container_runner_semantics.py
docs/security/levels.md
README.md
```

## 2.4 类型扩展

在 `ToolPolicy` 中新增：

```python
container_codegen_trusted: bool = False
```

语义：

```text
trusted=True:
  允许工具函数本身被信任执行。

container_codegen_trusted=True:
  声明该工具函数只是可信 code builder；
  它不会执行用户代码、不会访问未授权资源、不会产生副作用。
```

## 2.5 executor 检查

在 `_runner_for()` 或 `execute()` 中，当 `plan.runner == "container"` 时检查：

```python
policy = tool_def.policy
if policy is None:
    deny

if not (policy.trusted and policy.container_codegen_trusted):
    return ToolExecutionResult(
        ok=False,
        error=(
            "ContainerRunner requires a trusted code-generation tool. "
            "Set ToolPolicy(trusted=True, container_codegen_trusted=True) "
            "only for safe code-builder functions."
        ),
    )
```

如果不希望工具函数在宿主进程执行，则引入 declarative tool spec，见 2.7。

## 2.6 ContainerRunner 增强

`ContainerRunner.run()` 中只接受：

```python
CodeExecutionRequest
str  # 可选，但最好仅用于 legacy
```

如果返回其他类型，拒绝：

```python
if not isinstance(request, (CodeExecutionRequest, str)):
    return ToolRunResult(
        ok=False,
        error="ContainerRunner requires CodeExecutionRequest or code string",
        runner_name="container",
    )
```

## 2.7 推荐长期方案：Declarative CodeExecutionSpec

新增：

```python
@dataclass(frozen=True)
class CodeExecutionSpec:
    code_arg: str = "code"
    language: str = "python"
```

工具注册时：

```python
ToolDefinition(
    name="python_exec",
    execution=CodeExecutionSpec(code_arg="code"),
    policy=ToolPolicy(
        risk="code_exec",
        runner="container",
        capabilities={"code.exec"},
    ),
)
```

这种模式下 executor 不调用 tool function，直接从 validated arguments 中取 code，交给 sandbox。

## 2.8 测试

```python
def test_container_runner_requires_trusted_codegen_policy():
    ...


def test_untrusted_container_codegen_denied():
    ...


def test_container_runner_rejects_plain_object_result():
    ...


def test_declarative_code_exec_does_not_call_host_func():
    ...


def test_container_runner_docstring_mentions_host_codegen_boundary():
    ...
```

## 2.9 验收标准

```text
- ContainerRunner 不得暗示整个 tool function 被 sandbox
- container 工具必须 trusted + container_codegen_trusted，或使用 declarative spec
- 未声明 trusted codegen 的 code_exec/destructive 工具拒绝
```

---

# PR-3：ProcessRunner 对所有结果做 bounded output

## 3.1 问题

当前 ProcessRunner 只对子进程返回的字符串做 bounded serialization。非字符串结果，例如巨大 dict/list，仍可能通过 multiprocessing Queue 原样传给父进程。

这会导致父进程内存风险。

## 3.2 修改文件

```text
src/seekflow/tools/runners.py
src/seekflow/tools/limits.py
tests/tools/test_process_runner_output_bounds.py
```

## 3.3 修改方案

在子进程内对所有结果做 size check。

### 方案 A：所有 ProcessRunner 结果统一字符串化

最安全：

```python
result = func(**args)
serialized, truncated = serialize_bounded(result, max_output_bytes)
queue.put({
    "ok": True,
    "result": serialized,
    "output_truncated": truncated,
})
```

优点：父进程永远不会收到巨大对象。
缺点：小型 int/dict/list 类型不再保真。

### 方案 B：小对象保真，大对象字符串化

折中方案：

```python
result = func(**args)
size = estimate_json_bytes(result)

if size <= max_output_bytes:
    queue.put({
        "ok": True,
        "result": result,
        "output_truncated": False,
    })
else:
    serialized, truncated = serialize_bounded(result, max_output_bytes)
    queue.put({
        "ok": True,
        "result": serialized,
        "output_truncated": truncated,
    })
```

注意：`estimate_json_bytes()` 发生在子进程内，即使巨大对象序列化成本高，也不会打爆父进程。

推荐：**方案 B**。

## 3.4 额外防御

给 `Queue.put()` 加失败兜底：

```python
try:
    queue.put(payload)
except Exception as e:
    fallback, _ = serialize_bounded(
        {"error": f"failed to serialize tool result: {e}"},
        max_output_bytes,
    )
    queue.put({"ok": False, "error": fallback})
```

## 3.5 测试

```python
def test_large_dict_output_bounded_in_child():
    ...


def test_large_list_output_bounded_in_child():
    ...


def test_large_non_string_output_does_not_cross_queue_raw():
    ...


def test_small_dict_output_can_remain_typed():
    ...


def test_unserializable_result_returns_error_not_hang():
    ...
```

## 3.6 验收标准

```text
- 大 dict/list 不会原样跨进程传输
- output_truncated=True 被正确记录
- 小型结构化结果可保真或安全字符串化
- Queue 不因不可序列化结果 hang
```

---

# PR-4：Cache 策略限定 read-only / explicit opt-in

## 4.1 问题

cache lookup 已限制到 read 工具，但 cache write 仍可能对所有工具执行，只要 metadata `cache=True`。

这会污染 cache，甚至让 network/write/destructive 结果被缓存。

## 4.2 修改文件

```text
src/seekflow/tools/executor.py
tests/tools/test_executor_cache_policy.py
```

## 4.3 新增 helper

```python
def _cache_allowed(tool_def: ToolDefinition) -> bool:
    policy = tool_def.policy

    if policy is None:
        return False

    if not tool_def.metadata.get("cache", True):
        return False

    if policy.risk == "read":
        return True

    # Optional explicit opt-in for idempotent network reads.
    if (
        policy.risk == "network"
        and policy.idempotent
        and tool_def.metadata.get("cache_network", False)
    ):
        return True

    return False
```

## 4.4 修改 cache read/write

cache lookup：

```python
if self._cache is not None and _cache_allowed(tool_def):
    cached = self._cache.get(cache_key)
```

cache write：

```python
if self._cache is not None and _cache_allowed(tool_def):
    self._cache.put(cache_key, exec_result)
```

## 4.5 测试

```python
def test_read_tool_result_cached():
    ...


def test_write_tool_result_not_cached_even_if_metadata_cache_true():
    ...


def test_network_tool_not_cached_by_default():
    ...


def test_idempotent_network_cache_requires_explicit_opt_in():
    ...


def test_no_policy_tool_not_cached():
    ...
```

## 4.6 验收标准

```text
- read-only 才默认 cache
- write/network/destructive 默认不 cache
- network cache 必须 idempotent=True + metadata cache_network=True
```

---

# PR-5：Trusted output 从 metadata 收口到 ToolPolicy

## 5.1 问题

executor 当前判断是否 wrap untrusted output 时，仍可能使用 `tool_def.metadata["trusted"]`。这和最新设计冲突，因为 trusted 已经提升到 `ToolPolicy.trusted`。

更重要的是：**执行可信** 和 **输出可信** 是两个不同概念。

```text
trusted execution:
  是否允许 in_process / host-side code generation。

trusted output:
  工具输出是否可以不经过 untrusted wrapper 直接进入模型上下文。
```

二者不应混用。

## 5.2 修改文件

```text
src/seekflow/types.py
src/seekflow/tools/executor.py
tests/tools/test_trusted_output_policy.py
```

## 5.3 类型扩展

在 `ToolPolicy` 中新增：

```python
trusted_output: bool = False
```

默认 false。

## 5.4 executor 修改

将：

```python
trusted = tool_def.metadata.get("trusted", False)
```

改为：

```python
policy = tool_def.policy
trusted_output = bool(policy and policy.trusted_output)
```

然后：

```python
if not trusted_output:
    redacted = redact_secrets(...)
    wrapped = wrap_untrusted(tool_name, redacted).format_for_model()
else:
    # Still redact secrets unless explicitly disabled by separate dangerous flag.
    wrapped = redact_secrets(raw_output)
```

强烈建议：即使 `trusted_output=True`，也默认 redaction，不要默认绕过 secret redaction。

## 5.5 迁移兼容

如果旧 metadata trusted 仍存在：

```python
if tool_def.metadata.get("trusted", False) and not policy.trusted_output:
    warnings.warn(
        "metadata['trusted'] no longer controls output trust; use ToolPolicy.trusted_output",
        DeprecationWarning,
    )
```

## 5.6 测试

```python
def test_metadata_trusted_does_not_skip_untrusted_wrap():
    ...


def test_policy_trusted_execution_still_wraps_output_by_default():
    ...


def test_policy_trusted_output_skips_wrap_but_still_redacts():
    ...


def test_untrusted_output_redacted_then_wrapped():
    ...
```

## 5.7 验收标准

```text
- metadata.trusted 不再决定 output wrapping
- trusted execution 和 trusted output 分离
- 默认所有工具输出都作为 untrusted data
- secret redaction 默认不被 trusted_output 绕过
```

---

# PR-6：No-policy execution 默认拒绝

## 6.1 问题

主链路中 PolicyEngine 默认 no-policy deny，但如果开发者直接构造 `ToolExecutor(policy_engine=None)`，可能仍执行无 policy 工具。这是 legacy escape hatch。

完全半生产级要求：**无 ToolPolicy 的工具默认不能执行**，除非显式开启 unsafe/dev 模式。

## 6.2 修改文件

```text
src/seekflow/tools/executor.py
tests/tools/test_no_policy_execution.py
docs/security/levels.md
```

## 6.3 修改方案

`ToolExecutor.__init__()` 新增：

```python
allow_unsafe_no_policy_execution: bool = False
```

执行前：

```python
if tool_def.policy is None and not self.allow_unsafe_no_policy_execution:
    return ToolExecutionResult(
        tool_call_id=tool_call.id,
        name=tool_call.name,
        arguments=arguments,
        ok=False,
        error="ToolPolicy required for execution",
        elapsed_ms=0,
    )
```

如果 `allow_unsafe_no_policy_execution=True`，需要 warning：

```python
warnings.warn(
    "allow_unsafe_no_policy_execution=True disables semi-production safety guarantees",
    RuntimeWarning,
)
```

## 6.4 测试

```python
def test_no_policy_tool_denied_even_without_policy_engine():
    ...


def test_no_policy_tool_can_run_only_with_explicit_unsafe_flag():
    ...


def test_unsafe_no_policy_warning_emitted():
    ...
```

## 6.5 验收标准

```text
- 无 policy 工具默认拒绝
- unsafe dev mode 必须显式开启
- 文档说明 unsafe mode 不属于 Level 2
```

---

# PR-7：Deprecate `authorize_with_context()`

## 7.1 问题

`authorize_with_context(policy, context)` 只检查 policy 与 context，不接收 args，因此无法做：

```text
URL validation
path traversal validation
workspace path_params
network url_params
argument-specific security checks
```

如果外部用户误以为它等价于完整 authorization，会绕过关键校验。

## 7.2 修改文件

```text
src/seekflow/policy.py
tests/security/test_policy_deprecated_api.py
docs/security/levels.md
```

## 7.3 修改方案

短期保留，但加 warning：

```python
def authorize_with_context(self, policy, context):
    warnings.warn(
        "authorize_with_context() is deprecated and does not validate tool arguments. "
        "Use authorize(tool_def, args, context) for full policy enforcement.",
        DeprecationWarning,
        stacklevel=2,
    )
    ...
```

文档标注：

```text
authorize_with_context is policy-only and not sufficient for tool execution.
```

长期改名：

```python
authorize_policy_only()
```

## 7.4 测试

```python
def test_authorize_with_context_emits_deprecation_warning():
    ...


def test_authorize_with_context_doc_warns_no_args_validation():
    ...
```

## 7.5 验收标准

```text
- 误用 API 有明确 warning
- 文档不再把 authorize_with_context 描述为完整授权
```

---

# PR-8：ContainerSandbox timeout 显式 docker kill/rm

## 8.1 问题

ContainerSandbox 当前依赖 `subprocess.run(..., timeout=...)` 和 `docker run --rm`。如果 timeout 杀死的是 docker CLI，不一定能保证容器被清理。

## 8.2 修改文件

```text
src/seekflow/sandbox.py
tests/security/test_container_sandbox_cleanup.py
```

## 8.3 修改方案

为每次执行生成 container name：

```python
container_name = f"seekflow-{uuid.uuid4().hex}"
```

docker run 命令增加：

```bash
--name <container_name>
```

用 `subprocess.Popen` 代替 `subprocess.run`：

```python
proc = subprocess.Popen(cmd, stdout=PIPE, stderr=PIPE, text=True)
try:
    stdout, stderr = proc.communicate(timeout=timeout)
except subprocess.TimeoutExpired:
    subprocess.run(["docker", "kill", container_name], timeout=3, check=False)
    subprocess.run(["docker", "rm", "-f", container_name], timeout=3, check=False)
    return SandboxResult(ok=False, error="timeout", killed=True, ...)
finally:
    subprocess.run(["docker", "rm", "-f", container_name], timeout=3, check=False)
```

`SandboxResult` 增加：

```python
killed: bool = False
container_name: str | None = None
```

## 8.4 测试

用 monkeypatch mock `subprocess.Popen` / `subprocess.run`：

```python
def test_container_timeout_calls_docker_kill_and_rm():
    ...


def test_container_cleanup_called_in_finally():
    ...


def test_container_name_recorded_in_result():
    ...
```

## 8.5 验收标准

```text
- timeout 显式 docker kill
- finally 显式 docker rm -f
- audit/result 可记录 container_name/killed
```

---

# PR-9：核心 xfail 收敛

## 9.1 当前状态

报告说明 PR-9 部分搁置：所有 xfail 已改为 strict=True 并带 issue 编号，但仍有 14 个核心路径 xfail。

候选级可以接受 warning；完全半生产级不应长期保留核心 xfail。

## 9.2 修改文件

```text
scripts/check_xfail_policy.py
tests/*
docs/production-readiness.md
```

## 9.3 分阶段策略

### 阶段 A：现在立即做

将核心 xfail 从 warning 改为可配置 error：

```bash
python scripts/check_xfail_policy.py --strict-core
```

CI 主分支使用 warning，release workflow 使用 strict-core。

### 阶段 B：完全半生产 release 前

核心路径必须 0 xfail：

```text
tests/tools/
tests/security/
tests/deepseek/
tests/test_policy.py
tests/test_tool_executor.py
tests/test_runtime.py
tests/test_version_consistency.py
```

### 阶段 C：修复方式

对每个核心 xfail 做分类：

```text
旧语义已废弃 → 删除旧测试，写新语义测试
真实 bug → 修代码
业务未决 → 不发布完全半生产，只保留 candidate
```

## 9.4 验收标准

```text
- release workflow 中 core xfail 为 error
- 完全半生产 tag 前 core xfail = 0
- 非核心 xfail 必须 strict=True + issue id
```

---

# PR-10：最终文档与 release checklist

## 10.1 修改文件

```text
README.md
SECURITY.md 或 docs/security/levels.md
docs/production-readiness.md
CHANGELOG.md
pyproject.toml
.github/workflows/release.yml
```

## 10.2 README 增加准确边界

```markdown
## Security status

SeekFlow v0.3.x supports Level 2 semi-production under these conditions:

- All tools must have ToolPolicy.
- `code_exec` and `destructive` require ContainerRunner / ContainerSandbox.
- ProcessRunner provides timeout isolation, not a full security sandbox.
- Tool outputs are untrusted by default.
- Network tools require allowed_domains and url_params.
- Filesystem tools require workspace_root and path_params.
- Untrusted third-party tools and arbitrary MCP servers are not supported.
```

## 10.3 Release checklist

```text
- pytest 0 failed
- core xfail 0
- ruff pass
- mypy for core modules pass
- no known P0/P1 security gaps
- README version == pyproject version
- CHANGELOG updated
- GitHub Release created
```

## 10.4 验收标准

```text
- 文档不夸大 Level 3/4 能力
- ProcessRunner != sandbox 写清楚
- ContainerRunner host-side codegen boundary 写清楚
- 半生产 release 有 checklist
```

---

# 3. 最终 Definition of Done

完成全部 PR 后，才能声明 **完全 Level 2 半生产级**。

```text
代码闸门：
[ ] policy.runner 不能弱化 required runner
[ ] code_exec/destructive 必须 container 或拒绝
[ ] ContainerRunner 明确只支持 trusted codegen 或 declarative code spec
[ ] ProcessRunner 对所有大结果做 bounded output
[ ] cache read/write 仅限 read-only 或显式 idempotent opt-in
[ ] metadata.trusted 不再控制 output wrapping
[ ] no-policy 工具默认拒绝
[ ] authorize_with_context deprecated
[ ] ContainerSandbox timeout 显式 docker kill/rm

测试闸门：
[ ] pytest 0 failed
[ ] release workflow core xfail = 0
[ ] runner override tests 全过
[ ] container boundary tests 全过
[ ] process large output tests 全过
[ ] cache policy tests 全过
[ ] trusted output tests 全过
[ ] no-policy execution tests 全过

文档闸门：
[ ] README/pyproject 版本一致
[ ] Level 2 边界写清
[ ] ProcessRunner 不是 sandbox 写清
[ ] ContainerRunner host-codegen 边界写清
[ ] Level 3/4 不支持写清
```

---

# 4. 可直接给 Claude 的执行提示词

```text
你要把 SeekFlow v0.3.6 从 Level 2 semi-production candidate 推进到完全 Level 2 半生产级。

请基于当前 main 代码修改，不要重写已有模块。当前已有 ToolRunner、ProcessRunner、ContainerRunner、Policy normalized context、close_object_schema、resource limits、retry idempotency、文档 v0.3.6 等。你的任务是补齐最后的安全闭环。

按以下 PR 执行：

PR-1 Runner minimum isolation：
- 显式 policy.runner 不能降低 required runner。
- code_exec/destructive 永远 required=container。
- network/write 至少 required=process。
- read 可以显式提升到 process/container。
- 新增 tests/tools/test_runner_minimum_isolation.py。

PR-2 ContainerRunner semantics：
- ContainerRunner 当前先调用 func(**arguments)，再 sandbox code。
- 必须明确只允许 trusted code-builder，增加 ToolPolicy.container_codegen_trusted。
- 未 trusted + container_codegen_trusted 的 container tool 必须拒绝。
- 长期可支持 declarative CodeExecutionSpec，避免 host-side function execution。
- 增加测试说明 sandbox 不保护 tool function 本身。

PR-3 ProcessRunner output bounds：
- 当前只限制字符串输出。
- 对 dict/list/任意非字符串大对象也必须在子进程内做 bounded serialization 或 size estimate。
- 大对象不能原样跨 multiprocessing Queue。
- 增加 large dict/list 测试。

PR-4 Cache policy：
- cache read/write 均必须使用同一个 _cache_allowed。
- 默认只缓存 read 工具。
- network cache 必须 idempotent=True + metadata cache_network=True。
- write/destructive 永不默认缓存。

PR-5 Trusted output policy：
- metadata.trusted 不得决定是否 wrap_untrusted。
- 新增 ToolPolicy.trusted_output=False。
- 默认所有工具输出都 redact + wrap_untrusted。
- trusted_output=True 也默认 redaction，不默认绕过 secrets redaction。

PR-6 No-policy execution：
- ToolExecutor 默认拒绝无 ToolPolicy 工具，即使没有 policy_engine。
- 如需兼容 dev，用 allow_unsafe_no_policy_execution=True 显式开启，并发 RuntimeWarning。
- unsafe mode 不属于 Level 2。

PR-7 Deprecate authorize_with_context：
- 加 DeprecationWarning。
- 文档说明它不验证 args/path/url，不是完整 tool authorization。
- 推荐 authorize(tool_def, args, context)。

PR-8 ContainerSandbox cleanup：
- docker run 使用唯一 --name。
- timeout 后显式 docker kill + docker rm -f。
- finally 中兜底 rm -f。
- SandboxResult 记录 killed/container_name。

PR-9 xfail release gate：
- scripts/check_xfail_policy.py 增加 --strict-core。
- release workflow 要求 core xfail = 0。
- 完全半生产 release 前 runtime/tools/security/deepseek/policy/version consistency 不能 xfail。

PR-10 文档 release checklist：
- README/SECURITY/levels.md 写清 Level 2 边界。
- ProcessRunner 是 timeout isolation，不是 sandbox。
- ContainerRunner 只 sandbox 返回 code，不 sandbox tool function，除非使用 declarative spec。
- Level 3/4 不支持。
- CHANGELOG/release checklist 更新。

最终验收：
- pytest 0 failed。
- release workflow core xfail 0。
- code_exec/destructive 无 container 必拒绝。
- runner override 不能弱化隔离。
- 大非字符串输出不能跨进程原样返回。
- non-read tool 不默认 cache。
- metadata.trusted 不绕过 untrusted wrapping。
- no-policy tool 默认拒绝。
```

---

# 5. 最终建议

当前 SeekFlow 已经非常接近完全半生产级，剩下的不是大规模重构，而是**最后一层安全语义硬化**。

最重要的三件事：

1. **任何配置都不能把高风险工具降级到低隔离 runner。**
2. **ContainerRunner 的安全边界必须讲清并在代码中强制。**
3. **所有跨进程、缓存、输出、legacy API 的边界都必须 fail-closed。**

完成这份 RFC 后，SeekFlow 才可以非常有底气地声明：

> **Level 2 完全半生产级 DeepSeek-native secure tool runtime。**
