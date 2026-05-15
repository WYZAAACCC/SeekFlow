# Improve13.md 审核差异报告：搁置项分析

## 审核结论：全部 10 个 PR 均为真实问题，修复方案正确

经过逐项对照代码审核，improve13.md 提出的 10 个 PR 中：

- **0 个不需要修复**：所有问题都真实存在于当前 v0.3.6 代码中
- **10 个 PR 的修复方案均正确**：无需替代方案
- **1 个 PR（PR-9）有实施限制**：核心 xfail 清零依赖上游用户决策，无法在当前会话完全解决

---

## 逐项代码验证记录

### PR-1：Runner override 可弱化隔离等级
- **代码位置**：[planner.py:49-58](src/seekflow/tools/planner.py#L49-L58)
- **验证**：`if policy is not None and policy.runner != "auto"` 直接返回用户指定的 runner，不检查风险等级
- **结论**：✅ 需修复，方案正确

### PR-2：ContainerRunner 在宿主进程调用 tool function
- **代码位置**：[container_runner.py:46](src/seekflow/tools/container_runner.py#L46)
- **验证**：`request = func(**arguments)` 在 `ContainerRunner.run()` 中执行，sandbox 只保护返回的 code
- **结论**：✅ 需修复，方案正确

### PR-3：ProcessRunner 非字符串结果未 bounded
- **代码位置**：[runners.py:28-37](src/seekflow/tools/runners.py#L28-L37)（`_run_in_subprocess`）
- **验证**：`if isinstance(result, str)` — 只对字符串做 bounded，dict/list 原样通过 Queue
- **结论**：✅ 需修复，方案 B 推荐

### PR-4：Cache write 不限工具类型
- **代码位置**：[executor.py:443-445](src/seekflow/tools/executor.py#L443-L445)
- **验证**：cache write 仅检查 `metadata.get("cache", True)`，不检查 risk level。cache lookup 已限制 read 但 write 未限制
- **结论**：✅ 需修复，方案正确

### PR-5：metadata.trusted 控制 output wrapping
- **代码位置**：[executor.py:415](src/seekflow/tools/executor.py#L415)
- **验证**：`trusted = (tool_def.metadata or {}).get("trusted", False)` 直接控制是否跳过 untrusted wrapping
- **结论**：✅ 需修复，方案正确

### PR-6：无 policy 工具可绕过执行
- **代码位置**：[executor.py:158](src/seekflow/tools/executor.py#L158)（`if self.policy_engine is not None`）
- **验证**：当 `policy_engine=None` 时，policy gate 完全跳过，无 policy 工具直接执行
- **结论**：✅ 需修复，方案正确

### PR-7：authorize_with_context 不验证 args
- **代码位置**：[policy.py:57-81](src/seekflow/policy.py#L57-L81)
- **验证**：只检查 risk/approval/capabilities，无 path/url/args 校验
- **结论**：✅ 需修复，方案正确

### PR-8：ContainerSandbox timeout 无显式 docker kill/rm
- **代码位置**：[sandbox.py:149](src/seekflow/sandbox.py#L149)（`subprocess.run` with `--rm`）
- **验证**：依赖 `subprocess.run(timeout=...)` 和 `docker run --rm`。若 Python 进程被 timeout 杀死，`--rm` 可能不触发
- **结论**：✅ 需修复，方案正确

### PR-9：核心 xfail 收敛
- **状态**：14 个核心路径 xfail 带 strict=True + issue 编号
- **限制**：这些失败来自 v0.3.0–v0.3.5 用户业务变更，不了解意图无法正确修复
- **当前可做**：添加 `--strict-core` flag 到 check 脚本；写清楚 release 前置条件

### PR-10：文档与 release checklist
- **结论**：✅ 需执行，方案正确

---

## 实施建议

所有 10 个 PR 都应实施。PR-9 的"核心 xfail 清零"需要分步：
1. 本会话可实现：`--strict-core` flag + release checklist
2. 需要上游决策：实际修复 14 个核心 xfail 测试
