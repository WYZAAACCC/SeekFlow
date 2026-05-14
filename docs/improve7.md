# SeekFlow 最新更新后深度代码审计报告

## 0. 最终结论

这次更新**确实比上一轮更接近正确架构**：同步 `chat()`、`chat_stream()`、`chat_batch()` 和 `AsyncToolRuntime` 都已经开始传入 `policy_engine` / `policy_context`；`PolicyEngine.authorize()` 也已接受 `context`，并开始检查 `dangerous_tools_enabled`、`max_risk`、capabilities、workspace、network、sandbox；Agent 的 `allow_*` API 现在会立即注册安全工具 factory；MCP 也开始为 server 派生 `ToolPolicy`。这些都是实质进步，不是表面改动。([GitHub][1])

但当前版本仍然**不能称为生产级**。最大的风险已经从“安全模块没接线”变成“安全链路存在，但若干关键点仍会崩溃、绕过或产生错误安全假象”。最严重的是：`ToolExecutor` 的 approval 分支引用未定义变量 `policy`，一旦配置 approval handler 并执行需要审批的工具，会直接 `NameError`；MCP 手动 subprocess 在 env 为空时仍会继承父进程环境；MCP 注册名与执行解析逻辑不一致；DeepSeek usage/cost/pricing 仍未统一，成本结果不可信；文件访问校验还有相对路径 bug；ThreadPool timeout 仍不是安全边界。([GitHub][2])

我的判断：

> **SeekFlow 已经进入“Enforcement Core 半闭环”阶段，但仍是 security-hardening beta，不适合直接用于不可信工具执行、企业内网 Agent、MCP 插件系统或代码执行型生产环境。**

---

# 1. 这次更新做对了什么

## 1.1 Policy/context 主链路显著改善

`ToolRuntime.__init__()` 现在默认创建 `PolicyEngine()` 和 `ToolExecutionContext.conservative()`，并在同步 `chat()` 创建 `ToolExecutor` 时传入 `policy_engine`、`context`、`approval_handler`、`sandbox`。这比早期“policy 只是旁路模块”的状态强很多。([GitHub][3])

更重要的是，`chat_stream()` 和 `chat_batch()` 现在也传入了同样的 policy/context，不再像上一轮那样明显绕过同步路径安全边界。`AsyncToolRuntime` 也已接收 `policy_engine`、`policy_context` 并传给 `ToolExecutor`。([GitHub][3])

评价：**方向正确，属于重大进步。**

---

## 1.2 PolicyEngine 已开始执行风险、capability、workspace、sandbox gate

`PolicyEngine.authorize()` 已经支持 dataclass-style context，会读取 `dangerous_tools_enabled`、`allowed_capabilities`、`max_risk`，并拒绝无 policy 工具；它还检查 code execution sandbox、filesystem workspace、network allowed domains、path safe join、approval requirement。([GitHub][1])

评价：**方向正确，但 network 校验仍太弱，approval 执行分支有崩溃 bug。**

---

## 1.3 Agent capability profile 已经从“只存配置”变成“立即注册工具”

`allow_filesystem()` 现在会立即注册 `make_read_file()`，`allow_network()` 会立即注册 `make_fetch_url()`，`allow_python()` 会立即注册 `make_python_exec()`，`allow_sqlite()` 会立即注册 `make_sqlite_query()`，并且会调用 `_invalidate_runtime()`。这修复了之前“必须先 allow 再 with_default_tools，否则工具不生效”的核心问题。([GitHub][4])

评价：**正确，但 profile 参数仍有丢失，runtime 复用 key 仍过粗。**

---

## 1.4 safe builtin factories 比旧工具安全很多

新的文件工具绑定 workspace root、文件大小、扩展名限制；网络工具使用 `fetch_url_hardened()`；Python 执行要求非 `NoSandbox`；SQLite 工具使用只读 URI、workspace-bound path、authorizer、progress handler 和 max rows。([GitHub][5])

评价：**这是正确方向，但底层安全 primitive 还要继续加固。**

---

## 1.5 DeepSeek strict schema、thinking、FIM 都有进步

`ToolRegistry.to_deepseek_tools(strict=True)` 现在会使用 strict schema compiler，并设置 function `"strict": true`；DeepSeek API 文档要求 function name 只允许字母、数字、下划线、短横线、最大 64 字符，并支持 tool strict mode。([GitHub][6])

`fim.py` 已经对 `max_tokens > 4096` 抛错；DeepSeek pricing 页面也说明 FIM 是 non-thinking mode only。([GitHub][7])

评价：**strict 和 FIM 方向正确，但仍缺 model capability/non-thinking guard，usage/cost 还没有真正对齐官方字段。**

---

# 2. P0 级问题：必须立即修复

## P0-1：approval handler 分支会直接 `NameError`

`ToolExecutor.execute()` 中，当 `decision.requires_approval` 且 `approval_handler is not None` 时，会构造 `ApprovalRequest`，但里面引用了未定义变量 `policy`：

```python
risk=policy.risk if tool_def.policy else "destructive",
capability=policy.capabilities if tool_def.policy else set(),
```

在该作用域内没有 `policy = ...`。因此，任何需要审批且配置了 approval handler 的工具都会直接崩溃。典型受影响工具包括 `write_file` 和 `run_python`，因为它们默认 `requires_approval=True`。([GitHub][2])

这会造成一个很糟糕的生产行为：没有 approval handler 时能 fail-closed；一旦用户按文档配置 handler，反而运行时崩溃。

修复：

```python
policy = tool_def.policy or _DEFAULT_UNTRUSTED_POLICY

approval = self.approval_handler.request_approval(
    ApprovalRequest(
        tool=tool_def,
        arguments=arguments if isinstance(arguments, dict) else {},
        reason=decision.reason,
        risk=policy.risk,
        capability=policy.capabilities,
        run_id=getattr(self.context, "run_id", None) if self.context else None,
    )
)
```

必须新增测试：

```text
test_requires_approval_without_handler_denied
test_requires_approval_with_handler_approved_executes
test_requires_approval_with_handler_rejected_denies
test_approval_branch_does_not_raise_nameerror
```

---

## P0-2：MCP manual subprocess 在默认情况下仍可能继承全部环境变量

`MCPServerConfig` 已有 `env_allowlist`，但 manual subprocess path 中构造 `mcp_env` 后，如果它为空，会传 `env=None` 给 `subprocess.Popen()`。在 Python 中，`env=None` 表示继承父进程环境，所以默认情况下 MCP server 仍可拿到 `DEEPSEEK_API_KEY`、云凭证、数据库连接串等敏感信息。([GitHub][8])

当前代码：

```python
env=mcp_env if mcp_env else None
```

应改成：

```python
env=mcp_env  # even if empty
```

或者保留最小白名单：

```python
env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
```

但不能继承全部 env。

同时 SDK path 已经调用 `cfg.to_stdio_params()`，但 `to_stdio_params()` 直接返回 `env=self.env if self.env else None`，没有应用 `env_allowlist`。这意味着 SDK path 也没有真正执行 allowlist 策略。([GitHub][9])

修复要求：

```text
MCP env 默认空
显式 cfg.env 可传，但必须经过 allowlist/安全策略
SDK path 和 manual path 使用同一个 build_safe_env()
禁止默认继承 os.environ
敏感 key 自动 redaction / deny
```

---

## P0-3：MCP 注册名与执行解析逻辑不一致

MCP 注册工具时使用：

```python
full_name = f"{cfg.name}__{name}"
```

但 `MCPToolExecutor._parse_tool_name()` 仍然按 `"."` split；如果外部直接调用 `execute_sync(ToolCall(name="server__tool"))`，会解析成 `("", "server__tool")`，找不到 server。主 runtime 通过 wrapper closure 执行时可能不触发这个 bug，但 MCP executor 的直接 API 是坏的。([GitHub][8])

此外，`_mcp_exec.__name__` 仍设置成 `f"{server_name}.{tool_name}"`，这与 DeepSeek function name 规范冲突；DeepSeek 要求 function name 只能包含字母、数字、下划线和短横线，最大 64 字符。([GitHub][8])

修复：

```python
def sanitize_tool_name(server: str, tool: str) -> str:
    raw = f"{server}__{tool}"
    name = re.sub(r"[^A-Za-z0-9_-]", "_", raw)
    return name[:64]
```

并维护映射：

```python
deepseek_tool_name -> (server_name, original_tool_name)
```

不要通过 split 反推。

---

## P0-4：ToolRegistry 非 strict 模式不校验 function name 字符合法性

`ToolRegistry.to_deepseek_tools()` 只检查 tool name 长度是否超过 64，没有检查字符集；strict checker 会检查，但非 strict 模式同样会把非法 name 发给 DeepSeek API。DeepSeek API 文档明确要求 function name 只能是 a-z、A-Z、0-9、下划线或短横线，最大 64。([GitHub][6])

修复应放在 registry 层，而不是只放 strict checker：

```python
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

if not _NAME_RE.fullmatch(td.name):
    raise ToolSchemaError(
        f"Tool name '{td.name}' is invalid for DeepSeek. "
        "Use letters, digits, underscores, and hyphens only."
    )
```

这也能提前拦截 MCP 生成的非法工具名。

---

## P0-5：ToolExecutor 仍用 ThreadPoolExecutor 作为 timeout 边界

工具执行仍使用：

```python
with ThreadPoolExecutor(max_workers=1) as pool:
    future = pool.submit(tool_def.func, **arguments)
    raw_result = future.result(timeout=effective_timeout)
```

这不是强制隔离。Python 线程超时不能杀死正在运行的函数；而且 `with ThreadPoolExecutor(...)` 退出时可能等待线程结束。对纯计算工具还能接受，对文件、网络、SQL、MCP、代码执行都不能作为安全边界。([GitHub][2])

修复方向：

| 工具风险                   | 推荐执行器                              |
| ---------------------- | ---------------------------------- |
| `read` 且 trusted/pure  | thread                             |
| filesystem/network/sql | process wrapper 或受控 client timeout |
| MCP                    | sandboxed subprocess + kill tree   |
| code.exec              | ContainerSandbox / nsjail / gVisor |
| destructive/write      | approval + process isolation       |

---

# 3. P1 级问题：安全闭环仍需补强

## P1-1：`validate_file_access()` 仍有相对路径 bug

`validate_file_access()` 先执行 `Path(path).exists()`，再执行 `safe_join(workspace_root, str(path))`。如果 workspace 是 `/workspace/project`，用户传 `"data.txt"`，而进程 cwd 不是该 workspace，即使 `/workspace/project/data.txt` 存在，也会被错误地判定为不存在。([GitHub][10])

修复顺序必须改成：

```python
resolved = safe_join(workspace_root, str(path))
if not resolved.exists():
    raise FileNotFoundError(...)
```

正确安全顺序是：

```text
先解析到 workspace 内
再 exists/stat/ext/filename/size
```

---

## P1-2：Network policy 的授权检查弱于实际 fetch hardener

`make_fetch_url()` 使用 `fetch_url_hardened()`，这是好事；但 `PolicyEngine.authorize()` 对 network 工具只做了 `hostname not in domains` 的精确字符串检查，没有使用 `validate_url_strict()`，也不支持安全子域匹配、IDNA normalize、端口限制、scheme 限制。([GitHub][1])

对内置 `fetch_url`，工具执行时还能再挡一层；但对自定义 network 工具，`PolicyEngine` 本身并不能提供完整 SSRF 防护。

修复：

```python
if "network.public_http" in policy.capabilities:
    domains = policy.allowed_domains or context.allowed_domains
    if not domains:
        deny("network.public_http requires allowed_domains")
    validate_url_strict(args["url"], NetworkPolicy(allowed_domains=domains))
```

并且 `validate_url_strict()` 应成为 policy 层和工具层的共同 primitive。

---

## P1-3：SSRF hardener 仍存在 TOCTOU 与 urllib redirect 风险

`security/http.py` 已经比旧 `validate_url()` 强很多，但如果实现仍基于 `urllib.request.urlopen()`，需要注意：urllib 默认会自动处理重定向；如果没有禁用自动 redirect，就无法保证每一跳都先校验再连接。此外，DNS 校验和实际连接分离，仍存在 DNS rebinding / TOCTOU 风险。([GitHub][11])

建议改成 `httpx.Client(follow_redirects=False)`，手动逐跳校验，并 stream 读取响应：

```python
with httpx.Client(follow_redirects=False, timeout=policy.timeout_s) as client:
    for _ in range(policy.max_redirects + 1):
        validate_url_strict(current, policy)
        with client.stream("GET", current) as resp:
            if resp.is_redirect:
                current = urljoin(current, resp.headers["location"])
                continue
            ...
```

更高安全级别下，应固定连接到已校验 IP，并设置 Host header，减少 DNS rebinding 窗口。

---

## P1-4：Agent profile 参数仍有丢失

Agent 的 `allow_network()` 接收 `https_only`、`max_response_bytes`，但注册 `make_fetch_url()` 时只传了 `allowed_domains=domains`，没有传 `https_only` 和 `max_response_bytes`。`allow_filesystem()` 已传 `allowed_extensions` 和 `max_file_bytes`，但 `allow_sqlite(readonly=True)` 的 `readonly` 参数没有实际使用；`allow_python(timeout_s)` 已传入 factory。([GitHub][4])

修复：

```python
self.add_tool(make_fetch_url(
    allowed_domains=domains,
    https_only=https_only,
    max_response_bytes=max_response_bytes,
))
```

并用 profile dataclass 保存完整配置，避免零散字段继续漂移：

```python
@dataclass
class NetworkProfile:
    domains: set[str]
    https_only: bool
    max_response_bytes: int
```

---

## P1-5：runtime 复用条件仍只看 tool names

`DeepSeekAgent._make_runtime()` 复用 runtime 的条件是 registered tool names 与需要的 tool names 相等。它没有比较 workspace root、allowed domains、capabilities、max risk、sandbox、approval handler、strict mode 等安全 profile。虽然 `allow_*()` 会调用 `_invalidate_runtime()`，但如果用户直接修改内部字段，或者未来增加 profile update API，很容易复用 stale context。([GitHub][4])

建议 runtime cache key 包含安全 fingerprint：

```python
runtime_key = hash((
    tuple(sorted(tool_names)),
    tuple(sorted(allowed_capabilities)),
    tuple(sorted(allowed_domains)),
    str(workspace_root),
    max_risk,
    getattr(sandbox, "name", None),
    strict,
))
```

---

## P1-6：非字符串工具结果仍没有统一 UntrustedContent 包装

`ToolExecutor` 只在 `raw_result` 是 `str` 时包装 untrusted output。若工具返回 dict/list，结果不会经过 `wrap_untrusted()`，但外部数据一样可能包含 prompt injection。([GitHub][2])

修复：

```python
trusted = (tool_def.metadata or {}).get("trusted", False)
if not trusted:
    if isinstance(raw_result, str):
        content = raw_result
    else:
        content = json.dumps(raw_result, ensure_ascii=False, default=str)
    raw_result = wrap_untrusted(tool_call.name, content).format_for_model()
```

---

## P1-7：工具参数缺少 jsonschema validation

DeepSeek 文档明确提醒：tool call arguments 是模型生成的 JSON，模型可能生成无效 JSON，也可能 hallucinate 参数；开发者必须在调用函数前验证参数。([DeepSeek API Docs][12])

SeekFlow 当前有 JSON repair 和 `coerce_arguments()`，但没有看到执行前使用 `jsonschema` 校验 `tool_def.parameters`。这意味着 extra properties、enum、minimum、pattern 等约束可能不会被强制执行。([GitHub][2])

正确顺序：

```text
parse
→ repair
→ jsonschema validate
→ coerce
→ jsonschema validate again
→ policy authorize
→ approval
→ execute
```

高危工具 repair 后参数置信度应保持 `>= 0.95`，当前常量是 0.95，但错误信息仍写 0.85，文档/提示应统一。([GitHub][2])

---

# 4. DeepSeek 适配问题

## 4.1 usage normalizer 仍未成为全链路唯一入口

项目新增了 `NormalizedUsage` 和 `normalize_usage()`，但它只读取 `prompt_tokens_details.prompt_cache_hit_tokens`、`prompt_tokens_details.prompt_cache_miss_tokens` 或 `cached_tokens`，没有读取 DeepSeek 当前官方 usage 顶层字段 `prompt_cache_hit_tokens`、`prompt_cache_miss_tokens`，也没有读取 `completion_tokens_details.reasoning_tokens`。DeepSeek 官方文档说明 `prompt_tokens = prompt_cache_hit_tokens + prompt_cache_miss_tokens`，reasoning tokens 在 `completion_tokens_details.reasoning_tokens` 中。([GitHub][13])

`client.py` 非 streaming 路径会尝试把 top-level hit/miss 转入 `prompt_tokens_details`，但 `_usage_to_dict()` streaming fallback 只读取 `cached_tokens`；`runtime.py` 仍然手写累计 `prompt_tokens_details.cached_tokens`。([GitHub][14])

修复：

```python
hit = (
    usage.get("prompt_cache_hit_tokens")
    or details.get("prompt_cache_hit_tokens")
    or details.get("cached_tokens")
    or 0
)

miss = (
    usage.get("prompt_cache_miss_tokens")
    or details.get("prompt_cache_miss_tokens")
    or max(prompt - hit, 0)
)

reasoning = (
    (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
    or details.get("reasoning_tokens")
    or 0
)
```

然后 client/runtime/agent/cost/budget 全部使用 `NormalizedUsage`，不要各自解析 usage。

---

## 4.2 pricing/cost 仍不可信

DeepSeek 当前官方 pricing 以 **USD per 1M tokens** 列出：`deepseek-v4-flash` cache hit $0.0028、cache miss $0.14、output $0.28；`deepseek-v4-pro` 当前折扣价 cache hit $0.003625、cache miss $0.435、output $0.87，并说明产品价格可能变化，应定期检查。([DeepSeek API Docs][15])

SeekFlow 中仍至少有四套价格表：`agent.PRICING`、`models.py`、`cost.py`、`budget.py`。它们标成 CNY，但数值混用旧价格、折扣前价格、折扣后价格；例如 `models.py` 中 pro 仍为 0.028/1.74/3.48，`cost.py` 中 flash cached_input 是 0.002，而官方当前 flash cache hit 是 $0.0028。([GitHub][4])

这会导致：

```text
AgentResult.cost 不可信
BudgetGuard 不可信
README benchmark 成本不可信
cache saving 估算不可信
```

修复：

```python
@dataclass(frozen=True)
class Price:
    currency: Literal["USD", "CNY"]
    input_cache_hit_per_m: Decimal
    input_cache_miss_per_m: Decimal
    output_per_m: Decimal
    effective_from: datetime | None
    effective_until: datetime | None
    source_url: str
```

并删除重复表，只保留 `pricing.py`。

---

## 4.3 FIM 缺少 model capability 与 non-thinking guard

`fim.py` 只有 max_tokens guard，但没有检查 model 是否 supports_fim，也没有拒绝 thinking / extra_body thinking 参数。DeepSeek pricing 页面明确 FIM 是 non-thinking mode only。([GitHub][7])

修复：

```python
spec = get_model_spec(model)
if not spec.supports_fim:
    raise ValueError(f"{model} does not support FIM")

if "thinking" in kwargs or (
    isinstance(kwargs.get("extra_body"), dict)
    and "thinking" in kwargs["extra_body"]
):
    raise ValueError("FIM is non-thinking mode only")
```

---

## 4.4 JSON output mode 缺少 runtime contract

DeepSeek 文档说明，设置 `response_format={"type": "json_object"}` 时，还必须在 system 或 user message 中明确要求输出 JSON，否则模型可能生成空白直到 token limit。([DeepSeek API Docs][12])

Agent `_make_messages()` 对 JSON mode 做了中文提示，这是好事；但底层 `ToolRuntime.chat()` 只设置 `response_format`，不会检查 messages 是否包含 JSON 指令，也不会验证最终输出是否为合法 JSON。([GitHub][4])

建议 Runtime 增加 `json_mode_contract=True`：

```text
response_format=json_object 时自动检查/注入 JSON 指令
输出后 json.loads 校验
finish_reason == length 时标记 invalid_json
支持 Pydantic validation + retry
```

---

# 5. MCP 安全与架构专项审计

MCP 是目前剩余最大攻击面之一。

当前改进：

```text
MCPServerConfig 有 trust_level / allowed_capabilities / max_risk / allowed_domains / workspace_root / requires_approval / sandbox / env_allowlist / cwd
MCP 注册时会派生 ToolPolicy
SDK path 已调用 cfg.to_stdio_params()
manual path 有 stderr drain
```

这些方向正确。([GitHub][8])

但仍有严重问题：

```text
manual path env 为空时继承父进程环境
SDK path to_stdio_params 不应用 env_allowlist
sandbox 字段没有被用于真正隔离 MCP server
tool name 映射不一致
_parse_tool_name 仍按 "." split
_mcp_exec.__name__ 含 "."
直接 execute_sync 路径可能无法处理 server__tool
```

修复优先级：

```text
1. build_safe_env() 统一 SDK/manual path
2. env 默认空，不继承 os.environ
3. UNTRUSTED/SANDBOXED server 必须通过 sandbox runner
4. sanitize_tool_name + 映射表
5. _parse_tool_name 从映射表查，不 split
6. MCP server 断开时 terminate -> wait -> kill tree
7. MCP tool result 统一 wrap_untrusted
```

---

# 6. 架构与性能极致优化建议

## 6.1 Runtime 应从“复制逻辑”改成共享 engine

虽然 sync、stream、batch、async 现在都开始接入 policy，但这些路径仍复制了大量逻辑：usage 累计、tool execution、reasoning handling、context trim、tool result message 构造。复制逻辑会反复引入安全漂移。([GitHub][3])

建议抽出：

```text
RuntimeEngine.build_executor()
RuntimeEngine.build_tools_schema()
RuntimeEngine.accumulate_usage()
RuntimeEngine.execute_tool_calls()
RuntimeEngine.append_tool_messages()
RuntimeEngine.handle_reasoning_content()
RuntimeEngine.prepare_json_contract()
```

sync/async 只保留 transport 差异。

---

## 6.2 cache-first 策略还没真正贯穿 runtime

`append_only_compress()` 已修复为不修改 system message，但 `runtime._trim_messages()` 仍调用 `_runtime_base.trim_messages()`，也就是破坏式裁剪。([GitHub][16])

如果 SeekFlow 的差异化是 DeepSeek prompt cache，建议固定消息布局：

```text
messages[0] = frozen system prompt
messages[1] = deterministic tool/policy summary
messages[2] = dynamic compressed context
messages[3:] = recent exact turns
```

不要简单删除旧消息，而是将旧消息摘要放在固定位置，保持 prefix 稳定。

---

## 6.3 ToolExecutor 应拆分职责

当前 `ToolExecutor` 同时承担 parse、repair、coerce、policy、approval、cache、execute、truncate、audit。功能过多，且容易出现这次 `policy` 未定义这类作用域 bug。([GitHub][2])

建议拆成：

```text
ToolCallParser
ToolArgumentValidator
ToolPolicyAuthorizer
ToolApprovalGate
ToolScheduler
ToolRunner
ToolOutputSanitizer
ToolAuditLogger
```

最终执行路径：

```text
tool_call
→ parse/repair
→ schema validate
→ policy authorize
→ approval gate
→ scheduler
→ runner/thread/process/sandbox
→ sanitizer
→ audit
```

---

## 6.4 ContainerSandbox 仍需生产级 kill 与限制

`ContainerSandbox` 使用 `docker run --rm --network none --memory 256m --cpus 1 --read-only --tmpfs /tmp:noexec --user 1000:1000`，这是正确方向；但 timeout 时没有显式容器名，也就无法可靠 `docker kill` 指定容器。([GitHub][17])

建议：

```text
docker run --name seekflow-{uuid}
timeout 后 docker kill + docker rm -f
增加 --pids-limit
增加 --cap-drop ALL
增加 --security-opt no-new-privileges
可选 --security-opt seccomp=...
```

`ProcessSandbox` 和 `LocalThreadSandbox` 仍能访问宿主文件，文档必须明确它们只适用于可信开发，不适合不可信代码。([GitHub][17])

---

# 7. 更新正确性总表

| 模块                          | 当前状态    | 结论                                              |
| --------------------------- | ------- | ----------------------------------------------- |
| PolicyEngine 默认创建           | 已有      | 正确                                              |
| sync chat policy/context    | 已接入     | 正确                                              |
| stream/batch policy/context | 已接入     | 比上一轮明显进步                                        |
| async policy/context        | 已接入     | 进步，但缺 approval/sandbox 参数                       |
| approval handler            | 半成品     | 有严重 `policy` 未定义 bug                            |
| Agent allow_*               | 已立即注册工具 | 正确，但参数丢失                                        |
| safe filesystem             | 基本正确    | `validate_file_access` 顺序 bug                   |
| safe network                | 基本正确    | policy 层校验弱，SSRF hardener 需更硬                   |
| safe python                 | 方向正确    | sandbox timeout/kill 需加强                        |
| safe sqlite                 | 明显改善    | 仍需 SQL parser / function allowlist / BLOB limit |
| MCP policy                  | 有进步     | env/sandbox/name 映射未闭环                          |
| strict schema               | 有进步     | 非 strict name validation 缺失                     |
| usage normalizer            | 有但未接全   | 未读官方 top-level 字段                               |
| pricing/cost                | 不正确     | 多套表、CNY/USD 混乱                                  |
| FIM                         | 部分正确    | 缺 supports_fim/non-thinking guard               |
| cache                       | 部分正确    | compression 修复，runtime 仍 destructive trim       |
| CI/typing                   | 不足      | 无 workflows，核心模块 mypy ignore 仍多                 |

---

# 8. 下一版 v0.3.0 推荐目标：Enforcement Core 完整闭环

优先级必须是：

```text
1. 修复 ToolExecutor approval NameError。
2. MCP env 默认不继承父进程。
3. MCP tool name sanitize + 映射表。
4. ToolRegistry 全模式校验 DeepSeek function name。
5. validate_file_access 先 safe_join 再 exists。
6. Network policy 使用 validate_url_strict。
7. usage/cost/pricing 统一。
8. jsonschema validation 接入 ToolExecutor。
9. 非字符串工具结果统一 wrap_untrusted。
10. ContainerSandbox timeout 后显式 kill。
```

验收标准：

```text
所有模式：sync / stream / batch / async
所有工具来源：local / builtin / MCP
所有高危能力：filesystem / network / sql / python / write
都必须经过：

parse/repair
→ jsonschema validation
→ policy authorization
→ approval/sandbox
→ audited execution
→ untrusted output wrapping
→ normalized usage/cost accounting
```

---

## 9. 最终评价

这次更新**非常值得肯定**：SeekFlow 已经从“安全模块旁路存在”推进到“安全执行内核初步接入”。但现在不能因为模块都出现了，就宣称生产级。当前剩余问题不是小修小补，而是影响生产可信度的核心边界问题：approval 会崩、MCP env 会泄露、MCP name 映射不一致、usage/cost 不可信、ThreadPool timeout 不是隔离、文件路径校验顺序错误。

我的最终判断：

> **SeekFlow 现在是一个方向正确、进步明显、但仍需完成 v0.3.0 Enforcement Core 的 DeepSeek-native Agent Runtime beta。**

它最值得继续打磨的方向不是扩展更多功能，而是把 **policy-enforced + sandbox-first + cache/cost-aware + DeepSeek-protocol-correct** 这条主链路做到不可绕过。

[1]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/policy.py "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/executor.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/runtime.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/agent/agent.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/builtins/filesystem.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/registry.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/fim.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/mcp/executor.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/mcp/config.py "raw.githubusercontent.com"
[10]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/security.py "raw.githubusercontent.com"
[11]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/builtins/network.py "raw.githubusercontent.com"
[12]: https://api-docs.deepseek.com/api/create-chat-completion "Create Chat Completion | DeepSeek API Docs"
[13]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/usage.py "raw.githubusercontent.com"
[14]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/client.py "raw.githubusercontent.com"
[15]: https://api-docs.deepseek.com/quick_start/pricing "Models & Pricing | DeepSeek API Docs"
[16]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/cache.py "raw.githubusercontent.com"
[17]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/sandbox.py "raw.githubusercontent.com"
