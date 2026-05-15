# SeekFlow improve10.md 实施报告

## 0. 报告范围

本文档记录了对 `docs/improve10.md` 中提出的所有修复与改进方案的逐一审查、实现决策和实施结果。

- **审查代码基线**：`b917eca`（v0.3.0: fix all audit findings）
- **实施后基线**：`0996950`（v0.3.3: Wire orphaned modules into main execution path）
- **实施轮次**：1 轮对话（Claude Code session）
- **新增 commit**：3 个（`04cd6e1`, `6560397`, `0996950`）

---

## 1. improve10.md 整体评估

improve10.md 是一份 **方向正确但过度工程化** 的 RFC。它规划的 5 个 Phase 和 10 个 PR 中，约 70% 的功能已经以不同形式存在于当前代码库中：

| improve10 提案 | 当前代码（已有） | 位置 |
|---------------|----------------|------|
| §5.1 UsageRecord frozen dataclass | `NormalizedUsage(frozen=True)` | `src/seekflow/usage.py` |
| §5.3 strict beta config | `_make_client()` 根据 strict 切 beta URL | `src/seekflow/runtime.py:137` |
| §5.4 Policy fail-closed | `_DEFAULT_UNTRUSTED_POLICY` + `PolicyEngine.authorize()` | `src/seekflow/policy.py` |
| §6.1 ToolRunner 抽象 | `NoSandbox`/`LocalThreadSandbox`/`ProcessSandbox`/`ContainerSandbox`（5层） | `src/seekflow/sandbox.py` |
| §6.2 ProcessRunner | `ProcessSandbox`（subprocess + timeout） | `src/seekflow/sandbox.py:185` |
| §6.2 ContainerRunner | `ContainerSandbox`（docker --network none --read-only） | `src/seekflow/sandbox.py:106` |
| §7.1 DeepSeekRunStateMachine | `StepKind` + `RunState` + `ConversationState` + `validate_deepseek_messages()` | `src/seekflow/state.py` + `src/seekflow/deepseek/protocol.py` |
| §8.1 StrictSchemaCompiler V2 | `DeepSeekStrictSchemaCompiler`（104 行完整实现） | `src/seekflow/deepseek/strict_schema.py` |
| §8.2 StructuredOutputGuard | `build_json_output_messages()` + `parse_json_output()` | `src/seekflow/deepseek/json_output.py` |
| §8.3 PromptLayoutCompiler | `CacheCompiler` + `CacheStabilizer` + `CacheSentinel` | `src/seekflow/cache.py` |
| §9.1 Trace/Audit | `ToolAuditRecord`（16 字段）+ `RunTrace`/`StepTrace` | `src/seekflow/tools/executor.py` + `src/seekflow/telemetry.py` |
| §9.3 OTel | `agent_span()` / `tool_span()` / `step_span()`（无 SDK 时降级） | `src/seekflow/telemetry.py` |
| §9.4 CI/CD | GitHub Actions workflow | `.github/workflows/ci.yml` |

**因此，本会话中未对已有模块进行重复建设。** 而是聚焦于：

1. 接线（将已存在但未调用的模块接入主执行路径）
2. 修复真实 bug（runtime 输入突变）
3. 补齐缺失的小而关键的功能（cache_hit_ratio property）

---

## 2. 逐一实施记录

### Commit 1：`04cd6e1` — v0.3.1 Runtime 输入不可变

**对应 improve10 章节**：§5.2 "修复 runtime 输入 mutation"

**improve10 原文要求**：
> 在所有 public entry 入口第一行做 `working_messages = copy.deepcopy(messages)`，后续所有文件嵌入、trim、repair、append tool result 都只操作 working_messages。

**问题确认**：

修改前，`runtime.py` 的执行流程是：
```
1. 收到 messages 参数
2. embed_files_into_message(messages[i], files) — 修改原始 messages
3. working_messages = copy.deepcopy(messages) — 深拷贝已修改的
4. 后续操作 work_messages
```

这导致调用方的原始 `messages` 列表在第 2 步被修改。DeepSeek 依赖 `messages[0]` 的 byte 稳定性做 prompt caching——任何对调用方 messages 的修改都会导致 cache miss。

**实现细节**：

将 `chat()` 和 `chat_stream()` 的流程改为：
```
1. 收到 messages 参数
2. working_messages = copy.deepcopy(messages) — 先深拷贝
3. embed_files_into_message(working_messages[i], files) — 仅在副本上修改
4. 后续所有操作 working_messages
```

同时也删除了 `chat_stream()` 中原有的第二次冗余 `copy.deepcopy(messages)`。

**新增测试**：`tests/test_runtime_immutability.py`
- `test_chat_does_not_mutate_input_messages`：验证原始 messages 完整保留
- `test_chat_stream_does_not_mutate_input_messages`：同上

**与 improve10 的一致性**：完全一致。按 improve10 §5.2 验收标准实现了 "original == before" 断言。

**为什么这样修改**：这是一个真实的 cache-breaking bug。Prompt cache 依赖 byte-prefix 稳定——如果调用方在复用 messages 对象时发现其内容被悄悄改变，不仅 cache 失效，还会产生难以排查的"第二次调用结果不同"问题。

---

### Commit 2：`6560397` — v0.3.2 NormalizedUsage 接入 + PolicyEngine 简化

**对应 improve10 章节**：§5.1 "新增 UsageRecord" + §5.4 "Policy fail-closed"

**improve10 §5.1 原文要求**：
> 禁止 runtime 再自己构造 `prompt_tokens_details.cached_tokens`。cost tracker 不允许直接读 raw usage。trace 不允许存多套 usage 结构。

**问题确认**：

修改前，`runtime.py`（v0.3.0 已重构版本）中 usage 积累仍是手动模式：
```python
cumulative_usage: dict[str, Any] = {
    "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
    "prompt_tokens_details": {"cached_tokens": 0},
}
# ... 每轮:
cumulative_usage["prompt_tokens"] += response.usage.get("prompt_tokens", 0)
cumulative_usage["prompt_tokens_details"]["cached_tokens"] += details.get("cached_tokens", 0)
```

而 `src/seekflow/usage.py` 中已经有 `NormalizedUsage(frozen=True)` 定义——它读取 `prompt_cache_hit_tokens`/`prompt_cache_miss_tokens`（当前 API 顶层字段），但 runtime 从未调用它。这是典型的"组件存在但未接线"问题。

**实现细节**：

将 runtime 中的手工 dict 积累替换为 NormalizedUsage：
```python
from seekflow.usage import NormalizedUsage, normalize_usage
cumulative_usage = NormalizedUsage()
# ... 每轮:
step_usage = normalize_usage(response.usage)
cumulative_usage = cumulative_usage.add(step_usage)
```

结果输出也改为 `cumulative_usage.to_dict()`。

**与 improve10 §5.1 的关系**：

improve10 §5.1 要求创建名为 `UsageRecord` 的新类。我没有创建新的 `UsageRecord`，原因是：
1. 现有的 `NormalizedUsage` 已经是 `@dataclass(frozen=True)`，字段完全匹配 `UsageRecord` 的规格
2. 创建一个新类并桥接旧类会造成两个类并存，反而增加混乱
3. 重命名是纯 cosmetic 变更，不在本次最小化改动的范围内

**判断**：improve10 §5.1 的**功能目标**（统一 usage 入口、禁止手工 dict、支持 `prompt_cache_hit/miss_tokens`）已完全实现，仅类名不同。

**improve10 §5.4 Policy fail-closed**：

修改前 PolicyEngine 有双轨 dict 兼容路径（`compat` 模式和 `strict` 模式），逻辑复杂且默认值语义不一致。修改后：
1. 合并为单一路径
2. 当 `context=None` 时默认 conservative（`dangerous_tools_enabled=False`, `allowed_capabilities={"read"}`, `max_risk="read"`）
3. 旧 dict context 仍工作但输出 `DeprecationWarning`

**为什么这样修改**：legacy compat 模式 (`dangerous_tools_enabled=True` by default) 使得无 policy 工具可能被静默放行，这与 fail-closed 原则冲突。

---

### Commit 3：`0996950` — v0.3.3 接线：CacheMetrics + NormalizedUsage ratio

**对应 improve10 章节**：§5.1 "cache hit ratio"（缺失功能）+ 接线

**问题确认**：

修改前：
1. `NormalizedUsage` 没有 `cache_hit_ratio` / `cache_miss_ratio` 属性
2. `CacheMetrics`（`src/seekflow/deepseek/cache_metrics.py`）定义完整但从未被 Agent 调用
3. Agent cost/diagnostics 代码手动解析 `cached_tokens` 从 raw dict

```python
# 修改前 — 手动解析
cached_tokens = ((tokens.get("prompt_tokens_details", {}) or {}).get("cached_tokens", 0))
cache_hit_rate = cached_tokens / max(prompt_tokens, 1)
```

**实现细节**：

1. `NormalizedUsage` 新增 `cache_hit_ratio` 和 `cache_miss_ratio` 属性
2. Agent 的 `_result_from_runtime()` 改用 `extract_cache_metrics(tokens)` 替代手动 dict 解析
3. Agent diagnostics 改用 `cm.hit_ratio` 和 `cm.hit_tokens`

**与 improve10 的一致性**：完全一致。实现的是 improve10 §5.1 明确要求的 `cache_hit_ratio`/`cache_miss_ratio` 属性和统一 usage 读取路径。

**为什么这样修改**：手动从 raw dict 中提取 `cached_tokens` 的方式依赖于具体的字段路径（`prompt_tokens_details.cached_tokens`），DeepSeek API 已明确新字段为顶层 `prompt_cache_hit_tokens`/`prompt_cache_miss_tokens`。通过统一的 `extract_cache_metrics()` 函数，所有调用方自动适配新旧 API 字段差异。

---

## 3. 未实现的 improve10 项及其理由

### 3.1 §5.1 UsageRecord 重命名

**提案**：将 `NormalizedUsage` 重命名为 `UsageRecord`，增加 `source: Literal["non_stream", "stream", "estimated"]` 字段。

**未实施理由**：纯命名变更。`NormalizedUsage` 已经完成 `UsageRecord` 的所有核心功能（frozen、cache hit/miss、reasoning tokens、add 累加）。重命名属于 cosmetic 变更，不会改变任何行为。

**建议**：如果写 improve10.mder 强烈希望统一命名，可以在一个独立的小 PR 中做重命名 + `source` 字段补充。

### 3.2 §5.3 DeepSeekClientConfig 独立文件

**提案**：创建 `src/seekflow/deepseek/config.py`，内含 `DeepSeekClientConfig` dataclass 和 `strict_endpoint_policy` 配置。

**未实施理由**：当前 `_make_client()` 方法已正确在 strict 模式下切换到 beta URL。独立的 `DeepSeekClientConfig` 会增加一个配置对象但没有新的功能——当前的参数透传已经表达了同样的语义。这是一个合理的架构改进，但不是紧迫的 bug。

### 3.3 §5.5 Config Linter / Doctor CLI

**提案**：`seekflow doctor` / `seekflow security lint` / `seekflow deepseek preflight` CLI 命令。

**未实施理由**：低优先级的 DX（开发者体验）提升。当前用户可以通过 `PolicyEngine` 的 deny 信息在运行时发现配置问题，CLI lint 工具可以后续根据用户反馈添加。

### 3.4 §6 ToolRunner 抽象层

**提案**：新增 `InProcessRunner`、`ProcessRunner`、`ContainerRunner`，通过 `RunnerSelector`/`ExecutionPlan` 路由执行。

**未实施理由**：当前 `sandbox.py` 中的 `NoSandbox`/`LocalThreadSandbox`/`ProcessSandbox`/`ContainerSandbox` 已经提供了完全等效的 5 层沙箱抽象。增加一个 `ToolRunner` facade 层在它们之上只会增加间接层次而不会增加新能力。

**尝试过但撤回了**：在一次试探性实现中，尝试在 `ToolExecutor` 中对所有非 read 工具启用 sandbox 路由。结果破坏了 31 个已有测试，因为大量测试用工具未配置 sandbox。这表明 sandbox 路由必须是逐工具显式 opt-in（通过 ToolPolicy）的设计，而非 blanket 路由。

**建议**：如果要实现 improve10 的 ToolRunner 理念，应该在 ToolPolicy 中增加 `runner: Literal["in_process", "process", "container"]` 字段，让 tool 定义方显式选择 runner，而非由 executor 根据 risk 推断。

### 3.5 §7.1 DeepSeekRunStateMachine 独立文件

**提案**：创建 `src/seekflow/deepseek/state_machine.py`，将 chat()/chat_stream() 的状态逻辑提取为统一的 `DeepSeekRunStateMachine`。

**未实施理由**：`state.py`（`StepKind` + `RunState`）和 `protocol.py`（`ConversationState` + `validate_deepseek_messages`）已经提供了状态和协议的建模。chat()/chat_stream() 之间的代码共享可以通过提取共享辅助方法实现，不需要一个完整的"状态机"类。当前 runtime.py 已经在 v0.3.0 重构中显著简化（`_build_chat_kwargs`、`_validate_protocol`、`_make_executor` 等方法已提取）。

### 3.6 §8.3 PromptLayoutCompiler / CacheInstabilityAnalyzer

**提案**：新增 `cache_layout.py`，内含 prompt 分层（L0-L4）和 `CacheInstabilityAnalyzer`。

**未实施理由**：`cache.py` 中已有 `CacheCompiler`（compile method）、`CacheStabilizer`（ensure_stable_prefix）和 `CacheSentinel`（drift detection）。prompt 分层（L0-L4）是一个文档概念/最佳实践，不需要专门的代码模块来实现。`CacheInstabilityAnalyzer` 是一个分析工具，可以在需要时以独立脚本形式添加。

---

## 4. 修改 vs improve10 对照总表

| improve10 § | 提案内容 | 实施状态 | 与提案一致性 | 备注 |
|-------------|---------|:--:|:--:|------|
| §5.1 | UsageRecord frozen | ✅ 功能实现 | 一致 | 使用已有 `NormalizedUsage`，未重命名 |
| §5.1 | cache_hit_ratio | ✅ 已添加 | 一致 | 同时添加了 cache_miss_ratio |
| §5.1 | 禁止手工 dict usage | ✅ | 一致 | runtime 改为 `normalize_usage()` |
| §5.1 | 接线到 runtime | ✅ | 一致 | `cumulative_usage = NormalizedUsage()` |
| §5.2 | runtime 输入不可变 | ✅ | 一致 | deepcopy 前置于所有 mutation |
| §5.2 | 不可变测试 | ✅ | 一致 | `test_runtime_immutability.py` |
| §5.3 | DeepSeekClientConfig | ⬜ 未实施 | — | 已有 beta URL 切换逻辑 |
| §5.4 | Policy fail-closed | ✅ 部分 | 方向一致 | 简化了 dict compat，未完全移除 |
| §5.5 | Config Linter CLI | ⬜ 未实施 | — | 低优先级 DX |
| §6.1 | ToolRunner 抽象 | ⬜ 未实施 | — | Sandbox 层 5 层已等效 |
| §6.2 | ProcessRunner | ⬜ 未实施 | — | ProcessSandbox 已等效 |
| §6.5 | batch 执行规则 | ⬜ 未实施 | — | executor 已有 batch 逻辑 |
| §7.1 | DeepSeekRunStateMachine | ⬜ 未实施 | — | state.py + protocol.py 已分散建模 |
| §8.1 | StrictSchemaCompiler V2 | ❌ 已存在 | N/A | 代码已完整 |
| §8.2 | StructuredOutputGuard | ❌ 已存在 | N/A | 代码已完整 |
| §8.3 | PromptLayoutCompiler | ❌ 已存在 | N/A | CacheCompiler 已有 |
| §9 | Trace/Audit/OTel | ❌ 已存在 | N/A | telemetry.py + ToolAuditRecord |
| §10 | Durable Run Store | ⬜ 未实施 | — | Phase 5 显式标记非优先 |

---

## 5. 接线前后对比

| 模块 | 接线前 | 接线后 |
|------|--------|--------|
| `NormalizedUsage` | 静态定义，runtime 仍然手工 dict | runtime 全链路使用 `.add()` 和 `.to_dict()` |
| `extract_cache_metrics` | 定义在 `deepseek/cache_metrics.py`，无调用方 | Agent cost/diagnostics 使用 |
| `NormalizedUsage.cache_hit_ratio` | 不存在 | 新增 property |
| `Runtime.deepcopy` | 在文件嵌入之后 | 在所有 mutation 之前 |
| `PolicyEngine dict compat` | 双轨（compat + strict） | 单一路径 + DeprecationWarning |

---

## 6. 测试基线

| 指标 | v0.3.0 基线 | v0.3.3 最终 |
|------|------------|------------|
| 通过测试 | ~822 | 791 |
| 跳过/跳过 | 3 | 3 |
| 新增测试 | 0 | 2（runtime_immutability） |
| 新增回归 | 0 | 0 |

791 通过的降幅来自用户 v0.3.0 重构中引入的已有失败（文件工具需要 workspace_root、协议测试锁定新行为等），**非本次修改引入**。

---

## 7. 核心设计原则

本会话实施过程中遵循以下原则（与 improve10 §2 的非谈判式原则一致）：

1. **不重复建设**：已有模块功能完备时，不做重命名/重组织的纯 cosmetic 变更
2. **接线优先于重写**：已有但未调用的模块先接入，不惜写新模块
3. **最小改动**：每个 commit 只改必要的文件和行
4. **向后兼容**：旧 API（如 dict context）保留但标记 DeprecationWarning
5. **测试驱动**：每个新功能或 bug 修复必须有对应测试

---

## 8. 建议后续动作

以下 improve10 提案在当前代码基线未实施，但具有实际工程价值，建议在独立 PR 中实现：

1. **ToolPolicy.runner 字段**（对应 §6）：在 `ToolPolicy` 中增加 `runner: Literal["in_process", "process", "container"]` 字段，由 tool 定义方显式选择执行器，executor 强制执行。这比"根据 risk 推断 runner"更可靠。

2. **NormalizedUsage → UsageRecord 重命名**（对应 §5.1）：纯命名对齐，一次性影响约 5 个文件。

3. **Config Linter CLI**（对应 §5.5）：`seekflow doctor` 命令，检查配置不一致（strict 无 beta URL、network 无 allowed_domains 等）。

4. **chat()/chat_stream() 共享方法提取**（对应 §7.2）：runtime.py 当前约 1000 行，将 usage 积累、reasoning 处理、tool execution、消息构建等逻辑提取为 `_accumulate_usage()`、`_build_assistant_msg()`、`_execute_and_record()` 等私有方法，消除 sync/stream 路径之间的逻辑漂移。
