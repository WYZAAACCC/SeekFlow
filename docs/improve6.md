# SeekFlow 更新后深度代码审计报告

## 0. 审计结论

这次更新**比上一轮明显前进了一大步**：版本号在 `pyproject.toml` 与 `__init__.py` 中已统一到 `0.2.5`，新增了 `ToolExecutionContext`、`ApprovalHandler`、安全 builtin factories、严格 schema compiler、DeepSeek model registry、usage normalizer、FIM 4K 限制、cache 稳定化改造，以及 Agent 的 `allow_filesystem / allow_network / allow_python / allow_sqlite` profile API。也就是说，项目已经从“安全模块旁路存在”推进到了“部分安全链路接入主路径”的阶段。([GitHub][1])

但它**仍然不能被称为完整生产级**。最大问题已经从“完全没有接线”变成了“接线不一致、不全路径、不全模式”：`ToolRuntime.chat()` 已经会把 `policy_engine`、`policy_context` 传给 `ToolExecutor`，但 `chat_stream()`、`chat_batch()`、`AsyncToolRuntime` 仍然创建无 policy/context 的 executor；`ToolExecutor` 虽然有 policy gate，但 cache 命中发生在 policy 之前；`PolicyEngine.authorize()` 虽然默认拒绝无 policy 工具，但没有真正检查 `allowed_capabilities`、`max_risk`、`dangerous_tools_enabled`；approval handler 也定义了但没有执行。([GitHub][2])

一句话判断：

> **SeekFlow 更新方向正确，但当前仍处于 security-hardening beta。核心同步 `chat()` 路径已有安全雏形；stream、batch、async、cache、MCP、cost、usage、approval、timeout 仍有生产级漏洞。**

---

# 1. 更新后做对的地方

## 1.1 Agent 现在确实会使用安全 builtin factories

上一轮最大问题之一是 `dangerous_tools=True` 仍注册旧版危险工具。这次已经有实质修复：`with_default_tools()` 在 dangerous mode 下不再默认导入旧 `run_python / fetch_url / query_sql`，而是根据已配置 profile 使用 `make_read_file`、`make_fetch_url`、`make_python_exec`、`make_sqlite_query`；旧 `agent.builtins` 只保留 `parse_csv_str / extract_entities / classify_text` 这类低危文本工具。([GitHub][3])

这一步非常重要，说明项目已经从“布尔危险开关”转向“capability profile 驱动”的方向。安全 filesystem 工具会绑定 workspace root，并通过 `ToolPolicy(capabilities={"filesystem.read"}, risk="read", workspace_root=root)` 注册；网络工具会绑定 allowed domains；Python 执行工具要求传入非 `NoSandbox`；SQLite 工具使用只读 URI、authorizer、progress handler 和 row limit。([GitHub][4])

**评价：正确，但还没有完全闭环。**原因是 profile API 与 runtime 缓存、stream/async 路径、policy enforcement 仍未全部打通。

---

## 1.2 sync `ToolRuntime.chat()` 已经传入 policy/context

当前 `ToolRuntime.__init__()` 已经接受 `policy_engine`、`policy_context`、`approval_handler`、`sandbox`，并且 `chat()` 中创建 `ToolExecutor` 时会传入这些对象。Agent 的 `_make_runtime()` 也会构建 `ToolExecutionContext`，把 `dangerous_tools_enabled`、`allowed_capabilities`、`max_risk`、`workspace_root`、`allowed_domains`、`sandbox` 注入 runtime。([GitHub][2])

**评价：方向正确。**这是走向生产级的关键改动。

但注意：这个闭环只在同步 `chat()` 路径相对成立，`chat_stream()`、`chat_batch()`、`AsyncToolRuntime` 仍然绕开这些参数，后面会详细说。

---

## 1.3 无 policy 工具默认拒绝，已经比之前更安全

`policy.py` 现在定义了 `_DEFAULT_UNTRUSTED_POLICY`，risk 为 `destructive`，`requires_approval=True`，并且 `PolicyEngine.authorize()` 对 `tool_def.policy is None` 默认拒绝，除非显式 `allow_no_policy=True`。这是上一轮报告建议的关键修复之一。([GitHub][5])

**评价：正确。**这比“无 policy 默认 read safe”安全得多。

但 `ToolRuntime` 如果没有默认创建 `PolicyEngine`，这个拒绝不会自动生效；直接使用 `ToolRuntime(tools=[...])` 且不传 `policy_engine` 时，executor 内的 policy gate 不会运行。这意味着“每个 tool call 都授权”的文档仍然不完全真实。([GitHub][2])

---

## 1.4 DeepSeek thinking mode 处理方向正确

`_apply_thinking_mode()` 会在 thinking mode enabled 时移除 `temperature`、`top_p`、`presence_penalty`、`frequency_penalty` 并发 warning，这符合 DeepSeek 官方文档：thinking mode 下这些参数不生效。Runtime 在 assistant 消息带有 tool calls 时保留 `reasoning_content` 原文回传，这也符合 DeepSeek 官方要求：如果 thinking mode 下发生 tool call，`reasoning_content` 必须在后续上下文中回传。([GitHub][2])

**评价：正确，应保留。**

---

## 1.5 Strict schema 已经开始真正接入

`ToolRegistry.to_deepseek_tools(strict=True)` 现在会调用 `DeepSeekStrictSchemaCompiler`，并且在 function 上设置 `"strict": true`。Strict compiler 也会强制 object schema `additionalProperties=false`，并把所有 properties 设置为 required。([GitHub][6])

DeepSeek 官方要求 tool function name 只能使用字母、数字、下划线、短横线，并且最大 64 字符；strict mode 需要 function 级别 `strict=true`。当前 registry 至少在 strict 模式上已经接近正确方向。([DeepSeek API Docs][7])

**评价：有明显进步，但 MCP tool name 仍会破坏这个规则。**

---

## 1.6 cache compression 已修复“修改 system message”的大问题

上一轮报告指出 `append_only_compress()` 会把动态压缩摘要拼回第一条 system message，破坏 DeepSeek prompt cache 前缀。当前实现已经改成：保留原始 system message，然后把压缩摘要作为单独 user message 插入。这是正确修复。([GitHub][8])

**评价：正确。**但 runtime 仍默认调用 `_trim_messages()` 做 destructive trim，而不是 append-only compression；因此 cache-first 架构还没完全落地。([GitHub][9])

---

# 2. P0 级漏洞：必须优先修复

## P0-1：PolicyEngine 没有真正执行 capability / risk / dangerous gate

这是当前最严重的设计漏洞。

`PolicyEngine` 中存在 `authorize_with_context()`，它会检查 `dangerous_tools_enabled`、`max_risk`、`allowed_capabilities`。但 `ToolExecutor` 调用的是 `authorize()`，而 `authorize()` 主要检查无 policy、destructive、code sandbox、filesystem.write workspace、URL hostname、path safe_join、requires_approval；它**没有检查**：

```text
policy.risk 是否超过 context.max_risk
非 read 风险是否要求 dangerous_tools_enabled=True
policy.capabilities 是否包含在 context.allowed_capabilities 中
network.public_http 是否必须要求 allowed_domains 非空
filesystem.read 是否必须要求 workspace_root
```

这意味着一个自定义工具只要有 policy，`risk="network"` 或 `risk="write"` 并不一定会被 context 限制拦截。代码中 `authorize_with_context()` 写对了一部分，但主执行路径没用它。([GitHub][5])

### 可复现风险

一个自定义工具：

```python
@tool
def exfiltrate(url: str) -> str:
    ...

exfiltrate = exfiltrate.with_policy(ToolPolicy(
    capabilities={"network.public_http"},
    risk="network",
))
```

在当前 `authorize()` 中，如果 `policy.allowed_domains` 为空，URL 域名校验不会触发；如果 `dangerous_tools_enabled=False`，也不会因为 risk=network 被拒绝；如果 context 没有 `network.public_http` capability，也不会被拒绝。

### 修复方案

把 `authorize_with_context()` 合并进 `authorize()`，并让 `ToolExecutor` 只调用一个强制方法：

```python
def authorize(
    self,
    tool_def: ToolDefinition,
    args: dict[str, Any],
    context: ToolExecutionContext,
) -> PolicyDecision:
    policy = tool_def.policy or DEFAULT_UNTRUSTED_POLICY

    if tool_def.policy is None and not self._allow_no_policy:
        return deny("Tool has no policy configured", requires_approval=True)

    if policy.risk != "read" and not context.dangerous_tools_enabled:
        return deny("Dangerous tools are disabled")

    if RISK_ORDER[policy.risk] > RISK_ORDER[context.max_risk]:
        return deny(f"Tool risk {policy.risk} exceeds allowed risk {context.max_risk}")

    missing = policy.capabilities - context.allowed_capabilities
    if missing:
        return deny(f"Missing capabilities: {sorted(missing)}")

    if "filesystem.read" in policy.capabilities or "filesystem.write" in policy.capabilities:
        root = policy.workspace_root or context.workspace_root
        if root is None:
            return deny("filesystem capability requires workspace_root")

    if "network.public_http" in policy.capabilities:
        domains = policy.allowed_domains or context.allowed_domains
        if not domains:
            return deny("network.public_http requires allowed_domains")
        validate_url_strict(args["url"], NetworkPolicy(allowed_domains=domains))

    if "code.exec" in policy.capabilities:
        sandbox = context.sandbox
        if sandbox is None or getattr(sandbox, "name", "") in {"no_sandbox", "abstract"}:
            return deny("code.exec requires a real sandbox")

    if policy.requires_approval:
        return allow(requires_approval=True)

    return allow()
```

### 优先级

**最高。**没有这个修复，capability profile 只是配置，不是安全边界。

---

## P0-2：`ToolExecutor` 在 policy 之前查缓存，可能绕过新的安全策略

当前 `ToolExecutor.execute()` 在 parse、lookup、policy 之前先查 cache：如果 cache 命中，直接返回 cached result。也就是说，之前某个 policy 允许的工具结果，之后即使 policy 变成拒绝，只要 cache key 相同，就可能直接返回旧结果，绕过当前 policy。([GitHub][10])

这在多 tenant、动态 policy、临时授权、approval 场景非常危险。

### 攻击场景

1. tenant A 允许读取 `report.txt`。
2. 工具结果进入 cache。
3. tenant B 或后续同一用户在更严格 policy 下请求相同工具调用。
4. executor 在 policy 前命中 cache，直接返回旧数据。

### 修复方案

cache lookup 必须移动到 policy 之后，并且 cache key 必须包含 security context fingerprint：

```python
cache_key = make_cache_key(
    tool_call.name,
    arguments,
    context_hash=hash_context(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        allowed_capabilities=context.allowed_capabilities,
        workspace_root=context.workspace_root,
        allowed_domains=context.allowed_domains,
        policy_hash=hash_tool_policy(tool_def.policy),
    ),
)
```

并且高危工具默认不 cache：

```python
cache_enabled = (
    tool_def.policy is not None
    and tool_def.policy.risk == "read"
    and tool_def.policy.parallel_safe
)
```

---

## P0-3：stream、batch、async 路径绕过 policy/context

同步 `chat()` 已经把 policy/context 传给 executor，但 `chat_stream()` 创建 `ToolExecutor` 时没有传 `policy_engine`、`context`、`approval_handler`、`sandbox`。`chat_batch()` 里执行 tool calls 时也创建了无 policy/context 的 executor。`AsyncToolRuntime` 的 `chat_async()` 与 `chat_stream_async()` 同样没有 policy/context 参数，executor 也是无 policy 创建。([GitHub][2])

这造成了非常严重的不一致：

```text
agent.run(...)        相对有 policy
agent.stream(...)     绕过 policy
runtime.chat_batch()  绕过 policy
AsyncToolRuntime      绕过 policy
```

### 修复方案

抽出统一 executor factory：

```python
def _make_executor(self) -> ToolExecutor:
    return ToolExecutor(
        self._registry,
        repair=self._repair,
        max_result_chars=self._max_result_chars,
        cache=self._active_cache,
        truncation_strategy=self._truncation_strategy,
        policy_engine=self._policy_engine or PolicyEngine(),
        context=self._policy_context or ToolExecutionContext.conservative(),
        approval_handler=self._approval_handler or DefaultDenyApprovalHandler(),
        sandbox=self._sandbox,
    )
```

然后所有路径都只能调用 `_make_executor()`：

```text
chat
chat_stream
chat_batch
AsyncToolRuntime.chat_async
AsyncToolRuntime.chat_stream_async
MCP wrapper execution
```

### 优先级

**最高。**安全边界必须跨所有 runtime 模式一致。

---

## P0-4：`ToolRuntime` 默认不启用 PolicyEngine

`ToolRuntime.__init__()` 接收 `policy_engine=None`，然后原样保存。也就是说，用户直接使用核心 API：

```python
runtime = ToolRuntime(tools=[some_tool])
runtime.chat(...)
```

默认不会有 policy enforcement。README 和 SECURITY 文档却声称“every tool call authorized before execution”。([GitHub][2])

### 修复方案

默认启用最保守策略：

```python
self._policy_engine = policy_engine or PolicyEngine()
self._policy_context = policy_context or ToolExecutionContext.conservative()
self._approval_handler = approval_handler or DefaultDenyApprovalHandler()
```

如果为了兼容旧用户，需要提供显式逃生口：

```python
ToolRuntime(..., unsafe_disable_policy=True)
```

并发出 `UserWarning`。

---

## P0-5：approval handler 已定义但没有真正使用

`ApprovalHandler`、`DefaultDenyApprovalHandler` 已经定义，这是正确设计。([GitHub][11])

但 `ToolExecutor.execute()` 遇到 `decision.requires_approval` 时直接返回 “Approval required”，没有调用 `approval_handler.request_approval()`。([GitHub][10])

### 后果

1. `write_file`、`run_python` 等默认 `requires_approval=True` 的工具无法在受控生产环境中正常使用。
2. 用户为了让功能能跑，可能把 `requires_approval=False`，反而降低安全性。
3. 审计链路没有记录谁批准、何时批准、批准理由。

### 修复方案

```python
if decision.requires_approval:
    handler = self.approval_handler or DefaultDenyApprovalHandler()
    approval = handler.request_approval(ApprovalRequest(
        tool=tool_def,
        arguments=arguments,
        reason=decision.reason,
        risk=tool_def.policy.risk,
        capability=tool_def.policy.capabilities,
        run_id=self.context.run_id if self.context else None,
    ))
    if not approval.approved:
        return denied_result(f"Approval denied: {approval.reason}")
```

---

## P0-6：SSRF hardener 方向正确，但实现仍不达生产级

`security/http.py` 已经实现了 strict URL validation，包括 IDNA normalize、scheme、userinfo、hostname、port、allowed domains、DNS 解析和私网 IP 拦截。网络 builtin 也已经调用 `fetch_url_hardened()`，这是正确更新。([GitHub][12])

但 `fetch_url_hardened()` 仍使用 `urllib.request.urlopen()`。Python urllib 默认会自动处理 HTTP redirect，因此代码中“检查 300 <= status < 400 后重新 validate”的逻辑很可能不会按预期执行。更严重的是，它先 `resp.read()` 读取完整响应，再按 `max_response_bytes` 截断，无法防止大响应内存 DoS。([GitHub][12])

此外，`validate_url_strict()` 是“校验时 DNS 解析”，但真正连接时还是让 urllib 自己重新解析域名，存在 DNS TOCTOU / rebinding 风险。`domain_allowed()` canonicalize 了 host，但没有 canonicalize allowlist domains，也可能造成大小写、尾点、IDNA 处理不一致。([GitHub][12])

### 修复方案

使用 `httpx`，禁止自动 redirect，stream 读取：

```python
with httpx.Client(follow_redirects=False, timeout=policy.timeout_s) as client:
    for _ in range(policy.max_redirects + 1):
        validated = validate_url_strict(current, policy)

        with client.stream("GET", current, headers=...) as resp:
            if resp.is_redirect:
                current = urljoin(current, resp.headers["location"])
                continue

            chunks = []
            total = 0
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > policy.max_response_bytes:
                    raise SSRFError("response too large")
                chunks.append(chunk)
```

更高级的版本需要自定义 resolver 或连接到已验证 IP 并固定 Host header，避免 DNS rebinding。

---

# 3. P1 级问题：架构正确性与生产稳定性

## P1-1：Agent profile API 存在调用顺序陷阱

Agent 的 `allow_filesystem / allow_network / allow_python / allow_sqlite` 只是修改内部字段；实际工具注册发生在 `with_default_tools()` 里。也就是说：

```python
agent.with_default_tools()
agent.allow_network(domains={"example.com"})
```

不会自动添加 `fetch_url` 工具。必须反过来调用：

```python
agent.allow_network(...)
agent.with_default_tools()
```

而且 `_make_runtime()` 有 runtime 缓存逻辑：如果工具名集合没变，会复用旧 runtime。也就是说，即使后续改变了 `allowed_domains`、`workspace_root`、`sandbox`，runtime 可能继续持有旧 `ToolExecutionContext`。([GitHub][3])

### 修复方案

每个 `allow_*` 方法应该：

```python
self._invalidate_runtime()
self._ensure_builtin_tools_registered_or_updated()
```

或者更彻底：不要让 `with_default_tools()` 负责安全工具注册，改成 profile 方法立即注册对应工具：

```python
agent.allow_network(domains={"docs.deepseek.com"})
# 立即注册 make_fetch_url(...)
```

---

## P1-2：`allow_filesystem(write=True)` 与 max_risk 不一致

`allow_filesystem()` 在 `write=True` 时会添加 `filesystem.write` capability，但没有把 `_max_risk` 提升到 `"write"`。如果后续 PolicyEngine 正确执行 max_risk 检查，写工具会被拒绝。当前因为 `authorize()` 尚未检查 max_risk，所以这个 bug 被掩盖了。([GitHub][3])

### 修复方案

```python
if write:
    self._allowed_capabilities.add("filesystem.write")
    self._max_risk = max_risk(self._max_risk, "write")
```

---

## P1-3：文件访问校验存在相对路径 bug

`validate_file_access()` 当前先执行 `Path(path).exists()`，然后才执行 `safe_join(workspace_root, str(path))`。这会导致一个常见 bug：如果 `workspace_root=/workspace`，调用 `read_file("a.txt")`，但当前进程 cwd 不是 `/workspace`，`Path("a.txt").exists()` 会失败，即使 `/workspace/a.txt` 存在。([GitHub][13])

### 修复方案

顺序应该改成：

```python
resolved = safe_join(workspace_root, str(path))
if not resolved.exists():
    raise FileNotFoundError(...)
```

安全边界也更清晰：先 canonicalize 到 workspace，再做 exists、ext、filename、size 检查。

---

## P1-4：usage normalizer 没有真正接入主链路

项目新增了 `NormalizedUsage` 和 `normalize_usage()`，这是正确方向。但当前 `runtime.py` 仍然手写累计 `prompt_tokens_details.cached_tokens`；`client.py` 也主要读取 `response.usage.prompt_tokens_details`，而 DeepSeek 当前官方 API 文档把 `prompt_cache_hit_tokens` 和 `prompt_cache_miss_tokens` 放在 usage 顶层，并说明 `prompt_tokens = hit + miss`；reasoning tokens 在 `completion_tokens_details.reasoning_tokens` 中。([GitHub][14])

### 修复方案

`normalize_usage()` 必须支持：

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
    or max(prompt_tokens - hit, 0)
)

reasoning = (
    usage.get("completion_tokens_details", {}).get("reasoning_tokens")
    or details.get("reasoning_tokens")
    or 0
)
```

然后 runtime、agent、cost、budget、streaming 都只能使用 `NormalizedUsage`，不要再各自解析 usage。

---

## P1-5：价格表仍然混乱，并且货币单位错误

DeepSeek 官方 pricing 当前以美元计价：`deepseek-v4-flash` cache hit $0.0028、cache miss $0.14、output $0.28；`deepseek-v4-pro` 当前折扣价 cache hit $0.003625、cache miss $0.435、output $0.87，并说明价格可能变化，需要定期检查。([DeepSeek API Docs][15])

SeekFlow 里至少有三套价格：`agent.PRICING`、`models.py`、`cost.py`。它们都标成 CNY，但值与官方美元表混用。例如 `models.py` 中 pro miss 仍是 `1.74`、output `3.48`，这是官方未折扣美元价格的数值，却被标成 CNY；`cost.py` 中 flash cached_input 又是 `0.002`，与官方 $0.0028 不一致。([GitHub][3])

### 修复方案

建立唯一 `pricing.py`：

```python
@dataclass(frozen=True)
class Price:
    currency: Literal["USD", "CNY"]
    input_cache_hit_per_m: Decimal
    input_cache_miss_per_m: Decimal
    output_per_m: Decimal
    effective_from: datetime | None
    effective_until: datetime | None
    source: str
```

然后：

```text
agent.PRICING 删除
cost.PRICING 删除
models.py 只保留能力，不保留价格，或引用 pricing.py
budget.py 引用 pricing.py
```

用户界面中必须显示 currency，不能写 `CNY` 但使用 USD 数字。

---

## P1-6：cost guard 是事后检查，不是 hard stop

`Agent.run(max_cost=...)` 的 cost check 是在任务执行结束后，通过 `_result_from_runtime()` 计算 cost，然后如果超限返回 `[COST LIMIT EXCEEDED]`。这不是预算硬停止，而是“花完钱后告诉你超了”。([GitHub][3])

### 修复方案

需要两层：

1. **Preflight estimate**：每轮请求前估算下一步最大 prompt + completion 成本。
2. **Step-level hard stop**：累计 cost + projected next step > budget 时，不再发 API 请求。
3. **Tool budget**：高成本工具、MCP、web fetch、SQL 查询也要进入 budget。

---

## P1-7：MCP tool name 不符合 DeepSeek function name 规范

MCP adapter 和 executor 仍然把 tool name 命名为 `{server}.{tool}`。DeepSeek 官方要求 function name 只能包含字母、数字、下划线、短横线，最大 64 字符；点号 `.` 不合法。([GitHub][16])

这意味着 MCP 工具在非 strict 模式下也可能被 DeepSeek API 拒绝；strict 模式下 `check_strict_compatibility()` 会发现 name invalid，但默认 `strict_fallback=True` 又可能掩盖问题。([GitHub][17])

### 修复方案

```python
def sanitize_tool_name(server: str, tool: str) -> str:
    name = f"{server}__{tool}"
    name = re.sub(r"[^A-Za-z0-9_-]", "_", name)
    return name[:64]
```

维护映射：

```python
deepseek_tool_name -> (server_name, original_tool_name)
```

不要通过 split(".") 解析。

---

## P1-8：MCP subprocess 仍有环境变量泄露与死锁风险

`MCPServerConfig` 已经有 `env_allowlist`、`cwd`、`sandbox` 等字段，这是正确方向。但 SDK path 里 `_discover_via_sdk()` 直接构造 `StdioServerParameters(command=cfg.command, args=cfg.args)`，没有使用 `cfg.to_stdio_params()`，因此 `env` 和 allowlist 策略都没有真正生效。manual subprocess path 使用 `subprocess.Popen(..., stderr=subprocess.PIPE)`，没有传 `env`，默认继承父进程环境，包括 API key；stderr 也没有持续 drain，server 输出过多可能阻塞。([GitHub][18])

### 修复方案

```python
env = build_env_from_allowlist(cfg.env, cfg.env_allowlist)
proc = subprocess.Popen(
    ...,
    env=env,
    cwd=cfg.cwd or tempfile.mkdtemp(),
    stderr=subprocess.DEVNULL or background_drain_thread,
)
```

更进一步：MCP server 应按 `trust_level` 自动要求 sandbox；`UNTRUSTED` 不允许裸 subprocess。

---

## P1-9：ThreadPool timeout 仍然不是安全边界

`ToolExecutor` 仍然用 `ThreadPoolExecutor(max_workers=1)` 和 `future.result(timeout=...)` 执行工具；Agent 的 `execution_timeout` 也用 ThreadPool 包裹 `_run_impl()`。Python 线程 timeout 只能让调用方停止等待，不能强杀正在运行的函数；而且在 `with ThreadPoolExecutor(...)` 退出时可能等待工作线程结束。([GitHub][10])

### 修复方案

按风险分层：

| 工具类型                          | 执行方式                               |
| ----------------------------- | ---------------------------------- |
| pure calculate                | 线程可接受                              |
| filesystem / sqlite / network | 进程或受控 wrapper                      |
| python code exec              | ContainerSandbox / nsjail / gVisor |
| MCP                           | sandboxed subprocess + kill tree   |
| write/destructive             | approval + process isolation       |

---

## P1-10：streaming usage 默认拿不到

DeepSeek 官方文档说明，streaming 如果要得到 usage，需要设置 `stream_options.include_usage=true`。([DeepSeek API Docs][7])

`client.chat_stream()` 当前只设置 `"stream": True`，没有默认加入 `stream_options={"include_usage": True}`，所以 stream usage 大概率不会稳定返回。([GitHub][19])

### 修复方案

```python
params.setdefault("stream_options", {"include_usage": True})
```

如果用户显式传了 `stream_options`，则 merge：

```python
params["stream_options"] = {
    **params.get("stream_options", {}),
    "include_usage": True,
}
```

---

# 4. P2 级问题：性能、架构、开发体验

## 4.1 Runtime 仍然使用 destructive trimming，不符合 cache-first 目标

虽然 `append_only_compress()` 已修复为不修改 system message，但 `ToolRuntime.chat()` 每轮仍调用 `_trim_messages()`，而 `_trim_messages()` 会删除旧的非 system messages。删除旧消息不一定破坏第一条 system prompt cache，但会改变后续 prefix 结构，降低长任务中的 cache 稳定性，也会丢失旧上下文。([GitHub][2])

### 极致方案

把 runtime context management 改成：

```text
messages[0] = frozen system
messages[1] = deterministic policy/tool summary
messages[2] = dynamic compressed context
messages[3:] = recent exact turns
```

不要删除历史；把旧消息合成稳定摘要，并放在固定位置。

---

## 4.2 Tool arguments 缺少 jsonschema validation

DeepSeek 官方明确提醒：tool call arguments 是模型生成的 JSON，模型可能生成无效 JSON，也可能 hallucinate schema 之外的参数，开发者必须在执行函数前验证参数。([DeepSeek API Docs][7])

SeekFlow 有 JSON repair 和 type coercion，但没有在执行前用 `jsonschema` 对 `tool_def.parameters` 做严格验证。`coerce_arguments()` 只能做类型转换，不能拒绝 extra properties、pattern、enum、minimum 等约束。

### 修复方案

执行顺序应改为：

```text
JSON parse
JSON repair
jsonschema validate
coerce
jsonschema validate again
policy authorize
approval
execute
```

对于 high-risk 工具，repair 后参数必须更严格：

```text
confidence < 0.95 -> approval or deny
extra args -> deny
schema validation error -> deny
```

---

## 4.3 非字符串工具结果没有统一 UntrustedContent 包装

`ToolExecutor` 只在 `isinstance(raw_result, str)` 时对非 trusted 工具结果执行 `wrap_untrusted()`。如果工具返回 dict/list，结果不会被包装，而 runtime 又会把结果 JSON dump 后放进 tool message。([GitHub][10])

### 修复方案

所有非 trusted 工具输出都应统一：

```python
if not trusted:
    content = raw_result if isinstance(raw_result, str) else json.dumps(raw_result, ensure_ascii=False)
    raw_result = wrap_untrusted(tool_call.name, content).format_for_model()
```

---

## 4.4 SQL 工具还可以继续收紧

新 SQLite 工具有明显进步：workspace-bound、只读 URI、`set_authorizer()`、progress handler、row limit。([GitHub][20])

但仍建议加强：

1. `startswith("SELECT")` 不是 SQL parser，建议用 `sqlglot` 或 SQLite prepare + authorizer 双重校验。
2. `SQLITE_FUNCTION` 当前允许所有函数，应建立函数 allowlist，避免 `randomblob()`、昂贵函数或潜在扩展函数。
3. 返回 JSON 只按字符截断，可能切断 JSON，建议返回 envelope：

   ```json
   {"rows": [...], "truncated": true, "max_rows": 1000}
   ```
4. BLOB 字段应禁止或按大小截断。
5. `data.sqlite` capability 应在 PolicyEngine 中被识别为 filesystem/data capability。

---

## 4.5 FIM 还缺少模型能力与 non-thinking 约束

`fim.py` 已有 `max_tokens <= 4096` guard，这是正确的。([GitHub][21])

但 DeepSeek pricing/model table 说明 FIM 只支持 non-thinking mode。([DeepSeek API Docs][15])

当前 `fim_complete()` 没有检查：

```text
model 是否 supports_fim
是否显式传入 thinking 相关 kwargs
prefix/suffix 是否为空
```

### 修复方案

```python
spec = get_model_spec(model)
if not spec.supports_fim:
    raise ValueError(f"{model} does not support FIM")

if "thinking" in kwargs or "extra_body" in kwargs:
    raise ValueError("FIM runs in non-thinking mode only")
```

---

# 5. 文档与发布质量问题

README 仍显示 `SeekFlow v0.2.0`，并继续宣称 “Production-grade security / 620+ tests / safe for production deployments”。但 `pyproject.toml` 与 `__init__.py` 是 `0.2.5`，GitHub 页面显示 no releases published。([GitHub][22])

这会影响用户对版本、安装包、审计结论、漏洞修复状态的判断。

### 修复方案

```text
README version = 0.2.5
CHANGELOG 增加 0.2.5
Git tag v0.2.5
发布 PyPI 包
GitHub Release
SECURITY.md 标注当前仍是 beta，不应宣称 full production
```

`pyproject.toml` 仍然对 `runtime`、`async_runtime`、`agent.*`、`mcp.*`、`fim`、`structured`、`cost` 等关键模块 `ignore_errors=true`。这不适合生产级安全框架。([GitHub][1])

---

# 6. 更新正确性总表

| 模块                           | 更新是否正确 | 当前状态                                                        |
| ---------------------------- | ------ | ----------------------------------------------------------- |
| Agent safe builtin factories | 基本正确   | dangerous path 改用 profile factories，但调用顺序和 runtime cache 有坑 |
| ToolRuntime sync chat        | 部分正确   | 已传 policy/context，但默认仍可无 policy                             |
| ToolRuntime stream           | 不正确    | executor 无 policy/context                                   |
| ToolRuntime batch            | 不正确    | executor 无 policy/context                                   |
| AsyncToolRuntime             | 不正确    | 没有 policy/context 参数                                        |
| PolicyEngine                 | 部分正确   | 无 policy 默认拒绝正确，但缺 capability/risk/dangerous enforcement    |
| ApprovalHandler              | 未完成    | 定义了协议，但 executor 未调用                                        |
| Hardened HTTP                | 部分正确   | 主工具已调用，但 urllib redirect/read-all 仍有 SSRF/DoS 风险            |
| Filesystem tool              | 部分正确   | factory 正确，validate_file_access 顺序有 bug                     |
| Python exec                  | 方向正确   | factory 要求 sandbox，但 timeout/sandbox 仍需加强                   |
| SQLite tool                  | 明显改善   | 仍需 parser/function allowlist/blob limit                     |
| MCP                          | 部分正确   | 有 policy 派生，但 tool name 非法、env/sandbox 未闭环                  |
| Strict schema                | 明显改善   | registry 已设置 strict，但 MCP name 会失败                          |
| Usage/cost                   | 不完整    | normalizer 未全链路接入，官方字段解析不全                                  |
| Pricing                      | 不正确    | 多套价格表，USD/CNY 混乱                                            |
| Cache                        | 部分正确   | append_only_compress 修复，但 runtime 仍 destructive trim        |
| FIM                          | 部分正确   | 4K guard 正确，缺 non-thinking/model capability guard           |

---

# 7. 推荐修复路线图

## Phase 1：Enforcement Core

目标：让任何 tool call 在任何模式下都不能绕过 policy。

必须完成：

```text
1. ToolRuntime 默认创建 PolicyEngine + conservative context。
2. chat / chat_stream / chat_batch / AsyncToolRuntime 全部使用同一个 _make_executor()。
3. ToolExecutor cache lookup 移到 policy 之后。
4. PolicyEngine.authorize() 合并 authorize_with_context() 逻辑。
5. capability / risk / dangerous_tools_enabled / workspace / domain / sandbox 全部强制检查。
6. ApprovalHandler 真正执行。
```

验收测试：

```text
无 policy 工具默认拒绝
stream 模式下高危工具被拒绝
batch 模式下高危工具被拒绝
async 模式下高危工具被拒绝
cache 命中不能绕过当前 policy
network tool 无 allowed_domains 拒绝
filesystem.read 无 workspace_root 拒绝
code.exec 无 sandbox 拒绝
requires_approval 无 handler 拒绝，有 handler 才执行
```

---

## Phase 2：Dangerous Capability Hardening

目标：把 filesystem/network/sql/python/mcp 做成真实生产安全边界。

必须完成：

```text
1. validate_file_access 先 safe_join，再 exists/stat。
2. fetch_url_hardened 改 httpx follow_redirects=False + stream size cap。
3. DNS failure fail closed，redirect 每跳重新 validate。
4. SQL 使用 parser 或更严格 statement validation。
5. SQL 函数 allowlist，BLOB size cap。
6. ContainerSandbox timeout 必须 docker stop/kill，不能只等 subprocess timeout。
7. MCP tool name 改 server__tool，维护映射。
8. MCP subprocess 默认空 env，env_allowlist 生效，stderr drain，cwd/sandbox 生效。
```

---

## Phase 3：DeepSeek-native Correctness

目标：把 DeepSeek 的 cache、thinking、usage、tool strict、FIM 做成真正优势。

必须完成：

```text
1. NormalizedUsage 接入 client/runtime/agent/cost/budget。
2. 支持官方顶层 prompt_cache_hit_tokens / prompt_cache_miss_tokens。
3. 支持 completion_tokens_details.reasoning_tokens。
4. 唯一 pricing.py，标明 USD/CNY，不混用。
5. Streaming 默认 include_usage。
6. Strict schema fail-fast，MCP name 合规。
7. FIM 检查 supports_fim 与 non-thinking。
8. Runtime 改 append-only compression，不再 destructive trim。
```

---

## Phase 4：Performance & Architecture Extreme Optimization

目标：在 DeepSeek 方向做到极致，而不是变成另一个 LangChain。

建议：

```text
1. Cache-first message layout：
   system frozen
   policy/tool summary deterministic
   compressed dynamic context
   recent turns

2. Tool planner：
   read-only tools parallel
   side-effect tools sequential
   high-risk tools approval
   code tools sandbox only

3. Usage/cost observability：
   cache_hit_tokens
   cache_miss_tokens
   cache_hit_ratio
   reasoning_tokens
   cost_per_step
   budget_remaining

4. Security telemetry：
   policy_denied_total
   approval_required_total
   sandbox_killed_total
   ssrf_blocked_total
   path_escape_blocked_total
   repair_denied_total

5. CI gates：
   ruff
   mypy for security/policy/tools/runtime
   pytest
   bandit
   pip-audit
   version consistency
   SSRF regression suite
   MCP sandbox regression suite
```

---

# 8. 最终判断

SeekFlow 这次更新**不是表面更新**，确实修了很多上一轮指出的问题。尤其是：

```text
安全 builtin factories 已出现
Agent dangerous tools 开始改用 profile factories
sync chat 开始传 policy context
无 policy 默认拒绝已经写进 PolicyEngine
strict schema compiler 已接入 registry
append_only_compress 已不再修改 system message
thinking mode 与 reasoning_content 处理方向正确
FIM 4K guard 正确
```

但它还不是完整生产级，主要因为：

```text
PolicyEngine 主 authorize 逻辑不完整
stream/batch/async 绕过 policy
cache 在 policy 之前命中
approval handler 未使用
SSRF hardener 仍不够硬
MCP tool name 与 DeepSeek 规范冲突
usage/cost/pricing 未统一
runtime 仍 destructive trim
ThreadPool timeout 不是安全边界
```

我的最终建议是：下一版不要继续加功能，应该发布一个专门的：

```text
v0.3.0 — Enforcement Core
```

唯一目标：

```text
所有模式、所有工具、所有来源的 tool call 都必须经过：
parse/repair
→ schema validation
→ policy authorization
→ approval/sandbox
→ audited execution
→ untrusted output wrapping
→ normalized usage/cost accounting
```

完成这条链路后，SeekFlow 才真正有资格称为：

> **DeepSeek-native, policy-enforced, sandbox-first Agent Runtime.**

现在它更准确的定位是：

> **方向正确、进步明显、但仍处于安全闭环未完全完成的 beta 框架。**

[1]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/pyproject.toml "raw.githubusercontent.com"
[2]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/runtime.py "raw.githubusercontent.com"
[3]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/agent/agent.py "raw.githubusercontent.com"
[4]: https://github.com/WYZAAACCC/SeekFlow/blob/main/src/seekflow/tools/builtins/filesystem.py "SeekFlow/src/seekflow/tools/builtins/filesystem.py at main · WYZAAACCC/SeekFlow · GitHub"
[5]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/policy.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/registry.py "raw.githubusercontent.com"
[7]: https://api-docs.deepseek.com/api/create-chat-completion "Create Chat Completion | DeepSeek API Docs"
[8]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/cache.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/_runtime_base.py "raw.githubusercontent.com"
[10]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/executor.py "raw.githubusercontent.com"
[11]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/execution/approval.py "raw.githubusercontent.com"
[12]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/security/http.py "raw.githubusercontent.com"
[13]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/security.py "raw.githubusercontent.com"
[14]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/usage.py "raw.githubusercontent.com"
[15]: https://api-docs.deepseek.com/quick_start/pricing "Models & Pricing | DeepSeek API Docs"
[16]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/mcp/adapter.py "raw.githubusercontent.com"
[17]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/strict.py "raw.githubusercontent.com"
[18]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/mcp/config.py "raw.githubusercontent.com"
[19]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/client.py "raw.githubusercontent.com"
[20]: https://github.com/WYZAAACCC/SeekFlow/blob/main/src/seekflow/tools/builtins/sqlite.py "SeekFlow/src/seekflow/tools/builtins/sqlite.py at main · WYZAAACCC/SeekFlow · GitHub"
[21]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/fim.py "raw.githubusercontent.com"
[22]: https://github.com/WYZAAACCC/SeekFlow "GitHub - WYZAAACCC/SeekFlow: DeepSeek-native agent framework with production-grade reliability · GitHub"
