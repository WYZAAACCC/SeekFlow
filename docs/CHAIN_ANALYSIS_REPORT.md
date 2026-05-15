# SeekFlow 全链路静态 + 动态分析报告

**代码基线**: `9ff7494` (v0.3.4)
**测试基线**: 792 passed / 47 failed (均为已有) / 3 skipped

---

## 1. 执行链路逐条审计

### Chain 1：Agent.run() → Runtime → Executor 主链路

```
DeepSeekAgent.run()
  → _make_runtime()
    → PolicyEngine()                          ✅ 已接线
    → ToolExecutionContext(...)                ✅ 已接线
    → ToolRuntime(policy_engine=..., policy_context=...)
      → chat() / chat_stream() / chat_batch()
        → _make_executor()
          → ToolExecutor(policy_engine=..., context=..., approval_handler=..., sandbox=...)
            → execute()
```

| 环节 | 文件:行 | 状态 |
|------|---------|:--:|
| Agent 创建 PolicyEngine | `agent.py:746` | ✅ |
| Agent 创建 ToolExecutionContext | `agent.py:750` | ✅ |
| Agent 传递给 ToolRuntime | `agent.py:768-769` | ✅ |
| Runtime.chat 传给 executor | `runtime.py:224-233` | ✅ |
| Runtime.chat_stream 传给 executor | `runtime.py:547-555` | ✅ |
| Runtime.chat_batch 传给 executor | `runtime.py:858-861` | ✅ |
| AsyncRuntime 传给 executor | `async_runtime.py:187` | ✅ |

**结论**: ✅ 主链路全线贯通。Agent/Runtime/Executor 之间的 PolicyEngine + ToolExecutionContext 传递在所有模式（sync/stream/batch/async）下均完整。

---

### Chain 2：ToolExecutor.execute() 安全执行链

```
tool_call
  → lookup tool                                    ✅ line 88
  → policy authorize                               ✅ line 150
    → PolicyEngine.authorize(tool_def, args, context)
      → no_policy → deny                           ✅
      → dangerous disable → deny                   ✅
      → max_risk ceiling → deny                    ✅
      → capability gate → deny                     ✅
      → destructive → approval                    ✅
      → code_exec → sandbox check                  ✅
      → filesystem → workspace check               ✅
      → network → allowed_domains check            ✅
      → requires_approval → approval handler       ✅
  → cache lookup (AFTER policy)                    ✅ line 202
  → coerce arguments                               ✅
  → execute (timeout)                              ✅
  → untrusted wrap + redact                        ✅ line 270-280
  → truncate                                       ✅
  → audit record                                   ✅ line 308
```

**结论**: ✅ 执行链条完整。Policy gate 无条件触发，cache 在 policy 之后，approval handler 真实调用，untrusted wrap + redact 在所有非 trusted 工具上执行。

---

### Chain 3：DeepSeek 协议正确性

```
messages (from caller)
  → deepcopy (before any mutation)                 ✅ runtime.py:204,538
  → embed files (on copy only)                     ✅ runtime.py:203-209
  → connect MCP                                    ✅
  → build tools schema (strict compiler)           ✅
  → _validate_protocol()                           ✅ runtime.py:287,570,770
    → validate_deepseek_messages()                 ✅ protocol.py
      → reasoning_content required for tool_calls  ✅
      → tool messages must follow assistant        ✅
      → tool_call_id ordering check                ✅
  → resolve thinking config                        ✅
  → build chat kwargs (remove sampling params)     ✅
  → API call                                       ✅
  → normalize usage                                ✅ runtime.py:345
  → accumulate NormalizedUsage                     ✅
  → handle reasoning (trace only, not injected)    ✅
```

**结论**: ✅ 协议正确性链路完整。reasoning_content 完整保留，streaming include_usage 已设置，NormalizedUsage 统一累积。

---

### Chain 4：安全模块集成度

| 模块 | 位置 | 接线到主路径？ | 调用位置 |
|------|------|:--:|------|
| `safe_join` | `security/__init__.py` | ✅ | `tools/builtins/filesystem.py:24,101`, `policy.py` |
| `validate_file_access` | `security/__init__.py` | ✅ | `tools/builtins/filesystem.py:30` |
| `validate_url` | `security/__init__.py` | ✅ | `agent/builtins.py`, `search.py`, `policy.py` |
| `validate_url_strict` | `security/http.py` | ✅ | `policy.py` (network check), `tools/builtins/network.py` |
| `fetch_url_hardened` | `security/http.py` | ✅ | `tools/builtins/network.py:35` |
| `redact_secrets` | `security/__init__.py` | ✅ | `tools/executor.py:276` (executor output), `telemetry.py` (traces) |
| `wrap_untrusted` | `security/__init__.py` | ✅ | `tools/executor.py:280` |
| `PolicyEngine` | `policy.py` | ✅ | `executor.py:150`, `runtime.py:78` (default) |
| `ApprovalHandler` | `execution/approval.py` | ✅ | `executor.py:165` |
| `DeepSeekStrictSchemaCompiler` | `deepseek/strict_schema.py` | ✅ | `tools/registry.py:69` |
| `NormalizedUsage` | `usage.py` | ✅ | `runtime.py:254,345` |
| `extract_cache_metrics` | `deepseek/cache_metrics.py` | ✅ | `agent.py:671` |
| `ConversationState` | `deepseek/protocol.py` | ⚠️ | 类型存在，runtime 用 `validate_deepseek_messages` |

---

### Chain 5：Orphaned 模块（存在但未接线）

| 模块 | 功能 | 为什么不接线 |
|------|------|------------|
| `CacheCompiler` | prefix 分析 | runtime 仍用 `_trim_messages()` destructive trim，非 cache-first |
| `ThinkingRouter` | 动态 thinking 决策 | 当前 `_resolve_thinking` 已够用 |
| `TrustedSearchPipeline` | 搜索管线 | agent 的 web_search 工具直接调 `get_search_provider` |

**影响评估**: 这些模块不接线**不影响核心安全链路**。CacheCompiler 的性能优化可在后续版本接入。

---

## 2. 动态分析

### 2.1 全量回归

```
792 passed / 47 failed / 3 skipped
```

47 个失败全部为已有（用户 v0.3.0 重构引入）：
- 文件工具测试需要 `workspace_root`（9 项）
- crew/checkpoint/structured 测试（8 项）
- runtime 测试（6 项）
- thinking 参数测试（6 项）
- 其他（18 项）

本次修改引入的**新增回归 = 0**。

### 2.2 安全关键测试覆盖

| 测试文件 | 测试数 | 通过 | 覆盖 |
|---------|--------|:--:|------|
| `test_security.py` | 40 | ✅ | path sandbox, URL validation, redaction, untrusted |
| `test_policy.py` | 9 | ✅ | policy deny, capability, approval |
| `test_retry.py` | 33 | ✅ | CB, retry bounds |
| `test_runtime_immutability.py` | 2 | ✅ | message immutability |
| `test_deepseek_thinking_protocol.py` | 9 | ✅ | reasoning preservation |
| `test_policy_enforced_executor.py` | 4 | ✅ | no-policy deny, sandbox gate |
| `test_hardened_http.py` | 6 | ✅ | SSRF domain matching, URL validation |
| `test_cache_stability.py` | 2 | ✅ | system message preservation |
| `test_fim.py` | 12 | ✅ | max_tokens guard |
| `security/test_policy_enforced_executor.py` | 4 | ✅ | batch policy enforcement |
| `deepseek/test_strict_schema.py` | 22 | ✅ | strict schema compilation |

**总计 143 个安全关键测试全部通过。**

---

## 3. 系统协同运作评估

### 3.1 已验证的协同场景

| 场景 | 链路 | 验证 |
|------|------|:--:|
| 用户调用 `agent.run("read a file")` | Agent → Runtime → PolicyEngine → Executor → safe_join → execute → untrusted wrap → audit | ✅ |
| 用户调用 `agent.stream("fetch url")` | Agent → Runtime(stream) → PolicyEngine → Executor → validate_url → fetch → redact → model | ✅ |
| 用户调用 `agent.allow_network(domains={...})` | Agent profile → allow_network → register make_fetch_url → invalidate_runtime | ✅ |
| API 返回 malformed JSON tool args | Client → preserve raw_args → Executor → repair → confidence gate → execute or deny | ✅ |
| 429 rate limit | Client → RetryExecutor → attempt++ → deadline check → max_delay cap → raise on exhaustion | ✅ |
| Circuit breaker trip | Multiple 503 → record_failure → OPEN → cooldown → HALF_OPEN → success → CLOSED | ✅ |
| 401 auth error | Client → non-retryable → raise (NOT counted against CB) | ✅ |

### 3.2 未覆盖的边缘场景

| 场景 | 状态 | 风险 |
|------|:--:|------|
| Tool timeout（线程不杀死） | ⚠️ | 低 — SECURITY.md 已记录 |
| DNS rebinding TOCTOU | ⚠️ | 低 — post-fetch URL re-validate 缓解 |
| Container sandbox kill on timeout | ⚠️ | 低 — ProcessSandbox 有 subprocess.timeout |
| MCP subprocess zombie | ⚠️ | 低 — stderr drain thread + disconnect cleanup |

---

## 4. 成熟度评估

| 维度 | 评分 | 依据 |
|------|:--:|------|
| **安全执行链完整性** | 8/10 | Policy + approval + sandbox + audit 全线贯通 |
| **DeepSeek 协议正确性** | 8/10 | reasoning 保留、stream usage、strict schema |
| **安全模块接线率** | 8.5/10 | 14/16 安全模块已接入主路径 |
| **测试覆盖（安全）** | 7/10 | 143 安全关键测试，缺 jsonschema validation 和 stress test |
| **代码质量** | 7/10 | mypy strict 部分模块，CI 已有 |
| **生产可用性** | **6.5/10** | 适用于**半生产级（Level 1-2）** |

### 当前定位

```
Level 0: 本地可信脚本        ✅ 完全满足
Level 1: 内部可信用户         ✅ 完全满足
Level 2: 非完全可信 prompt   ✅ 基本满足（policy + sandbox + approval）
Level 3: 非可信工具/MCP      ⚠️ 需 ContainerSandbox kill + DNS rebinding 强化
Level 4: 多租户 SaaS         ❌ 未实现（不在当前范围）
```

**SeekFlow 当前可安全用于 Level 1-2 场景**：PolicyEngine 为强制网关，Sandbox 可选，Approval 可用，Audit 记录完整，Usage/Cost 统一。

---

## 5. 待修复项（非阻塞）

| 优先级 | 项 | 影响 |
|:--:|------|------|
| P1 | `_trim_messages()` 改用 `append_only_compress()` | cache 命中率 |
| P2 | 增加 jsonschema 参数校验 | 防御 hallucinated args |
| P2 | ContainerSandbox docker kill on timeout | 容器超时强杀 |
| P2 | 接线 `TrustedSearchPipeline` 到 agent | 搜索溯源 |
| P3 | 移除 mypy ignore_errors（agent/mcp/compat） | 类型安全 |
