下面这份是**最终版工程修改方案**。它已经结合了前两份报告、最新公开代码状态，以及 DeepSeek 官方协议要求。可以直接交给 Claude Code 作为执行规格书。

我先强调一个关键修订：**`seekflow.tools.builtins` 现在已经不是完全缺失，而是以 package 形式存在，包含 `filesystem.py`、`network.py`、`python_exec.py`、`sqlite.py`，并在 `__init__.py` 导出了 `make_read_file / make_write_file / make_fetch_url / make_python_exec / make_sqlite_query`。** 但这个实现仍不完整：缺少 `make_calculate`、`make_list_dir`；`allow_filesystem(write=True)` 没有注册 `write_file`；built-in tool policy 没有设置 `path_params/url_params`；`ToolExecutor` 仍未完整执行 `max_input_bytes/max_output_bytes/timeout_s`；runtime 的 file embedding 仍未传 `workspace_root`；DeepSeek adapter 仍没有成为唯一协议入口。当前 `tools/builtins` 目录和导出内容可在仓库中看到。([GitHub][1])

---

# SeekFlow 最终修复与极致化工程方案

## 0. 当前代码状态基线

当前 README 仍宣称 `SeekFlow v0.2.5`、production-grade security 和 620+ tests，但 GitHub 页面显示没有正式 release；PyPI 当前公开版本仍是 `seekflow 0.1.0`。这意味着 `pip install seekflow` 得到的包与 GitHub main 的 `0.2.5` 源码不是同一可信发布物。([GitHub][2])

当前 `pyproject.toml` 已写成 `version = "0.2.5"`，并称项目是 “security-hardened beta”；但同时 mypy strict 打开后又对 `runtime`、`agent`、`retry_executor`、`files`、`cost` 等核心模块设置了 `ignore_errors = true`。这说明“严格类型”仍未真正覆盖最关键主路径。([GitHub][3])

当前 DeepSeek protocol 模块已经是 mode-aware，知道 thinking mode 下 tool-call assistant 需要保留 `reasoning_content`，non-thinking 下不强制；这方向正确。([GitHub][4]) DeepSeek 官方也明确要求：thinking mode 的 tool-call turn 必须回传 `reasoning_content`，否则会 400；并且 DeepSeek V4 thinking mode 不支持 `tool_choice`、不支持 developer role、使用 `max_tokens` 字段、tool-call assistant message 需要非空 content。([DeepSeek API Docs][5])

---

# 1. 总体目标

Claude Code 的任务不是“继续加功能”，而是把 SeekFlow 现有模块打通成一条**可运行、默认安全、DeepSeek 协议正确、成本/cache 可观测、发布可信**的主路径。

最终目标：

```text
SeekFlow = DeepSeek-native lightweight agent runtime

必须做到：
1. 所有公开 API 可 import、可运行；
2. DeepSeek thinking/tool-call 协议 100% 正确；
3. 所有工具执行都经过 ToolExecutor + PolicyEngine；
4. 文件、网络、Python、SQLite 工具不能绕过安全边界；
5. retry、stream、circuit breaker 行为可预测；
6. JSON Output + repair + schema validation 闭环；
7. model / pricing / usage / budget 单一来源；
8. README、pyproject、GitHub release、PyPI 一致；
9. CI 对 import、security、protocol、runtime 主路径有硬测试。
```

---

# 2. 禁止事项

Claude Code 必须遵守：

```text
禁止 1：不要重写整个项目。
禁止 2：不要为了兼容旧行为放宽默认安全。
禁止 3：不要在 DeepSeek thinking mode 下发送 tool_choice。
禁止 4：不要伪造 reasoning_content。
禁止 5：不要压缩带 tool_calls 的 assistant.reasoning_content。
禁止 6：不要让文件/网络/Python/SQLite 工具绕过 ToolExecutor。
禁止 7：不要让 NoSandbox 执行 Python 代码。
禁止 8：不要用 ThreadPoolExecutor timeout 当作安全隔离。
禁止 9：不要在多个文件里硬编码 DeepSeek 价格。
禁止 10：不要在 release 未对齐前继续宣称 production-grade。
```

---

# 3. 提交顺序

建议 Claude Code 严格按 12 个提交做：

```text
commit 01: format codebase and add import smoke tests
commit 02: complete safe builtin tools package
commit 03: fix Agent.allow_* tool registration semantics
commit 04: wire runtime file attachments to workspace_root
commit 05: enforce ToolPolicy limits in ToolExecutor
commit 06: introduce kill-safe execution backend
commit 07: centralize DeepSeekAdapter
commit 08: fix DeepSeek protocol repair/validation across chat/chat_stream/batch
commit 09: harden HTTP, filesystem, Python, SQLite builtins
commit 10: unify model registry, pricing, usage, budget
commit 11: complete JSON Output structured pipeline
commit 12: tests, CI, docs, release truth alignment
```

---

# 4. Commit 01：先格式化与 import smoke tests

当前多个核心文件被压缩成极少行，例如 `types.py`、`policy.py`、`executor.py`、`runtime.py` 等 raw 文件都显示为极少数长行；这会让 review、coverage、traceback、mypy 定位都非常差。([GitHub][6])

## 4.1 先格式化

运行：

```bash
ruff format src tests
ruff check --fix src tests
```

要求：

```text
不要改业务逻辑；
只做格式化和 import 排序；
单独一个 commit。
```

## 4.2 新增 import smoke tests

新增：

```text
tests/test_import_smoke.py
```

内容：

```python
def test_public_imports() -> None:
    import seekflow
    from seekflow import DeepSeekAgent
    from seekflow.client import DeepSeekClient
    from seekflow.runtime import ToolRuntime
    from seekflow.policy import PolicyEngine
    from seekflow.tools.executor import ToolExecutor
    from seekflow.execution.context import ToolExecutionContext
    from seekflow.execution.approval import ApprovalRequest


def test_builtin_factories_import() -> None:
    from seekflow.tools.builtins import (
        make_fetch_url,
        make_python_exec,
        make_read_file,
        make_sqlite_query,
        make_write_file,
    )
```

新增：

```python
def test_no_legacy_import_regressions() -> None:
    import importlib

    for mod in [
        "seekflow.deepseek.protocol",
        "seekflow.deepseek.params",
        "seekflow.security.http",
        "seekflow.files",
        "seekflow.tools.builtins.filesystem",
        "seekflow.tools.builtins.network",
        "seekflow.tools.builtins.python_exec",
        "seekflow.tools.builtins.sqlite",
    ]:
        importlib.import_module(mod)
```

验收：

```bash
pytest tests/test_import_smoke.py -q
```

---

# 5. Commit 02：补全 safe builtin tools package

当前 `seekflow.tools.builtins` 已存在，但只导出五个 factory；`filesystem.py` 中只有 `make_read_file` 和 `make_write_file`，没有 `make_list_dir`；`__init__.py` 也没有导出 `make_calculate`。([GitHub][7])

## 5.1 修改 `src/seekflow/tools/builtins/__init__.py`

最终导出：

```python
from seekflow.tools.builtins.compute import make_calculate
from seekflow.tools.builtins.filesystem import (
    make_list_dir,
    make_read_file,
    make_write_file,
)
from seekflow.tools.builtins.network import make_fetch_url
from seekflow.tools.builtins.python_exec import make_python_exec
from seekflow.tools.builtins.sqlite import make_sqlite_query

__all__ = [
    "make_calculate",
    "make_read_file",
    "make_write_file",
    "make_list_dir",
    "make_fetch_url",
    "make_python_exec",
    "make_sqlite_query",
]
```

## 5.2 新增 `src/seekflow/tools/builtins/compute.py`

实现 AST-safe calculator，不允许 `eval` 执行任意代码：

```python
def make_calculate() -> ToolDefinition:
    @tool(trusted=True)
    def calculate(expression: str) -> str:
        ...

    return calculate.with_policy(
        ToolPolicy(
            capabilities={"compute.basic"},
            risk="read",
            timeout_s=1.0,
            max_input_bytes=10_000,
            max_output_bytes=10_000,
            parallel_safe=True,
        )
    )
```

允许节点：

```text
Expression
BinOp
UnaryOp
Constant
Add/Sub/Mult/Div/FloorDiv/Mod/Pow
USub/UAdd
```

禁止：

```text
Call
Attribute
Subscript
Name
Import
Lambda
Comprehension
```

## 5.3 修改 `filesystem.py`

当前 `make_read_file()` 的 `ToolPolicy` 有 `workspace_root`，但没有设置 `path_params={"path"}`；`make_write_file()` 也没有设置 `path_params={"filename"}`，而且没有 `max_input_bytes/max_output_bytes`。([GitHub][8])

改成：

```python
return read_file.with_policy(
    ToolPolicy(
        capabilities={"filesystem.read"},
        risk="read",
        workspace_root=root,
        path_params=frozenset({"path"}),
        timeout_s=2.0,
        max_input_bytes=100_000,
        max_output_bytes=max_file_bytes,
        parallel_safe=True,
    )
)
```

`write_file`：

```python
return write_file.with_policy(
    ToolPolicy(
        capabilities={"filesystem.write"},
        risk="write",
        workspace_root=root,
        path_params=frozenset({"filename"}),
        timeout_s=5.0,
        max_input_bytes=max_file_bytes + 10_000,
        max_output_bytes=10_000,
        requires_approval=True,
        parallel_safe=False,
    )
)
```

新增 `make_list_dir()`：

```python
def make_list_dir(
    *,
    workspace_root: str | Path,
    max_entries: int = 200,
) -> ToolDefinition:
    root = Path(workspace_root).resolve()

    @tool(trusted=False)
    def list_dir(path: str = ".") -> str:
        target = validate_file_access(
            path,
            workspace_root=root,
            max_bytes=None,
            must_exist=True,
            allow_directory=True,
        )
        entries = []
        for child in sorted(target.iterdir())[:max_entries]:
            entries.append(
                {
                    "name": child.name,
                    "type": "dir" if child.is_dir() else "file",
                    "size": child.stat().st_size if child.is_file() else None,
                }
            )
        return json.dumps(entries, ensure_ascii=False)

    return list_dir.with_policy(
        ToolPolicy(
            capabilities={"filesystem.read"},
            risk="read",
            workspace_root=root,
            path_params=frozenset({"path"}),
            timeout_s=2.0,
            max_input_bytes=10_000,
            max_output_bytes=100_000,
            parallel_safe=True,
        )
    )
```

如果现有 `validate_file_access()` 不支持目录，需要添加 `allow_directory` 参数，或单独实现 `validate_directory_access()`。

## 5.4 修改 `network.py`

当前 `make_fetch_url()` 使用 `fetch_url_hardened()` 是正确方向，但 `ToolPolicy` 没有设置 `url_params={"url"}`。([GitHub][9])

改为：

```python
return fetch_url.with_policy(
    ToolPolicy(
        capabilities={"network.public_http"},
        risk="network",
        allowed_domains=allowed_domains,
        url_params=frozenset({"url"}),
        timeout_s=timeout,
        max_input_bytes=20_000,
        max_output_bytes=max_response_bytes,
        parallel_safe=True,
    )
)
```

并加校验：

```python
if not allowed_domains:
    raise ValueError("make_fetch_url requires non-empty allowed_domains")
```

## 5.5 修改 `python_exec.py`

当前已经拒绝 `NoSandbox`，这是正确的。([GitHub][10]) 但 policy 仍需加 input/output 限制：

```python
ToolPolicy(
    capabilities={"code.exec"},
    risk="code_exec",
    timeout_s=timeout_s,
    max_input_bytes=200_000,
    max_output_bytes=200_000,
    parallel_safe=False,
    requires_approval=True,
)
```

`run_python()` 不要自己吞掉太多上下文，返回结构化结果更好：

```python
return json.dumps(
    {
        "ok": result.ok,
        "stdout": result.stdout[:max_output_bytes],
        "stderr": result.stderr[:50_000],
        "error": result.error,
        "elapsed_ms": result.elapsed_ms,
    },
    ensure_ascii=False,
)
```

## 5.6 修改 `sqlite.py`

当前 SQLite built-in 已经使用 `mode=ro`、`set_authorizer()`、`set_progress_handler()`，这是正确方向。([GitHub][11]) 但需要补：

```python
ToolPolicy(
    capabilities={"filesystem.read", "data.sqlite"},
    risk="read",
    workspace_root=root,
    path_params=frozenset({"db_path"}),
    timeout_s=timeout_s,
    max_input_bytes=100_000,
    max_output_bytes=1_000_000,
    parallel_safe=False,
)
```

SQL 允许：

```text
SELECT
WITH ... SELECT
PRAGMA table_info(...)
PRAGMA index_list(...)
PRAGMA table_list
```

SQL 禁止：

```text
ATTACH
DETACH
INSERT
UPDATE
DELETE
DROP
ALTER
CREATE
REPLACE
VACUUM
.load
PRAGMA writable_schema
```

不要只用 `startswith("SELECT")`。应做粗粒度 tokenizer：

```python
FORBIDDEN_SQL_TOKENS = {
    "ATTACH", "DETACH", "INSERT", "UPDATE", "DELETE",
    "DROP", "ALTER", "CREATE", "REPLACE", "VACUUM",
}
```

并用 sqlite authorizer 作为第二道防线。

## 5.7 测试

新增：

```text
tests/test_builtin_factories.py
```

必须覆盖：

```python
def test_make_calculate_policy() -> None: ...
def test_make_read_file_sets_path_params(tmp_path) -> None: ...
def test_make_write_file_sets_path_params_and_requires_approval(tmp_path) -> None: ...
def test_make_list_dir_blocks_escape(tmp_path) -> None: ...
def test_make_fetch_url_requires_domains() -> None: ...
def test_make_fetch_url_sets_url_params() -> None: ...
def test_make_python_exec_rejects_no_sandbox() -> None: ...
def test_make_sqlite_query_sets_path_params(tmp_path) -> None: ...
```

---

# 6. Commit 03：修复 `DeepSeekAgent.allow_*` 语义

当前 `allow_filesystem(write=True)` 只注册 `make_read_file()`，没有注册 `make_write_file()`；`with_default_tools()` 文档说 dangerous_tools=True 加载 all 11 tools，但实际只是添加 calculate 和 legacy text utils，安全 builtins 需要 allow_* 提前调用。([GitHub][12])

## 6.1 修改 `allow_filesystem()`

当前逻辑：

```python
if write:
    self._allowed_capabilities.add("filesystem.write")
...
self.add_tool(make_read_file(...))
```

修为：

```python
from seekflow.tools.builtins import make_list_dir, make_read_file, make_write_file

if read:
    self.add_tool(
        make_read_file(
            workspace_root=root,
            allowed_extensions=allowed_extensions,
            max_file_bytes=max_file_bytes,
        )
    )
    self.add_tool(make_list_dir(workspace_root=root))

if write:
    self.add_tool(
        make_write_file(
            workspace_root=root,
            max_file_bytes=max_file_bytes,
        )
    )
```

并且：

```python
if not read and not write:
    raise ValueError("allow_filesystem requires read=True or write=True")
```

## 6.2 修改 `with_default_tools()`

不要再宣称 dangerous_tools=True 加载 “all 11 tools”。当前设计更安全的是：

```text
with_default_tools():
  永远只加载 calculate + safe text utils

allow_filesystem():
  显式注册文件工具

allow_network():
  显式注册网络工具

allow_python():
  显式注册 Python 工具

allow_sqlite():
  显式注册 SQLite 工具
```

文档和函数 docstring 改成：

```python
"""Load safe default tools.

Always registers:
- calculate
- parse_csv_str
- extract_entities
- classify_text

Dangerous tools are not loaded here.
Use allow_filesystem/allow_network/allow_python/allow_sqlite explicitly.
"""
```

## 6.3 修改 runtime context

`DeepSeekAgent._make_runtime()` 应把：

```text
dangerous_tools_enabled
allowed_capabilities
allowed_domains
workspace_root
max_risk
sandbox
```

全部传入 `ToolExecutionContext`。

如果 context 当前不支持 `allowed_domains/workspace_root/sandbox`，补字段。

## 6.4 测试

新增：

```text
tests/test_agent_allow_tools.py
```

覆盖：

```python
def test_allow_filesystem_read_registers_read_and_list(tmp_path): ...
def test_allow_filesystem_write_registers_write(tmp_path): ...
def test_allow_network_registers_fetch_url(): ...
def test_allow_python_rejects_no_sandbox(): ...
def test_allow_sqlite_registers_query_sql(tmp_path): ...
def test_with_default_tools_does_not_register_dangerous_tools(): ...
```

---

# 7. Commit 04：runtime 文件附件必须绑定 workspace

当前 `files.py` 已有 `workspace_root` 和 deny globs，默认阻断 `.env`、私钥、证书、云凭据、`.git`、`node_modules`、`.venv`，这是正确的。([GitHub][13]) 但 `ToolRuntime.chat()` 和 `chat_stream()` 调用 `embed_files_into_message(messages[i], files)` 时没有传 `workspace_root`，因此主路径仍能绕过该校验。([GitHub][14])

## 7.1 修改 runtime

新增 helper：

```python
def _workspace_root_or_error(self, files: list[str] | None) -> str | Path | None:
    if not files:
        return None

    root = getattr(self._policy_context, "workspace_root", None)
    if root is None:
        raise PermissionError(
            "File attachments require a workspace_root. "
            "Use DeepSeekAgent.allow_filesystem(root=...) or pass "
            "ToolExecutionContext(workspace_root=...)."
        )
    return root
```

在 `chat()` 和 `chat_stream()` 中：

```python
workspace_root = self._workspace_root_or_error(files)
...
messages[i] = embed_files_into_message(
    messages[i],
    files,
    workspace_root=workspace_root,
)
```

## 7.2 修复 directory expansion

当前 `_resolve_files()` 遇到目录会遍历所有直接子文件，但目录路径在 `workspace_root` 校验之前已经展开；这容易产生边界复杂性。([GitHub][13])

修改为：

```text
先校验用户传入的目录路径在 workspace 内；
再枚举目录；
对每个子文件再次 validate_file_access。
```

## 7.3 测试

新增：

```text
tests/test_runtime_file_attachments_security.py
```

覆盖：

```python
def test_runtime_files_require_workspace_root(): ...
def test_runtime_files_inside_workspace_allowed(tmp_path): ...
def test_runtime_files_block_dotenv(tmp_path): ...
def test_runtime_files_block_private_key(tmp_path): ...
def test_runtime_files_block_symlink_escape(tmp_path): ...
def test_runtime_files_directory_expansion_validates_each_file(tmp_path): ...
def test_chat_stream_files_same_policy_as_chat(tmp_path): ...
```

---

# 8. Commit 05：ToolExecutor 完整执行 ToolPolicy

当前 `ToolExecutor` 注释声称执行顺序包括 policy、approval、sandbox、sanitize、truncate、audit，但实际执行仍使用 `ThreadPoolExecutor`，且没有看到 `policy.max_input_bytes/max_output_bytes` 的硬 enforcement。([GitHub][15])

## 8.1 统一执行顺序

`ToolExecutor.execute()` 必须改成：

```text
1. lookup tool
2. parse / repair arguments
3. dangerous repair confidence gate
4. canonical JSON serialize args
5. enforce policy.max_input_bytes
6. schema coerce / validate
7. PolicyEngine.authorize()
8. approval if required
9. cache lookup after policy
10. execute using ExecutionBackend
11. serialize raw result
12. redact secrets
13. enforce policy.max_output_bytes
14. wrap untrusted output
15. prompt-level truncate with max_result_chars
16. audit record
17. cache set if eligible
```

## 8.2 input bytes

新增：

```python
def _enforce_input_limit(tool_def: ToolDefinition, arguments: dict[str, Any]) -> None:
    policy = tool_def.policy
    if not policy:
        return
    payload = json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > policy.max_input_bytes:
        raise ToolInputTooLargeError(...)
```

## 8.3 output bytes

新增：

```python
def _serialize_tool_result(result: Any) -> str:
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
```

```python
def _enforce_output_limit(tool_def: ToolDefinition, result_text: str) -> str:
    limit = tool_def.policy.max_output_bytes if tool_def.policy else 100_000
    data = result_text.encode("utf-8")
    if len(data) > limit:
        raise ToolOutputTooLargeError(...)
```

不要静默截断作为安全边界；如果为了 UX 截断，必须返回结构化错误：

```json
{
  "error": "tool_output_too_large",
  "max_output_bytes": 100000,
  "actual_output_bytes": 2000000
}
```

## 8.4 timeout

当前有效 timeout 优先读 metadata，再用传入 timeout。应改为：

```python
effective_timeout = (
    tool_def.policy.timeout_s
    if tool_def.policy is not None
    else timeout
)
```

`metadata["timeout"]` 可以作为 legacy，但不得覆盖更严格 policy：

```python
metadata_timeout = tool_def.metadata.get("timeout")
if metadata_timeout is not None:
    effective_timeout = min(effective_timeout, metadata_timeout)
```

## 8.5 audit

Audit record 增加：

```python
input_bytes: int
output_bytes: int
policy_timeout_s: float
capabilities: set[str]
requires_approval: bool
approved: bool | None
```

不要记录明文参数和明文结果，只记录 hash。

## 8.6 测试

新增：

```text
tests/test_tool_executor_policy_limits.py
```

覆盖：

```python
def test_max_input_bytes_enforced(): ...
def test_max_output_bytes_enforced(): ...
def test_policy_timeout_s_used_over_default(): ...
def test_metadata_timeout_cannot_relax_policy_timeout(): ...
def test_approval_required_blocks_without_handler(): ...
def test_approval_denied_prevents_execution(): ...
def test_audit_contains_hashes_not_plaintext(): ...
```

---

# 9. Commit 06：引入 kill-safe execution backend

当前 `ToolExecutor` 用 `ThreadPoolExecutor` 的 timeout 执行工具。Python 线程无法被可靠强杀，所以这不是生产级工具隔离。([GitHub][15])

## 9.1 新增 `src/seekflow/execution/backend.py`

定义：

```python
@dataclass(frozen=True)
class ExecutionLimits:
    timeout_s: float
    max_output_bytes: int
    max_input_bytes: int


@dataclass(frozen=True)
class ExecutionResult:
    ok: bool
    result: Any | None = None
    error: str | None = None
    elapsed_ms: int = 0
    timed_out: bool = False


class ExecutionBackend(Protocol):
    def run_callable(
        self,
        func: Callable[..., Any],
        arguments: dict[str, Any],
        limits: ExecutionLimits,
    ) -> ExecutionResult:
        ...
```

实现两个 backend：

```text
ThreadExecutionBackend:
  仅用于 risk=read 且 capabilities 不含 filesystem/network/code.exec/data.sqlite

ProcessExecutionBackend:
  用 multiprocessing/subprocess，timeout 后 terminate/kill
```

选择逻辑：

```python
def select_backend(policy: ToolPolicy) -> ExecutionBackend:
    if policy.risk == "read" and policy.capabilities <= {"compute.basic"}:
        return ThreadExecutionBackend()
    return ProcessExecutionBackend()
```

但是：

```text
code.exec 不走 run_callable；
code.exec 必须通过 sandbox.execute()。
```

## 9.2 ToolExecutor 路由

```python
if tool_def.policy and "code.exec" in tool_def.policy.capabilities:
    if self.sandbox is None:
        deny
    # 但当前 make_python_exec 已把 sandbox 绑定在 closure 中；
    # 长期应改为 executor 中央调用 sandbox，而不是 closure 自己调用。
```

最终目标：

```python
if "code.exec" in policy.capabilities:
    result = self.sandbox.execute(arguments["code"], timeout=policy.timeout_s)
else:
    result = backend.run_callable(tool_def.func, arguments, limits)
```

## 9.3 sandbox hardening

`ProcessSandbox`：

```text
- clean env
- temp cwd
- timeout 后 kill process group
- no stdin
- no shell=True
- output limit
- Linux 下 resource.setrlimit: CPU, AS, NOFILE, NPROC
```

`ContainerSandbox`：

```bash
--network none
--read-only
--tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m
--cap-drop ALL
--security-opt no-new-privileges
--pids-limit 64
--memory 256m
--cpus 1
--user 65534:65534
--ulimit nofile=64:64
```

## 9.4 测试

新增：

```text
tests/test_execution_backend.py
tests/test_sandbox_hardening.py
```

覆盖：

```python
def test_process_backend_kills_timeout(): ...
def test_thread_backend_only_used_for_compute_basic(): ...
def test_code_exec_requires_sandbox(): ...
def test_container_command_contains_hardening_flags(): ...
```

---

# 10. Commit 07：DeepSeekAdapter 成为唯一 provider 入口

当前已有 `deepseek/params.py`，会处理 thinking extra_body 和 ignored sampling params。([GitHub][16]) 但 runtime、agent、client 仍分散处理 `_apply_thinking_mode()`、model defaults、legacy mapping、usage 等。DeepSeek 兼容逻辑必须集中。

## 10.1 新增 `src/seekflow/deepseek/adapter.py`

定义：

```python
@dataclass(frozen=True)
class ThinkingConfig:
    enabled: bool = True
    effort: Literal["high", "max"] = "high"


@dataclass(frozen=True)
class NormalizedRequest:
    model: str
    messages: list[dict[str, Any]]
    params: dict[str, Any]
    warnings: list[str]


class DeepSeekAdapter:
    def normalize_model(
        self,
        model: str,
        thinking: ThinkingConfig | None,
    ) -> tuple[str, ThinkingConfig]:
        ...

    def normalize_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        thinking: ThinkingConfig,
        repair: bool = True,
    ) -> list[dict[str, Any]]:
        ...

    def build_chat_params(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        thinking: ThinkingConfig,
        response_format: dict[str, Any] | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> NormalizedRequest:
        ...

    def normalize_usage(self, usage: Any) -> Usage:
        ...
```

## 10.2 规则

DeepSeek 官方要求：

```text
supportsDeveloperRole = false
maxTokensField = max_tokens
supportsToolChoice = false in thinking mode
requiresReasoningContentForToolCalls = true
requiresAssistantContentForToolCalls = true
reasoning_effort = high|max
thinking extra_body = {"thinking": {"type": "enabled"}}
```

这些规则来自 DeepSeek 官方 agent integration 文档。([DeepSeek API Docs][17])

实现：

```python
if "max_completion_tokens" in kwargs:
    kwargs["max_tokens"] = kwargs.pop("max_completion_tokens")
```

```python
if thinking.enabled:
    kwargs.setdefault("extra_body", {})
    kwargs["extra_body"]["thinking"] = {"type": "enabled"}
    kwargs["reasoning_effort"] = thinking.effort
    kwargs.pop("tool_choice", None)

    for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
        kwargs.pop(key, None)
else:
    kwargs.setdefault("extra_body", {})
    kwargs["extra_body"]["thinking"] = {"type": "disabled"}
```

DeepSeek 官方 thinking 文档也说明 thinking mode 不支持 temperature、top_p、presence_penalty、frequency_penalty，这些参数无效果。([DeepSeek API Docs][5])

developer role：

```python
if msg["role"] == "developer":
    if strict_provider:
        raise DeepSeekProtocolError("DeepSeek does not support developer role")
    msg = {**msg, "role": "system"}
```

tool-call content：

```python
if msg["role"] == "assistant" and msg.get("tool_calls") and msg.get("content") is None:
    msg["content"] = ""
```

不伪造 reasoning：

```python
if thinking.enabled and assistant_has_tool_calls and not msg.get("reasoning_content"):
    raise DeepSeekProtocolError(...)
```

## 10.3 alias

当前必须统一：

```text
deepseek-chat:
  actual_model = deepseek-v4-flash
  thinking.enabled = False

deepseek-reasoner:
  actual_model = deepseek-v4-flash
  thinking.enabled = True

deepseek-v4-flash:
  actual_model = deepseek-v4-flash
  thinking = user/default

deepseek-v4-pro:
  actual_model = deepseek-v4-pro
  thinking = user/default
```

DeepSeek 官方模型页列出 `deepseek-v4-flash`、`deepseek-v4-pro`，并说明 `deepseek-chat` 和 `deepseek-reasoner` 是兼容别名。([DeepSeek API Docs][18])

## 10.4 runtime/client 接入

删除或降级：

```text
runtime._apply_thinking_mode()
agent.MODEL_DEFAULTS 中的 provider-specific thinking 参数
agent.LEGACY_MODEL_MAP
client 中 scattered usage parsing
```

最终：

```python
adapter = DeepSeekAdapter()
normalized = adapter.build_chat_params(...)
client.chat(**normalized.params)
```

`chat()`、`chat_stream()`、`chat_batch()` 都必须走 adapter。

## 10.5 测试

新增：

```text
tests/deepseek/test_adapter.py
```

覆盖：

```python
def test_thinking_enabled_sets_extra_body_and_effort(): ...
def test_thinking_removes_tool_choice(): ...
def test_thinking_removes_sampling_params(): ...
def test_non_thinking_keeps_tool_choice_if_supported(): ...
def test_developer_role_converted_or_rejected(): ...
def test_max_completion_tokens_maps_to_max_tokens(): ...
def test_deepseek_chat_alias(): ...
def test_deepseek_reasoner_alias(): ...
def test_tool_call_content_none_repaired_to_empty(): ...
def test_missing_reasoning_in_thinking_tool_call_fails_closed(): ...
```

---

# 11. Commit 08：DeepSeek protocol 覆盖 chat / stream / batch

当前 `deepseek/protocol.py` 已经 mode-aware，并提供 `validate_deepseek_messages()` 和 `repair_deepseek_messages()`。([GitHub][4]) 但 runtime 里只调用 validate，没有调用 repair；chat_stream 构造 tool-call assistant 时仍可能 `content=None`；batch path 也没有完整 DeepSeek adapter 和 protocol validation。([GitHub][14])

## 11.1 修改 `chat()`

构造 tool-call assistant：

```python
assistant_msg = {
    "role": "assistant",
    "content": response.content or "",
    "tool_calls": ...
}
```

如果 thinking enabled：

```python
if not response.reasoning_content:
    raise DeepSeekProtocolError(
        "DeepSeek thinking tool-call response missing reasoning_content"
    )
assistant_msg["reasoning_content"] = response.reasoning_content
```

不要继续允许：

```python
"content": response.content
```

因为可能是 `None`。

## 11.2 修改 `chat_stream()`

当前 streaming tool-call assistant：

```python
"content": "".join(current_content) if current_content else None
```

必须改为：

```python
"content": "".join(current_content) if current_content else ""
```

如果 thinking enabled 且有 tool_calls：

```python
if not step_reasoning:
    raise DeepSeekProtocolError("streaming thinking tool-call missing reasoning_content")
assistant_msg["reasoning_content"] = "".join(step_reasoning)
```

## 11.3 修复 early-stop user reminder

当前 runtime 在 tool-call 结果后会插入 user reminder，这是在所有 tool result 之后，协议上可行；但必须确保永远不插入到 assistant tool_calls 和对应 tool messages 之间。当前代码基本是在 tool messages 后插入，但要加测试防回归。([GitHub][14])

## 11.4 修改 `chat_batch()`

batch body 构造必须走 adapter：

```python
normalized = adapter.build_chat_params(
    model=model,
    messages=req["messages"],
    tools=req.get("tools") or tools_schema,
    thinking=...
)
body = normalized.params
```

如果 batch 不支持多轮 tool loop，应明确文档：

```text
chat_batch is single-step only. It may execute returned tool calls locally,
but it does not send tool results back to the model.
```

或改名：

```python
chat_batch_single_step()
```

## 11.5 修复测试语义

当前 `tests/test_deepseek_thinking_protocol.py` 仍把 `validate_deepseek_messages()` 当成会 raise 的函数，但当前实现是返回 `list[ValidationIssue]`。([GitHub][19])

选择一种语义：

推荐保留：

```python
validate_deepseek_messages() -> list[ValidationIssue]
```

新增：

```python
def assert_deepseek_messages_valid(...):
    issues = validate_deepseek_messages(...)
    if errors:
        raise DeepSeekProtocolError(...)
```

测试改为：

```python
issues = validate_deepseek_messages(messages, thinking_enabled=True)
assert any(i.code == "non_tool_after_tool_calls" for i in issues)
```

## 11.6 测试

新增或修复：

```text
tests/deepseek/test_protocol_validator.py
tests/test_runtime_protocol_chat.py
tests/test_runtime_protocol_stream.py
tests/test_runtime_protocol_batch.py
```

覆盖：

```python
def test_thinking_tool_call_requires_reasoning(): ...
def test_non_thinking_tool_call_allows_missing_reasoning_warning(): ...
def test_null_content_repaired_to_empty(): ...
def test_validate_returns_issues_not_raise(): ...
def test_assert_valid_raises(): ...
def test_chat_tool_call_assistant_content_never_none(): ...
def test_stream_tool_call_assistant_content_never_none(): ...
def test_chat_stream_missing_reasoning_fails_closed(): ...
def test_batch_uses_adapter_and_validates_messages(): ...
def test_user_reminder_not_inserted_between_tool_call_and_tool_result(): ...
```

---

# 12. Commit 09：安全模块继续加固

## 12.1 HTTP SSRF

当前 `security/http.py` 已经实现 allowed_domains、HTTPS 默认、端口限制、私网 IP 阻断、redirect 逐跳校验、max_response_bytes。([GitHub][20])

但仍需修：

```python
httpx.Client(..., trust_env=False)
```

当前 client 没有显式设置 `trust_env=False`，可能受环境代理影响。应改：

```python
with httpx.Client(
    follow_redirects=False,
    timeout=policy.timeout_s,
    trust_env=False,
) as client:
```

补充 blocked ranges：

```text
100.64.0.0/10
192.0.0.0/24
198.18.0.0/15
2001:db8::/32
::/128
```

生产 profile 终局：

```text
resolve host
validate every IP
connect to validated IP
preserve Host header and TLS SNI
disable proxy
revalidate every redirect hop
```

## 12.2 legacy `agent.builtins`

当前 `agent/builtins.py` 仍有 legacy `fetch_url()` 使用 `urllib.request.urlopen()`，`run_python()` 直接 `subprocess.run()`，`query_sql()` 仅做简单 SELECT/PRAGMA 前缀判断。([GitHub][21])

这些函数要么移除，要么 hard deprecate：

```python
def fetch_url(*args, **kwargs):
    raise RuntimeError(
        "Unsafe legacy fetch_url is disabled. "
        "Use seekflow.tools.builtins.make_fetch_url()."
    )
```

但为了不破坏 safe text utils，可以保留：

```text
parse_csv_str
extract_entities
classify_text
```

## 12.3 PolicyEngine 默认严格

当前 `PolicyEngine` 对 dict context 和 no context 默认 permissive：`dangerous_enabled=True`、`max_risk="destructive"`。([GitHub][22])

改为：

```python
class PolicyEngine:
    def __init__(self, allow_no_policy: bool = False, mode: Literal["strict", "compat"] = "strict"):
        self._mode = mode
```

strict 默认：

```python
dangerous_enabled = False
allowed_caps = {"read"}
max_risk = "read"
```

compat 才允许旧行为：

```python
if self._mode == "compat":
    dangerous_enabled = True
    max_risk = "destructive"
```

同时修测试。当前 `tests/test_policy.py` 用 `context={}` 期望 read tool allowed、network tool allowed，但 strict 默认下这应该不成立，除非 context 明确授权。([GitHub][23])

新测试应写：

```python
ctx = ToolPolicyContext(
    dangerous_tools_enabled=False,
    allowed_capabilities={"filesystem.read"},
    max_risk="read",
)
```

## 12.4 测试

新增：

```text
tests/test_security_http_hardened.py
tests/test_legacy_builtins_disabled.py
tests/test_policy_strict_mode.py
```

覆盖：

```python
def test_http_client_trust_env_false(monkeypatch): ...
def test_blocks_cgnat_ip(): ...
def test_blocks_userinfo(): ...
def test_redirect_to_private_ip_blocked(): ...
def test_legacy_fetch_url_disabled(): ...
def test_legacy_run_python_disabled(): ...
def test_policy_no_context_denies_network(): ...
def test_policy_strict_requires_explicit_capabilities(): ...
def test_policy_compat_preserves_legacy_if_requested(): ...
```

---

# 13. Commit 10：统一 ModelRegistry / Pricing / Usage / Budget

当前 `DeepSeekClient` 仍手写 usage dict，包含 prompt/cache details 的兼容逻辑。([GitHub][24]) 当前 agent 也有 pricing/model defaults 残留。([GitHub][12])

## 13.1 单一来源

保留：

```text
src/seekflow/models.py
src/seekflow/usage.py
src/seekflow/budget.py
```

删除或改造：

```text
agent.py 中 PRICING / MODEL_DEFAULTS / LEGACY_MODEL_MAP
cost.py 中重复 PRICING
budget.py 中重复 _PRICING
deepseek/models.py 中重复 pricing
```

## 13.2 ModelSpec

```python
@dataclass(frozen=True)
class PricingSpec:
    input_cache_hit_per_1m: Decimal
    input_cache_miss_per_1m: Decimal
    output_per_1m: Decimal
    currency: Literal["USD"]
    effective_at: date
    source: str


@dataclass(frozen=True)
class ModelSpec:
    id: str
    provider: Literal["deepseek"]
    context_length: int
    max_output_tokens: int
    supports_thinking: bool
    supports_tool_calls: bool
    supports_json_output: bool
    supports_context_caching: bool
    supports_fim_non_thinking_only: bool
    pricing: PricingSpec
```

DeepSeek 官方模型页说明 V4 Flash / Pro 是当前模型，context window 1,000,000，maxTokens 384,000，支持 tool calls、JSON Output、Context Caching；FIM 是 non-thinking 特性。([DeepSeek API Docs][17])

## 13.3 Usage

```python
@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    prompt_cache_hit_tokens: int = 0
    prompt_cache_miss_tokens: int = 0
    reasoning_tokens: int = 0
```

所有入口：

```python
usage = normalize_usage(response.usage)
```

不要再各处手写解析。

## 13.4 Budget preflight

请求前：

```python
estimated = estimator.estimate(
    model=model,
    input_tokens=token_counter(messages),
    max_output_tokens=max_tokens,
    cache_hit_ratio_estimate=cache_predictor.estimate(...),
)
budget.check_preflight(estimated)
```

请求后：

```python
actual = registry.price_usage(model, usage)
budget.record_actual(actual)
```

## 13.5 测试

新增：

```text
tests/test_model_registry.py
tests/test_usage_normalization.py
tests/test_budget_preflight.py
```

覆盖：

```python
def test_deepseek_chat_alias_flash_non_thinking(): ...
def test_deepseek_reasoner_alias_flash_thinking(): ...
def test_v4_pro_explicit_not_alias(): ...
def test_usage_parses_prompt_cache_hit_miss_top_level(): ...
def test_usage_parses_nested_prompt_tokens_details(): ...
def test_budget_blocks_before_request(): ...
def test_actual_cost_uses_hit_miss_separately(): ...
```

---

# 14. Commit 11：JSON Output structured pipeline

DeepSeek 官方 JSON Output 要求设置 `response_format={"type":"json_object"}`，并在 prompt 中明确要求 JSON 和给出示例；官方还提示 JSON Output 可能返回 empty content。([DeepSeek API Docs][25])

## 14.1 新增统一入口

新增：

```text
src/seekflow/structured_output.py
```

API：

```python
def structured_output(
    client: DeepSeekClient | ToolRuntime,
    *,
    model: str,
    messages: list[dict[str, Any]],
    schema: type[BaseModel] | dict[str, Any],
    thinking: ThinkingConfig | None = None,
    max_repair_attempts: int = 1,
    max_reemit_attempts: int = 1,
) -> StructuredOutputResult:
    ...
```

流程：

```text
1. Normalize schema。
2. Build system instruction：必须包含 "json"。
3. Add compact example。
4. Set response_format={"type": "json_object"}。
5. Call through DeepSeekAdapter。
6. If empty content，retry once with explicit correction。
7. json.loads。
8. Pydantic / jsonschema validate。
9. Mechanical repair。
10. Validate again。
11. Model re-emit once。
12. Fail closed with raw redacted output。
```

## 14.2 Tool argument repair

危险工具参数 repair：

```python
if policy.risk in {"write", "network", "code_exec", "destructive"}:
    if repair_confidence < 0.95:
        deny
```

当前 `ToolExecutor` 已有 `DANGEROUS_REPAIR_CONFIDENCE_THRESHOLD = 0.95`，保持统一。([GitHub][15])

## 14.3 测试

新增：

```text
tests/test_structured_output.py
tests/test_json_repair_pipeline.py
```

覆盖：

```python
def test_response_format_json_object_set(): ...
def test_prompt_contains_json_and_example(): ...
def test_empty_content_retries_once(): ...
def test_repair_then_schema_validate(): ...
def test_reemit_then_validate(): ...
def test_fail_closed_returns_structured_error(): ...
def test_dangerous_tool_low_confidence_repair_denied(): ...
```

---

# 15. Commit 12：CI、README、release 对齐

## 15.1 README 降级或发布

当前 README 顶部仍写 production-grade security 和 620+ tests，同时 GitHub 无 release、PyPI 为 0.1.0。([GitHub][2])

二选一：

### 方案 A：尚未发布 0.2.5

README 顶部改为：

```text
SeekFlow v0.2.5-dev

Status:
- main branch: security-hardening beta
- PyPI stable: 0.1.0
- production use: not recommended until v0.2.5 release and security checklist pass
```

删除：

```text
Production-grade security
620+ tests
```

改为：

```text
Security-hardening beta
Test suite in progress
```

### 方案 B：正式发布 0.2.5

必须完成：

```text
1. ruff check src tests
2. mypy src/seekflow
3. pytest -q
4. build wheel
5. install wheel in clean venv
6. import smoke pass
7. GitHub tag v0.2.5
8. GitHub release v0.2.5
9. PyPI publish 0.2.5
10. Trusted Publishing enabled
```

## 15.2 CI

新增 `.github/workflows/ci.yml`：

```yaml
name: ci

on:
  push:
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: python -m pip install -U pip
      - run: pip install -e ".[dev]"
      - run: ruff format --check src tests
      - run: ruff check src tests
      - run: mypy src/seekflow
      - run: pytest -q
```

## 15.3 逐步移除 mypy ignore

第一批必须移除：

```text
seekflow.files
seekflow.retry_executor
seekflow.cost
```

第二批：

```text
seekflow.runtime
seekflow.agent.*
seekflow.mcp.*
```

---

# 16. 必须新增/修复的测试总表

Claude Code 必须新增或修复：

```text
tests/test_import_smoke.py
tests/test_builtin_factories.py
tests/test_agent_allow_tools.py
tests/test_runtime_file_attachments_security.py
tests/test_tool_executor_policy_limits.py
tests/test_execution_backend.py
tests/test_sandbox_hardening.py
tests/deepseek/test_adapter.py
tests/deepseek/test_protocol_validator.py
tests/test_runtime_protocol_chat.py
tests/test_runtime_protocol_stream.py
tests/test_runtime_protocol_batch.py
tests/test_security_http_hardened.py
tests/test_legacy_builtins_disabled.py
tests/test_policy_strict_mode.py
tests/test_model_registry.py
tests/test_usage_normalization.py
tests/test_budget_preflight.py
tests/test_structured_output.py
tests/test_json_repair_pipeline.py
```

必须修复现有：

```text
tests/test_deepseek_thinking_protocol.py
tests/test_policy.py
```

当前 deepseek protocol test 仍把 `validate_deepseek_messages()` 当成会 raise 的函数，但实现是返回 issues。([GitHub][19]) 当前 policy test 仍用 `context={}` 期望一些危险能力通过，这与目标 strict default 冲突。([GitHub][23])

---

# 17. Claude Code 可直接执行的最终任务说明

把下面这段直接交给 Claude Code：

```text
你要修复 WYZAAACCC/SeekFlow。不要重写整个项目，按闭环主路径修复。

当前状态：
- tools/builtins 已是 package，不是完全缺失；
- 但 builtins 不完整，缺 make_calculate/make_list_dir；
- allow_filesystem(write=True) 没注册 write_file；
- builtins 的 ToolPolicy 缺 path_params/url_params；
- ToolExecutor 未强制 max_input_bytes/max_output_bytes/timeout_s；
- ToolExecutor 仍用 ThreadPoolExecutor timeout，不是 kill-safe；
- runtime chat/chat_stream files=... 没传 workspace_root；
- PolicyEngine no context / dict context 默认过宽；
- DeepSeekAdapter 还不是唯一 provider 参数入口；
- chat_stream 和 batch 仍未完全走 DeepSeek protocol repair/validation；
- client.chat(stream=True) 参数语义不清；
- legacy agent.builtins 仍有 unsafe fetch_url/run_python/query_sql；
- model/pricing/usage/budget 多处重复；
- README/pyproject/GitHub release/PyPI 不一致。

按以下顺序修：

1. ruff format src tests，新增 import smoke tests。
2. 补全 seekflow.tools.builtins：
   - make_calculate
   - make_read_file
   - make_write_file
   - make_list_dir
   - make_fetch_url
   - make_python_exec
   - make_sqlite_query
   所有 factory 必须返回带完整 ToolPolicy 的 ToolDefinition。
3. 修 Agent.allow_*：
   - allow_filesystem(read=True) 注册 read_file + list_dir；
   - allow_filesystem(write=True) 注册 write_file；
   - allow_network 注册 fetch_url；
   - allow_python 拒绝 NoSandbox；
   - allow_sqlite 注册 query_sql；
   - with_default_tools 不再宣称加载危险工具。
4. runtime file attachments：
   - chat/chat_stream 传 workspace_root；
   - 没有 workspace_root 时 files=... 直接 PermissionError；
   - .env/key/cert/cloud creds/symlink escape 必须被阻断。
5. ToolExecutor：
   - enforce max_input_bytes；
   - enforce max_output_bytes；
   - enforce policy.timeout_s；
   - approval required 时无 handler 必须阻断；
   - audit 只记 hash，不记明文；
   - max_result_chars 只做 prompt 截断，不是安全边界。
6. ExecutionBackend：
   - read/compute 可 thread；
   - filesystem/network/sqlite 用 kill-safe backend 或强 timeout；
   - code.exec 必须 sandbox；
   - NoSandbox 不允许执行。
7. DeepSeekAdapter：
   - 统一 model alias；
   - deepseek-chat -> deepseek-v4-flash non-thinking；
   - deepseek-reasoner -> deepseek-v4-flash thinking；
   - thinking 下 extra_body.thinking enabled；
   - reasoning_effort high/max；
   - thinking 下移除 tool_choice 和 sampling params；
   - developer role 转 system 或 strict reject；
   - max_completion_tokens -> max_tokens；
   - assistant tool_calls content None -> ""；
   - thinking tool_calls 缺 reasoning_content fail closed。
8. runtime protocol：
   - chat/chat_stream/chat_batch 全部走 adapter；
   - 每次请求前 repair_deepseek_messages + validate；
   - 不伪造 reasoning_content；
   - 不压缩 tool-call assistant reasoning_content；
   - user reminder 不得插入 assistant tool_calls 和 tool results 中间。
9. Retry/circuit：
   - 保留 DeepSeekAPIError retry；
   - stream 已 yield 后禁止 retry；
   - CircuitBreaker.record_success 在 CLOSED 状态也清零 failure_count；
   - 400/401/402/403/404 不计入 breaker。
10. Security：
   - httpx.Client trust_env=False；
   -补 SSRF blocked ranges；
   - legacy agent.builtins.fetch_url/run_python/query_sql 禁用或转发安全 builtins；
   - SQLite readonly 使用 mode=ro + authorizer + progress_handler；
   - SQL 禁止 ATTACH/INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/VACUUM。
11. Model/cost/usage/budget：
   - 单一 ModelRegistry；
   - 单一 Usage normalization；
   - 删除 agent/cost/budget 多处 pricing；
   - budget preflight 接入 runtime；
   - cost actual 使用 cache hit/miss 分开计算。
12. JSON Output：
   - response_format={"type":"json_object"}；
   - prompt 必须包含 json 和 schema/example；
   - empty content retry once；
   - parse -> validate -> repair -> validate -> reemit -> fail closed。
13. Docs/release：
   - 如果不发布 0.2.5，README 降级为 security-hardening beta；
   - 如果发布，必须 GitHub tag/release/PyPI/Trusted Publishing/CI 全部对齐。

必须通过：
ruff format --check src tests
ruff check src tests
mypy src/seekflow
pytest -q

不要为了让测试通过放宽默认安全。
```

---

# 18. Definition of Done

项目只有满足下面条件，才能称为 `production-hardened beta`：

```text
Import:
  - 所有 public imports 正常；
  - clean wheel install 后 import smoke pass。

DeepSeek:
  - thinking tool-call reasoning_content 完整回传；
  - thinking 下绝不发送 tool_choice；
  - assistant tool-call content 永不为 None；
  - developer role 不进入 DeepSeek 请求；
  - max_tokens 字段正确；
  - chat/chat_stream/chat_batch 都走 adapter。

Tools:
  - builtins 完整；
  - allow_* 立即注册正确工具；
  - ToolPolicy path_params/url_params 完整；
  - ToolExecutor 强制 input/output/timeout/approval；
  - code.exec 必须 sandbox。

Security:
  - files 必须 workspace_root；
  - .env/key/cert/cloud creds/symlink escape blocked；
  - HTTP SSRF tests pass；
  - trust_env=False；
  - legacy unsafe builtins disabled；
  - SQLite readonly hardened。

Reliability:
  - retry bounded；
  - stream yield 后不 retry；
  - circuit breaker success clears failures；
  - non-retryable errors 不污染 breaker。

Cost/cache:
  - model registry 单一来源；
  - usage normalization 单一入口；
  - cache hit/miss 成本分离；
  - budget preflight hard stop。

Release:
  - README 与真实状态一致；
  - pyproject version、GitHub tag、GitHub release、PyPI version 一致；
  - CI 全绿；
  - mypy ignore 不覆盖核心主路径。
```

---

# 19. 最终判断

当前 SeekFlow 已经朝正确方向更新：`tools/builtins` package、DeepSeek protocol validator、strict HTTP、file deny globs、retry 对 `DeepSeekAPIError` 的处理、stream yield 后不 retry，这些都是进步。([GitHub][7])

但它仍没有完成生产主路径闭环。最应优先修的不是新功能，而是：

```text
1. 完整 safe builtins；
2. Agent.allow_* 语义正确；
3. runtime files workspace_root；
4. ToolExecutor policy enforcement；
5. kill-safe execution；
6. DeepSeekAdapter 唯一入口；
7. protocol repair/validation 覆盖 chat/stream/batch；
8. release/README/PyPI 对齐。
```

真正做到极致后的 SeekFlow 应该只有一句话定位：

> **DeepSeek V4 thinking/tool-call 协议绝对正确、工具执行默认安全、prompt-cache 和成本可观测且可控、足够轻量到能嵌入任何 Python 项目的 agent runtime。**

[1]: https://github.com/WYZAAACCC/SeekFlow/tree/main/src/seekflow/tools "SeekFlow/src/seekflow/tools at main · WYZAAACCC/SeekFlow · GitHub"
[2]: https://github.com/WYZAAACCC/SeekFlow "GitHub - WYZAAACCC/SeekFlow: DeepSeek-native agent framework with production-grade reliability · GitHub"
[3]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/pyproject.toml "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/deepseek/protocol.py "raw.githubusercontent.com"
[5]: https://api-docs.deepseek.com/guides/thinking_mode "Thinking Mode | DeepSeek API Docs"
[6]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/types.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/builtins/__init__.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/builtins/filesystem.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/builtins/network.py "raw.githubusercontent.com"
[10]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/builtins/python_exec.py "raw.githubusercontent.com"
[11]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/builtins/sqlite.py "raw.githubusercontent.com"
[12]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/agent/agent.py "raw.githubusercontent.com"
[13]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/files.py "raw.githubusercontent.com"
[14]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/runtime.py "raw.githubusercontent.com"
[15]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/executor.py "raw.githubusercontent.com"
[16]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/deepseek/params.py "raw.githubusercontent.com"
[17]: https://api-docs.deepseek.com/quick_start/agent_integrations/oh_my_pi "Using DeepSeek with Oh My Pi | DeepSeek API Docs"
[18]: https://api-docs.deepseek.com/quick_start/pricing "Models & Pricing | DeepSeek API Docs"
[19]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/tests/test_deepseek_thinking_protocol.py "raw.githubusercontent.com"
[20]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/security/http.py "raw.githubusercontent.com"
[21]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/agent/builtins.py "raw.githubusercontent.com"
[22]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/policy.py "raw.githubusercontent.com"
[23]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/tests/test_policy.py "raw.githubusercontent.com"
[24]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/client.py "raw.githubusercontent.com"
[25]: https://api-docs.deepseek.com/guides/json_mode "JSON Output | DeepSeek API Docs"
