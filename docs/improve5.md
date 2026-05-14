# SeekFlow 更新后深度代码审计报告

## 0. 总结判断

这次更新**方向是正确的，但工程闭环仍然不正确**。

项目确实新增或强化了不少我们前面报告中建议过的模块：`security/http.py`、`models.py`、`usage.py`、`tools/builtins/*`、Agent 的 `allow_filesystem / allow_network / allow_python / allow_sqlite`、FIM 4K guard、thinking mode 参数清理、部分 Policy gate 等。这说明维护者理解了问题方向。

但核心问题是：**很多新模块只是“放进仓库了”，没有真正接入主执行链路。**最严重的是，Agent 仍然在 `dangerous_tools=True` 时注册旧版高危工具，而不是使用新的安全 builtin factories；`ToolRuntime` 创建 `ToolExecutor` 时也没有传入 policy context、allowed capabilities、workspace root、allowed domains、sandbox 或 approval handler；`ToolExecutor` 只有一个局部 policy gate，并且只在 `tool_def.policy is not None` 时执行。结果是：**无 policy 的高危工具可以绕过 PolicyEngine，且 batch 执行还会默认把无 policy 工具当成 safe read 并行执行。**([GitHub][1])

我的最终评分：

| 维度          |  更新后评分 | 判断                                              |
| ----------- | -----: | ----------------------------------------------- |
| 更新方向        |   8/10 | 明显吸收了前期审计建议                                     |
| 安全闭环        |   3/10 | 新安全模块未进入强制执行路径                                  |
| DeepSeek 适配 | 6.5/10 | thinking/FIM 方向对，但 usage/pricing/strict mode 仍错 |
| 工程稳定性       |   4/10 | 版本、CI、测试预期与实现不一致                                |
| 当前生产可用性     |   3/10 | 仍不适合不可信任务或企业生产环境                                |
| 长期潜力        |   8/10 | 只要把执行内核打通，仍有价值                                  |

---

# 1. 本次更新做对了什么

## 1.1 新增了更安全的工具工厂，这是正确方向

仓库现在已经有 `src/seekflow/tools/builtins` 目录，并包含 `filesystem.py`、`network.py`、`python_exec.py`、`sqlite.py`。`filesystem.py` 提供 workspace-bound read/write 工具；`python_exec.py` 明确拒绝 `NoSandbox`；`sqlite.py` 使用只读 SQLite URI、authorizer、progress handler 和 max rows；这些都比旧版内置工具安全得多。([GitHub][2])

但问题是：**Agent 默认危险工具路径没有使用这些新工厂。**`with_default_tools()` 在 `dangerous_tools=True` 时仍然定义本地 `read_file`，并从 `seekflow.agent.builtins` 导入旧版 `fetch_url`、`run_python`、`query_sql` 等工具。([GitHub][3])

所以这次更新是“组件正确，接线错误”。

---

## 1.2 新增 `security/http.py`，方向正确

`security/http.py` 已经有 `NetworkPolicy`、`validate_url_strict()`、`resolve_all()`、`domain_allowed()` 和 `fetch_url_hardened()`，也开始处理 IDNA、私网 IP、reserved/multicast、userinfo、端口和 allowlist。相比旧的 `security.validate_url()`，这是明显进步。([GitHub][4])

但它仍然没有成为主路径：新的 `tools/builtins/network.py` 仍然调用旧的 `validate_url()` 和 `urllib.request.urlopen()`，不是 `fetch_url_hardened()`。旧 Agent dangerous tools 也继续使用旧 `fetch_url`。([GitHub][5])

---

## 1.3 thinking mode 有进步

`runtime._apply_thinking_mode()` 现在会在 thinking enabled 时移除 `temperature`、`top_p`、`presence_penalty`、`frequency_penalty` 并发 warning；这与 DeepSeek 当前文档方向一致，因为 thinking mode 下这些 sampling 参数不应被用户误以为有效。Runtime 在 tool call 场景也保留 `reasoning_content` 原文回传，这是 DeepSeek V4 tool calling + thinking mode 最重要的协议要求。DeepSeek 官方文档明确说明，如果 thinking mode 下 tool call 后没有正确回传 `reasoning_content`，API 会返回 400。([GitHub][1])

---

## 1.4 FIM 已经补上 4K guard

`fim.py` 现在对 `max_tokens > 4096` 抛 `ValueError`，这符合 DeepSeek FIM 官方说明：FIM completion 最大生成 token 是 4K，并且必须使用 `https://api.deepseek.com/beta`。 ([GitHub][6])

---

# 2. P0 级问题：更新后仍然存在的严重漏洞

## P0-1：PolicyEngine 仍不是不可绕过的执行内核

这是当前最大问题。

`ToolExecutor.execute()` 只有在 `tool_def.policy is not None` 时才执行 policy gate；无 policy 工具不会经过 `PolicyEngine.authorize()`。更严重的是，`execute_batch()` 中如果工具没有 policy，代码把它当成 safe read：`if policy else True`。这意味着无 policy 的危险工具既能绕过授权，又可能被并行执行。([GitHub][7])

与此同时，`ToolRuntime.chat()` 创建 `ToolExecutor` 时没有传入 policy engine、allowed capabilities、workspace root、allowed domains、sandbox 或 approval handler。Streaming runtime、batch runtime、async runtime 也同样没有安全上下文。([GitHub][1])

这导致 Agent 新增的 `allow_*` API 实际上几乎没有安全效果。Agent 里确实保存了 `_allowed_capabilities`、`_allowed_domains`、`_workspace_root`、`_sandbox`，但 `_make_runtime()` 创建 `ToolRuntime` 时没有把这些字段传进去。([GitHub][3])

**可利用路径：**

```python
agent = DeepSeekAgent(..., dangerous_tools=True)
agent.with_default_tools()

# 模型调用 run_python / read_file / query_sql
# 这些旧工具没有 ToolPolicy
# ToolExecutor 不进入 policy gate
# execute_batch 还默认 no-policy safe read
```

**修复要求：**

1. `ToolExecutor` 构造器必须接收 `policy_engine`、`execution_context`、`approval_handler`、`sandbox_manager`。
2. 无 policy 工具默认 `destructive + requires_approval`，不能默认 read。
3. `execute()` 中 policy gate 必须无条件执行。
4. `execute_batch()` 中无 policy 工具必须顺序执行或直接拒绝。
5. `ToolRuntime`、`AsyncToolRuntime`、`chat_stream()`、`chat_batch()` 都必须传入同一套 context。

---

## P0-2：旧版 dangerous tools 仍然是主路径

虽然安全工具工厂已经存在，但 `with_default_tools()` 仍然注册旧版工具。旧版 `read_file` 直接 `Path(path).read_text()`，没有 workspace root；旧版 `run_python` 直接把模型给的代码写到临时文件并用本机 Python subprocess 执行；旧版 `query_sql` 虽然有 `safe_join(Path.cwd(), db_path)` 和只读 URI，但仍然从 `agent.builtins` 暴露，且没有 ToolPolicy。([GitHub][3])

这意味着 `dangerous_tools=True` 仍然等于：

```text
模型可读宿主文件
模型可请求网络
模型可本机执行 Python
模型可查询 SQLite
模型可保存输出到本地 output/
```

而且因为这些旧工具作为普通 callable 注册，`tools.decorator._make_tool_definition()` 生成的 `ToolDefinition` 没有 policy。([GitHub][8])

**修复要求：**

`with_default_tools()` 必须改成：

```python
if self._dangerous_tools:
    if self._workspace_root:
        self.add_tool(make_read_file(workspace_root=self._workspace_root))
    if self._allowed_domains:
        self.add_tool(make_fetch_url(allowed_domains=self._allowed_domains))
    if self._sandbox:
        self.add_tool(make_python_exec(sandbox=self._sandbox))
    ...
```

旧版 `seekflow.agent.builtins.run_python/fetch_url/query_sql` 应标记 deprecated，并从 dangerous default path 移除。

---

## P0-3：timeout 机制仍不可靠，甚至可能根本不起作用

`ToolExecutor` 用 `ThreadPoolExecutor(max_workers=1)` 加 `future.result(timeout=effective_timeout)` 做超时。这个设计不是安全边界。更糟的是，它在 `with ThreadPoolExecutor(...) as pool:` 语句内等待 future；如果 `future.result(timeout=...)` 抛出 `TimeoutError`，上下文管理器退出时会调用 `shutdown(wait=True)`，通常会等待线程真实结束。因此一个永不返回的工具函数仍可能卡死 executor。([GitHub][7])

项目自己的 `docs/SECURITY.md` 也承认“Thread-based tool timeout cannot forcibly kill Python threads”，但 README 仍把 per-tool timeout 作为 production security feature。([GitHub][9])

**修复要求：**

| 工具类型              | 执行隔离                 |
| ----------------- | -------------------- |
| 纯计算、可信 read       | 线程可接受                |
| 文件/网络/SQL/MCP     | 进程或受控 wrapper        |
| 代码执行              | 容器 / nsjail / gVisor |
| destructive/write | 审批 + 独立进程            |

代码执行工具必须由 sandbox 执行，不能由通用 `ToolExecutor` 线程执行。

---

## P0-4：SSRF 防护模块存在，但主路径没用，而且 hardener 本身仍有漏洞

`security/http.py` 是好方向，但 `tools/builtins/network.py` 没有用它，而是继续使用旧 `validate_url()`。旧 `validate_url()` 的 DNS 解析失败逻辑是 fail-open：`_is_private_ip()` 遇到 `socket.getaddrinfo` 失败返回 False，调用方就可能放行。([GitHub][10])

新的 `fetch_url_hardened()` 也仍有生产问题：

1. 使用 `urllib.request.urlopen()`，默认会自动跟随重定向，所以代码中“检查 300 <= status < 400 再重新 validate”的逻辑很可能不会执行。
2. 先 `resp.read()` 再比较 `max_response_bytes`，会先把大响应读进内存，不能防止大响应 DoS。
3. 校验 DNS 结果后没有把连接固定到已校验 IP，仍存在 DNS rebinding / TOCTOU 风险。
4. `domain_allowed()` 没有 canonicalize allowed_domains，allowlist 如果传入大小写、尾点、IDNA 域名可能不一致。([GitHub][4])

**修复要求：**

改用 `httpx.Client(follow_redirects=False)`，每跳手动校验；stream 读取并在超过 `max_response_bytes` 时立刻中止；所有 A/AAAA 结果 fail-closed；必要时通过自定义 resolver 或连接 IP 固定解决 TOCTOU。

---

## P0-5：MCP 仍然是高危本地插件执行入口

`MCPServerConfig` 现在有 `trust_level` 和 `allowed_capabilities`，但没有 workspace root、allowed domains、sandbox、cwd、env allowlist、risk、approval 等完整 profile。`to_stdio_params()` 会把 `env` 传给 MCP SDK；manual fallback 的 `subprocess.Popen()` 没有传 `env`，因此会继承父进程环境变量，包括 `DEEPSEEK_API_KEY` 等敏感信息。([GitHub][11])

MCP 注册工具时创建 `ToolDefinition(..., source=cfg.name)`，但没有绑定 `ToolPolicy`。所以 MCP 工具进入 registry 后与普通无 policy 工具一样，可能绕过 policy gate。([GitHub][12])

还有一个协议级 bug：MCP tool 名称被转换成 `{server}.{tool}`，但 DeepSeek 文档要求 function name 只能包含字母、数字、下划线和短横线，最大 64 字符；点号 `.` 不合法。([GitHub][13])

**修复要求：**

```python
safe_name = f"{server_name}__{tool_name}"
safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", safe_name)[:64]
```

并建立映射：

```python
deepseek_name -> (server_name, original_tool_name)
```

MCP 注册时必须绑定 policy，并且 subprocess 必须默认空 env、显式 cwd、stderr 异步消费、断开时 terminate → wait → kill。

---

# 3. P1 级问题：更新方向对，但仍未生产化

## P1-1：版本仍然混乱

README 显示 `SeekFlow v0.2.0`，`pyproject.toml` 是 `0.2.5`，`src/seekflow/__init__.py` 仍是 `__version__ = "0.1.0"`。仓库页面也显示没有 published releases。([GitHub][14])

这会直接影响用户信任，也会破坏依赖锁定、bug report、PyPI 发布和安全公告。

**修复要求：**

```text
README version == pyproject.toml version == seekflow.__version__ == git tag == changelog
```

并添加版本一致性测试。

---

## P1-2：PolicyEngine 的测试与实现明显不一致

`tests/test_policy.py` 里明确写了“policy=None → restrictive default”，并断言无 policy 工具应 `allowed is False` 且 `requires_approval is True`。但 `policy.py` 中 `_DEFAULT_RESTRICTIVE_POLICY = ToolPolicy()`，而 `ToolPolicy` 默认 `risk="read"`、`requires_approval=False`，所以 `authorize()` 很可能返回 allowed。([GitHub][15])

这是一个非常危险的信号：**测试表达了正确安全意图，但代码没有实现。**

**修复要求：**

```python
_DEFAULT_RESTRICTIVE_POLICY = ToolPolicy(
    capabilities=set(),
    risk="destructive",
    parallel_safe=False,
    requires_approval=True,
)
```

同时 `ToolExecutor` 必须对无 policy 工具也执行这个默认策略。

---

## P1-3：Agent 的 capability profile 只是配置，没有真正生效

Agent 中新增了 `allow_filesystem()`、`allow_network()`、`allow_python()`、`allow_sqlite()`，这方向正确。但这些方法只是改了 Agent 内部字段，没有改变 `with_default_tools()` 注册的工具，也没有把字段传给 `ToolRuntime`。([GitHub][3])

例如：

```python
agent.allow_filesystem(root="/workspace")
```

不会自动注册 `tools/builtins/filesystem.make_read_file()`，也不会让旧版 `read_file` 限制在 `/workspace`。

**修复要求：**

`allow_*` 不应只是“存配置”，而应：

1. 注册对应安全工具 factory；
2. 更新 ToolExecutionContext；
3. 如果 runtime 已创建，强制 invalidate runtime；
4. 把 profile 传入 Runtime/Executor。

---

## P1-4：DeepSeek usage/cost 适配仍然错误

DeepSeek 当前 Chat Completion API 文档显示，`usage` 中有顶层 `prompt_cache_hit_tokens` 和 `prompt_cache_miss_tokens`，`prompt_tokens = hit + miss`，并且 `completion_tokens_details.reasoning_tokens` 表示 reasoning token。([DeepSeek API Docs][16])

但 `client.py` 仍主要尝试从 `response.usage.prompt_tokens_details` 里读取 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`，streaming `_usage_to_dict()` 只读取 `cached_tokens`。`runtime.py` 聚合 usage 时也只累计 `prompt_tokens_details.cached_tokens`。([GitHub][17])

项目新增了 `usage.py` 的 `NormalizedUsage`，但 runtime/client/cost/agent 没有统一使用它。([GitHub][18])

**修复要求：**

`normalize_usage()` 必须兼容三种格式：

```python
# 当前官方顶层字段
usage["prompt_cache_hit_tokens"]
usage["prompt_cache_miss_tokens"]

# 可能的 SDK extra/model_extra 字段
getattr(usage, "prompt_cache_hit_tokens", None)

# 旧兼容 nested 字段
usage["prompt_tokens_details"]["cached_tokens"]
```

并把 runtime、agent、cost、budget 全部改为使用 `NormalizedUsage`。

---

## P1-5：价格表过期、单位混乱、多个模块互相矛盾

DeepSeek 官方当前 pricing 页面显示：`deepseek-v4-flash` cache hit $0.0028 / miss $0.14 / output $0.28；`deepseek-v4-pro` cache hit $0.003625 / miss $0.435 / output $0.87，且 pro 折扣延长到 2026-05-31；官方也说明 `deepseek-chat` 和 `deepseek-reasoner` 只是 legacy 兼容名，对应 V4 Flash 的非 thinking / thinking 模式。([DeepSeek API Docs][19])

但项目里至少有三套价格表：

1. `agent/agent.py` 使用 CNY 字段，pro 仍是 1.74 / 0.028 / 3.48；
2. `models.py` 也标成 CNY，但值与当前官方不一致；
3. `cost.py` 中 flash cached_input 是 0.002，agent 中是 0.014，models.py 中是 0.014。([GitHub][3])

**修复要求：**

建立唯一 `pricing.py`，字段必须带 currency：

```python
@dataclass(frozen=True)
class Price:
    currency: Literal["USD", "CNY"]
    input_cache_hit_per_m: Decimal
    input_cache_miss_per_m: Decimal
    output_per_m: Decimal
    effective_from: datetime | None
    effective_until: datetime | None
```

同时所有 cost 计算必须引用同一个表。

---

## P1-6：Strict mode 基本不可用

DeepSeek strict tool mode 要求：

1. base URL 使用 `/beta`；
2. 每个 tool function 设置 `"strict": true`；
3. 每个 object 的所有 properties 必须出现在 `required`；
4. 每个 object 必须 `additionalProperties: false`。([DeepSeek API Docs][20])

SeekFlow 虽然 `ToolRuntime(strict=True)` 会切换 beta base URL，但 `ToolRegistry.to_deepseek_tools(strict=True)` 完全没有使用 `strict` 参数，也没有给 function 添加 `"strict": true`。`tools/schema.py` 也不会为 object 自动添加 `additionalProperties: false`，Optional 参数也不会在 strict 模式下转成 required。([GitHub][21])

`tools/strict.py` 只给 warning，而不是自动修复或 fail。([GitHub][22])

**修复要求：**

```python
def to_deepseek_tools(strict: bool = False):
    ...
    if strict:
        fn["strict"] = True
        fn["parameters"] = make_deepseek_strict_schema(td.parameters)
```

严格模式下 schema 不兼容应 fail-fast，不能只是 warning 后 fallback，除非用户显式 `strict_fallback=True`。

---

## P1-7：Prompt cache 仍然会被 append_only_compress 破坏

`CacheStabilizer.ensure_stable_prefix()` 已经能把 drift 从 system message 拆到单独 user context，这是正确方向。([GitHub][23])

但 `append_only_compress()` 仍然把 compressed summary 拼回第一条 system message 的 content：`enhanced_system["content"] = original_content + ...`。这与注释“system message never changes”矛盾，也会改变 DeepSeek cache 的最关键前缀。([GitHub][23])

**修复要求：**

压缩摘要必须作为独立 message：

```python
result = [system_msg]
result.append({
    "role": "user",
    "content": f"[Compressed Context]\n{summary}"
})
result.extend(recent)
```

不能改 `messages[0]["content"]`。

---

## P1-8：JSON mode 只设置了 response_format，没有完整 contract

DeepSeek 文档说明，使用 JSON Output 时，除了设置 `response_format={"type":"json_object"}`，还必须在 system/user message 中明确要求模型输出 JSON，否则可能生成大量空白直到 token limit。([DeepSeek API Docs][16])

Agent `_make_messages()` 会在 task 不含 json 时追加“请以JSON格式输出”，这是好事；但 `ToolRuntime.chat()` 作为底层 API 只设置 response_format，不自动校验 prompt 是否包含 JSON 指令，也不验证最终输出是否为合法 JSON。([GitHub][1])

**修复要求：**

Runtime 层也应提供 `json_mode_contract=True`：

1. 检查消息中是否包含 JSON 指令；
2. 输出后 `json.loads()` 验证；
3. `finish_reason == "length"` 时标记不可信；
4. 支持 Pydantic model validation + retry。

---

## P1-9：Streaming usage 很可能拿不到

DeepSeek Chat Completion 文档说明，streaming 使用 usage 需要 `stream_options.include_usage=true`。([DeepSeek API Docs][16])

`client.chat_stream()` 捕获 usage chunk，但没有在请求 params 中自动设置 `stream_options={"include_usage": True}`。因此 `stream_usage` 很可能长期为 None。([GitHub][17])

**修复要求：**

```python
if stream:
    params.setdefault("stream_options", {"include_usage": True})
```

---

# 4. 其他重要漏洞与工程问题

## 4.1 文件读取安全工具自身有相对路径 bug

`validate_file_access()` 先执行 `Path(path).exists()`，再执行 `safe_join(workspace_root, str(path))`。如果传入相对路径 `"data.txt"`，而文件实际在 workspace root 下，但当前进程 cwd 不等于 workspace root，那么第一步 `Path("data.txt").exists()` 会失败。([GitHub][10])

正确顺序应该是：

```python
resolved = safe_join(workspace_root, str(path))
if not resolved.exists():
    raise FileNotFoundError(...)
```

否则新的 `make_read_file()` 在常见部署中会误报文件不存在。([GitHub][24])

---

## 4.2 新 `fetch_url_hardened()` 存在 redirect 与大响应问题

如前面所说，它用 urllib，默认自动 follow redirect；而响应体是先整体 `read()`，再截断。对于生产 SSRF 防护和 DoS 防护都不够。([GitHub][4])

---

## 4.3 SQL 工具有进步，但仍需收紧

新的 SQLite 工具用了只读 URI、authorizer、progress handler、max rows，这些是对的。([GitHub][25])

还建议继续加强：

```text
1. 用 sqlglot 或 sqlite parser 判断单条 SELECT，而不是 startswith("SELECT")。
2. finally 中确保 conn.close()。
3. 禁止超大 BLOB 返回。
4. 所有错误返回也应被 wrap_untrusted。
5. data.sqlite capability 应在 PolicyEngine 中被识别。
```

---

## 4.4 Approval 机制缺失

当前 `PolicyEngine` 能返回 `requires_approval=True`，但 `ToolExecutor` 遇到 requires approval 只会返回错误，没有 approval handler。([GitHub][7])

这会导致两个结果：

1. 真正需要 approval 的安全工具无法正常使用；
2. 用户可能为了让功能可用，把 `requires_approval=False`，反而降低安全性。

应新增：

```python
class ApprovalHandler(Protocol):
    def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        ...
```

---

## 4.5 安全文档与实现不一致

`docs/SECURITY.md` 声称 “Policy Engine: every tool call authorized before execution”，但当前代码只对有 policy 的工具授权，无 policy 直接绕过。([GitHub][9])

README 仍写 “Production-grade security”，但当前没有发布 release，版本混乱，安全主链路未闭环。([GitHub][14])

---

# 5. 更新是否正确：逐项评价

| 更新项                            | 是否正确 | 评价                                            |
| ------------------------------ | ---- | --------------------------------------------- |
| 新增 safe builtin factories      | 部分正确 | 代码方向对，但 Agent 没用                              |
| 新增 `security/http.py`          | 部分正确 | 方向对，但主路径没用，redirect/stream 仍有问题               |
| Agent `allow_*` API            | 不完整  | 只是存配置，没有传入 runtime/executor                   |
| ToolExecutor policy gate       | 不完整  | 只对有 policy 工具执行，无 policy 反而绕过                 |
| no-policy 默认拒绝                 | 未实现  | 测试想要，但实现不是                                    |
| FIM 4K guard                   | 正确   | 已符合官方 4K 限制                                   |
| thinking 参数清理                  | 正确   | 已有实质改进                                        |
| reasoning_content tool-call 回传 | 基本正确 | 非 tool final 压缩仍需谨慎                           |
| UsageNormalizer                | 方向正确 | 没有接入 runtime/client/cost                      |
| ModelRegistry                  | 方向正确 | 价格过期、单位混乱、未接入主链路                              |
| Strict schema                  | 未完成  | strict 参数未进入 tool schema                      |
| MCP trust level                | 不完整  | 没有 sandbox/policy/env/cwd 闭环                  |
| CacheStabilizer                | 部分正确 | ensure_stable_prefix 对，append_only_compress 错 |

---

# 6. 修复优先级路线图

## 立即修复：P0 安全闭环

### 任务 1：ToolExecutor policy 强制化

目标：**所有 tool call 必须过 policy。**

```python
policy = tool_def.policy or ToolPolicy.default_untrusted()
decision = self.policy_engine.authorize(
    tool_def=tool_def,
    args=arguments,
    context=self.context,
)
```

无 policy 默认：

```python
ToolPolicy(
    capabilities=set(),
    risk="destructive",
    requires_approval=True,
    parallel_safe=False,
)
```

验收测试：

```text
无 policy 工具：拒绝或 approval_required
dangerous_tools=True 下旧工具不允许绕过
execute_batch 无 policy 不并行
code.exec 无 sandbox 拒绝
network 无 allowed_domains 拒绝
filesystem 无 workspace_root 拒绝
```

---

### 任务 2：Agent 使用新的 safe builtin factories

`with_default_tools()` 改为：

```python
self.add_tool(safe_calculate)

if self._workspace_root:
    self.add_tool(make_read_file(workspace_root=self._workspace_root))

if self._allowed_domains:
    self.add_tool(make_fetch_url(allowed_domains=self._allowed_domains))

if self._sandbox:
    self.add_tool(make_python_exec(sandbox=self._sandbox))

if self._sqlite_root:
    self.add_tool(make_sqlite_query(workspace_root=self._sqlite_root))
```

旧的 `agent.builtins` 只能保留为 deprecated 兼容模块，不允许进入默认路径。

---

### 任务 3：Runtime 传递执行上下文

新增：

```python
@dataclass(frozen=True)
class ToolExecutionContext:
    run_id: str
    dangerous_tools_enabled: bool
    allowed_capabilities: set[str]
    max_risk: RiskLevel
    workspace_root: Path | None
    allowed_domains: set[str]
    sandbox: ToolSandbox | None
    tenant_id: str | None = None
    user_id: str | None = None
```

`ToolRuntime.__init__()`、`AsyncToolRuntime.__init__()` 必须接收并保存。创建 executor 时必须传入。

---

### 任务 4：彻底禁用旧 `run_python`

旧 `agent.builtins.run_python()` 当前直接本机 subprocess 执行，必须从 dangerous default 移除。([GitHub][26])

代码执行只能走：

```python
make_python_exec(sandbox=ContainerSandbox(...))
```

并且 approval 默认 required。

---

## 第二阶段：DeepSeek-native 正确性

### 任务 5：统一 usage/cost

建立唯一链路：

```text
DeepSeekClient raw usage
  -> normalize_usage()
  -> Runtime usage accumulator
  -> AgentResult cost
  -> CostTracker/BudgetGuard
```

必须支持官方顶层字段：

```python
hit = usage.get("prompt_cache_hit_tokens")
miss = usage.get("prompt_cache_miss_tokens")
```

以及 SDK object attribute / model_extra。

---

### 任务 6：修复价格表

删除 `agent.PRICING`、`budget._PRICING`、`cost.PRICING`、`models.DEEPSEEK_MODELS` 里的重复价格，保留唯一 `pricing.py`。

当前官方 pricing 应作为默认值，但文档要注明价格可能变动。DeepSeek 官方也建议用户定期检查 pricing 页面。([DeepSeek API Docs][19])

---

### 任务 7：真正实现 strict mode

```python
if strict:
    function["strict"] = True
    parameters = make_deepseek_strict_schema(parameters)
```

strict schema 自动修复：

```text
object.additionalProperties = false
object.required = 所有 properties
不支持字段 fail-fast
```

DeepSeek 官方 strict mode 明确要求 beta base URL、function strict=true，并由服务端校验 schema。([DeepSeek API Docs][20])

---

## 第三阶段：性能与架构极致优化

### 任务 8：cache-first runtime

当前 `_runtime_base.trim_messages()` 是 destructive trimming，会丢旧消息；`append_only_compress()` 又会修改 system message。([GitHub][27])

推荐架构：

```text
messages[0] = frozen system prompt
messages[1] = frozen deterministic tool/policy summary
messages[2] = dynamic compressed context
messages[3:] = recent turns
```

所有压缩摘要放到 `messages[2]` 或后续，不允许改 `messages[0]`。

指标：

```text
prefix_hash
prefix_drift_count
cache_hit_tokens
cache_miss_tokens
cache_hit_ratio
cost_saved
```

---

### 任务 9：MCP 安全与 schema 正确性

MCP 必须改：

```text
server.tool -> server__tool
绑定 ToolPolicy
默认空 env
显式 cwd
stderr drain
sandbox profile
disconnect 强杀
```

DeepSeek function name 不允许 `.`，所以当前 `{server}.{tool}` 是协议层错误。([GitHub][13])

---

### 任务 10：真实 CI 与发布质量

当前 `pyproject.toml` 仍然对大量核心模块 `ignore_errors=true`，包括 runtime、agent、mcp、fim、structured、cost、truncation 等。([GitHub][28])

必须逐步移除：

```text
第一批：security, policy, tools, sandbox, usage, models, cost
第二批：runtime, async_runtime
第三批：agent, mcp
```

CI 必须包含：

```text
ruff
mypy subset
pytest
bandit
pip-audit
version consistency
security regression tests
```

---

# 7. 最终风险结论

SeekFlow 这次更新**不是失败**，但也**没有达到生产级**。它现在处于一个典型的“重构中间态”：

```text
安全模块：有
安全工厂：有
模型注册表：有
usage normalizer：有
strict checker：有
MCP trust level：有
但主执行链路没有全部接上
```

最危险的一句话概括是：

> **SeekFlow 现在看起来有 policy，但旧 dangerous tools 仍可无 policy 执行。**

这比完全没有安全模块更容易误导用户，因为 README 和 SECURITY 文档会让用户以为“every tool call authorized before execution”，但实际 `ToolExecutor` 只在 `tool_def.policy is not None` 时授权。([GitHub][9])

---

# 8. 我建议的下一版目标

下一版不要叫“新增功能版”，应该叫：

```text
v0.3.0 — Enforcement Core
```

唯一目标：

```text
任何 LLM 产生的 tool call 都必须经过：
schema validation
-> policy authorization
-> approval / sandbox
-> audited execution
-> untrusted output wrapping
```

完成这个目标后，SeekFlow 才真正有资格把自己定位为：

> DeepSeek-native, policy-enforced, sandbox-first Agent Runtime.

目前它仍然是一个**方向很对、组件逐渐齐全、但执行内核没有完全闭合的安全硬化 beta 框架**。

[1]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/runtime.py "raw.githubusercontent.com"
[2]: https://github.com/WYZAAACCC/SeekFlow/tree/main/src/seekflow/tools/builtins "SeekFlow/src/seekflow/tools/builtins at main · WYZAAACCC/SeekFlow · GitHub"
[3]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/agent/agent.py "raw.githubusercontent.com"
[4]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/security/http.py "raw.githubusercontent.com"
[5]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/builtins/network.py "raw.githubusercontent.com"
[6]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/fim.py "raw.githubusercontent.com"
[7]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/executor.py "raw.githubusercontent.com"
[8]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/decorator.py "raw.githubusercontent.com"
[9]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/docs/SECURITY.md "raw.githubusercontent.com"
[10]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/security.py "raw.githubusercontent.com"
[11]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/mcp/config.py "raw.githubusercontent.com"
[12]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/mcp/executor.py "raw.githubusercontent.com"
[13]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/mcp/adapter.py "raw.githubusercontent.com"
[14]: https://github.com/WYZAAACCC/SeekFlow "GitHub - WYZAAACCC/SeekFlow: DeepSeek-native agent framework with production-grade reliability · GitHub"
[15]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/tests/test_policy.py "raw.githubusercontent.com"
[16]: https://api-docs.deepseek.com/api/create-chat-completion "Create Chat Completion | DeepSeek API Docs"
[17]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/client.py "raw.githubusercontent.com"
[18]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/usage.py "raw.githubusercontent.com"
[19]: https://api-docs.deepseek.com/quick_start/pricing "Models & Pricing | DeepSeek API Docs"
[20]: https://api-docs.deepseek.com/guides/tool_calls "Tool Calls | DeepSeek API Docs"
[21]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/registry.py "raw.githubusercontent.com"
[22]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/strict.py "raw.githubusercontent.com"
[23]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/cache.py "raw.githubusercontent.com"
[24]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/builtins/filesystem.py "raw.githubusercontent.com"
[25]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/tools/builtins/sqlite.py "raw.githubusercontent.com"
[26]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/agent/builtins.py "raw.githubusercontent.com"
[27]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/src/seekflow/_runtime_base.py "raw.githubusercontent.com"
[28]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/pyproject.toml "raw.githubusercontent.com"
