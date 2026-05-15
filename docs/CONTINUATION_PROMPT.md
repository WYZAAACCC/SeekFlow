# SeekFlow 新对话继续实施 Prompt

将此文件内容完整复制给新对话中的 Claude Code。

---

## 项目上下文

你正在处理 `WYZAAACCC/SeekFlow` 项目。这是一个 DeepSeek-native Agent Runtime，经过多轮安全审计和重构，当前处于"受控内部试用级"，目标是从当前的 v0.3.5 推进到**完全半生产级（安全等级 Level 2）**。

**代码基线**：commit `dcde2f0`，版本 v0.3.5
**测试基线**：`791 passed / 49 failed / 2 skipped`（失败均为已有用户修改引入）
**GitHub**：https://github.com/WYZAAACCC/SeekFlow

README 当前处于 `security-hardening beta` 状态。项目核心安全模块（PolicyEngine、Sandbox、StrictSchemaCompiler、NormalizedUsage、Telemetry、Audit、ApprovalHandler）均已存在并部分接入主链路，但**执行路径上仍有安全缺口**。

---

## 剩余任务：实现 improve11.md 的 Block 1 (ToolRunner) + Block 5 (测试归零)

当前已完成的 improve11 项：
- ✅ PR1：PolicyEngine fail-closed（dict context 不再绕过 capability gate，network empty domains = deny）
- ✅ PR2：JSON Schema validation（`tools/validation.py`，jsonschema Draft202012Validator，接入 executor）
- ⬜ PR0：49 个失败测试标记 xfail 或修复
- ⬜ PR3：ToolRunner / ExecutionPlanner（最大阻塞——当前 executor 直接执行工具函数）

### 最重要的工作：PR3 —— ToolRunner 强制执行

当前 `src/seekflow/tools/executor.py` 在 `execute()` 方法中**仍然直接调用 `tool_def.func(**arguments)`** 和 `ThreadPoolExecutor`。这意味着：
- 工具在宿主 Python 进程中运行——无隔离
- timeout 无法硬杀死循环/阻塞的工具
- write/network/code_exec/destructive 工具只要不主动使用 Sandbox，就不受任何沙箱约束

**必须实现**：

1. **新增 `src/seekflow/tools/runners.py`**：
   - `InProcessRunner`：仅用于 `trusted=True` + `risk="read"` + `parallel_safe=True` 的工具，不提供硬超时
   - `ProcessRunner`：使用 `multiprocessing.get_context("spawn")` 创建子进程，timeout 后 `terminate()` → 0.5s grace → `kill()`，返回 `ToolRunResult(killed=True)` 标识

2. **新增 `src/seekflow/tools/planner.py`**：
   - `ExecutionPlan` dataclass: runner, timeout_s, requires_hard_timeout, allow_parallel, cache_allowed, reason
   - `plan_execution(tool_def, context, timeout)` 函数——根据 risk/capabilities/trusted 选择 runner:
     ```
     code_exec/destructive → container (暂用 ProcessRunner fallback)
     network/write/filesystem.write → process
     trusted + read + parallel_safe → in_process
     其他 → process (default untrusted isolation)
     ```

3. **修改 `src/seekflow/tools/executor.py`**：
   - **删除** `tool_def.func(**arguments)` 和 `ThreadPoolExecutor` 直接调用
   - **替换为** `plan = plan_execution(...)` → `runner = self._runner_for(plan)` → `run_result = runner.run(tool_def.func, arguments, plan.timeout_s)`
   - executor 中**不允许**任何绕过 runner 的直接函数调用（`InProcessRunner.run()` 内部除外）

4. **修改 `src/seekflow/types.py`**：
   - `ToolPolicy` 新增字段：
     ```python
     RunnerKind = Literal["auto", "in_process", "process", "container"]
     runner: RunnerKind = "auto"
     trusted: bool = False
     ```

5. **新增测试**（`tests/tools/test_runner_timeout.py` + `tests/tools/test_runner_selection.py` + `tests/tools/test_executor_no_direct_bypass.py`）：
   - infinite loop 工具被 hard kill
   - sleep 工具 timeout 返回
   - trusted read 可使用 in_process
   - network/write 使用 process runner
   - runner name 记录到 audit
   - 直接调用 `tool_def.func` 的代码路径不存在（grep 验证）

**设计约束**：
- Windows/macOS `spawn` 下工具函数必须是 pickleable
- 不可 pickle 的 closure 工具在 untrusted 路径下应报错或降级为 trusted-in-process-only
- 不要破坏现有 trusted read 工具的行为
- executor 现有的 chain（parse → repair → lookup → coerce → schema → policy → approval）不变，只是在 execute 环节替换执行方式

### 次要工作：PR0 —— 清理失败测试

当前 49 个失败测试来源（非你造成）：
- 文件工具测试：v0.3.0 用户新增 `_workspace_root_or_error` 要求（9 项）
- crew/checkpoint/structured 测试（8 项）
- thinking 参数测试：旧 `budget_tokens` 断言与新 API 不一致（6 项）
- runtime/stress 测试（部分需真实 API key）
- 其他

**不要修复这些测试**（它们是用户的业务变更造成的，你不了解意图）。应当在测试文件头部用 `pytest.importorskip` 或标记 `@pytest.mark.xfail(reason="pre-existing: issue #...")` 处理。目标：`pytest` 不输出裸露的 FAILED。

---

## 关键架构决策（请遵守）

1. **不重写已有好模块**：`NormalizedUsage`、`DeepSeekStrictSchemaCompiler`、`json_output.py`、`CacheCompiler`、`CacheStabilizer`、`telemetry.py`、`ToolAuditRecord`、`validate_url_strict`、`fetch_url_hardened` 都已完成，不要动它们
2. **接线优先于重写**：把已有模块接到主执行路径上，不要创建新模块包裹已有模块
3. **安全默认拒绝**：无 policy = deny，无 workspace = deny，无 domains = deny，无 sandbox = deny
4. **每个 PR 必须有测试**：不写测试的改动 = 不完整

## 主要执行链路（已知正确，请勿破坏）

```
Agent.run()
  → _make_runtime() (agent.py:746-769)
    → PolicyEngine() + ToolExecutionContext()
    → ToolRuntime(policy_engine=..., policy_context=...)
      → chat() / chat_stream() / chat_batch()
        → working_messages = copy.deepcopy(messages)  # FIRST, before any mutation
        → embed files on copy only
        → _validate_protocol()
        → ToolExecutor(policy_engine=..., context=..., approval_handler=..., sandbox=...)
          → execute():
            parse → repair → lookup → coerce → schema_validate → policy authorize
            → approval → cache lookup → **RUNNER EXECUTE** → redact → untrusted wrap
            → truncate → audit
```

Stream/Batch/Async 路径均传递 policy_engine + context（runtime.py:230,552,858; async_runtime.py:187）。

---

## 关键文件清单

| 文件 | 作用 | 需修改？ |
|------|------|:--:|
| `src/seekflow/tools/executor.py` | 工具执行器（需删除直接调用） | ✅ 核心修改 |
| `src/seekflow/types.py` | ToolPolicy 添加 runner/trusted | ✅ 小幅修改 |
| `src/seekflow/tools/runners.py` | 新的 InProcessRunner + ProcessRunner | 🆕 新建 |
| `src/seekflow/tools/planner.py` | ExecutionPlan + plan_execution() | 🆕 新建 |
| `src/seekflow/tools/validation.py` | JSON Schema 校验（已完成） | ✅ 已有 |
| `src/seekflow/sandbox.py` | ContainerSandbox（已有，用于 ContainerRunner 桥接） | - |
| `src/seekflow/policy.py` | PolicyEngine fail-closed（已完成） | - |
| `src/seekflow/usage.py` | NormalizedUsage（已完成） | - |
| `src/seekflow/security/` | safe_join/validate_url/redact/http（均完成） | - |
| `src/seekflow/deepseek/` | strict_schema/json_output/models/protocol（均完成） | - |
| `tests/tools/test_runner_timeout.py` | Timeout/kill 测试 | 🆕 新建 |
| `tests/tools/test_runner_selection.py` | Runner 选择逻辑测试 | 🆕 新建 |
| `tests/tools/test_executor_no_direct_bypass.py` | 验证无直接调用 | 🆕 新建 |

---

## 验收标准

完成所有工作后，必须满足：

```text
1.  grep executor.py 不得出现 tool_def.func(**arguments)（InProcessRunner 内部除外）
2.  network/write/code/destructive 工具不走 in_process
3.  infinite loop 工具在 timeout 内被 kill，不拖死 pytest
4.  timeout 结果 killed=True，audit 记录 runner name
5.  pytest 无裸露 FAILED
6.  现有 791 个通过的测试不受影响
```

---

## 参考资料

- `docs/improve11.md` — 完整的半生产级修复方案（8 个 PR，本对话完成了 PR1+PR2）
- `docs/IMPLEMENTATION_REPORT.md` — 所有修改与 improve10 对照表
- `docs/CHAIN_ANALYSIS_REPORT.md` — 5 条执行链路逐段审计
- `src/seekflow/sandbox.py` — 已有 ContainerSandbox/ProcessSandbox（可桥接）
