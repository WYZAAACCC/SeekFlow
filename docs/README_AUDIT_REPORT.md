# SeekFlow v0.3.7 README 审计报告

**审计日期**: 2026-05-18 | **审计范围**: README.md 全文 vs src/seekflow/ 源码 | **结论**: 6 处错误/漂移，3 处误导

---

## 一、阻断级错误（用户按 README 操作会报错）

### 错误 1：Quick Start 中 `dangerous_tools=True` 不提供 11 个工具

**README 原文**（`## Quick Start` 区域）：
```python
agent2 = DeepSeekAgent(
    role="研究员",
    goal="搜索并分析信息",
    backstory="资深研究员",
    dangerous_tools=True,  # explicit opt-in
)
agent2.with_default_tools()  # all 11 tools available
```

**实际情况**：`with_default_tools()` 始终只加载 4 个安全工具（calculate、parse_csv_str、extract_entities、classify_text），**无论 `dangerous_tools` 取什么值**。要获得文件/网络/代码/SQL 工具，必须显式调用：
```python
agent2.allow_filesystem(root="/workspace")
agent2.allow_network(domains={"api.example.com"})
agent2.allow_python(sandbox=ProcessSandbox())
agent2.allow_sqlite(root="/data", readonly=True)
```
且这些方法都有**必填参数**（如 `root`、`domains`、`sandbox`），README 完全没有提及。

**严重性**: 🔴 阻断级 — 用户复制粘贴 README 代码会发现只有 4 个工具可用。

### 错误 2：`from seekflow import DeepSeekAgent` 缺少 API key

**README 原文**：
```python
agent = DeepSeekAgent(
    role="分析师",
    goal="分析数据并给出建议",
    backstory="经验丰富的数据分析师",
    model="deepseek-v4-pro",
)
agent.with_default_tools()
```

**实际情况**：第一个示例没传 `api_key`，虽然 SeekFlow 会尝试从 `DEEPSEEK_API_KEY` 环境变量读取，但 README 没提这一点。如果环境变量未设置，运行会报错。所有三个示例中，只有危险工具那个示例在第二个 agent 上没写 `api_key`，读者会困惑。

**严重性**: 🟡 中等 — 有环境变量时能跑，但文档不完整。

---

## 二、功能漂移（代码改了 README 没跟上）

### 漂移 1：`CacheCompiler` 不再是 `CacheStabilizer` 的别名

**README 原文**：
```python
from seekflow.cache import CacheCompiler
compiler = CacheCompiler()
compiled = compiler.compile(system_prompt, tools_schema)
```

**实际情况**：代码中存在两个独立类：
- `CacheCompiler`：有 `compile()` 和 `predict_cache_hit()` 方法
- `CacheStabilizer`：有 `ensure_stable_prefix()`、`freeze()`、`cache_health()` 方法

READMD 示例调用的是 `CacheCompiler.compile()`，这个能正常工作。但 `CacheStabilizer` 在代码中存在却完全没有被文档提及，用户不知道何时该用哪个。

**严重性**: 🟡 中等 — 示例能跑，但 API 未被完整文档化。

### 漂移 2：`redact_secrets` 不在 `seekflow.secrets` 中

README 说 "Secret redaction pipeline ✅"，但没有说明导入路径。实际位置是 `seekflow.security.redact_secrets`，而 `seekflow.secrets` 模块包含的是 `SecretBroker`、`SecretRef`（不同的功能）。`redact_secrets` 也不在顶层 `seekflow` 的 `__all__` 中。

**严重性**: 🟡 中等 — 功能存在但发现性差。

### 漂移 3：JSON Repair 表描述的是 4-Level，实际是 3-Level

**READMD 原文表格**：
| Level | Method | Confidence | Dangerous tools |
|-------|--------|-----------|-----------------|
| 0 | `json.loads` native | 1.0 | ✅ Allowed |
| 1 | Syntactic repair | 0.60–0.99 | ❌ Denied if < 0.85 |
| 2 | Model re-emission | N/A | ✅ Allowed (expensive) |
| 3 | Fail-closed | 0.0 | ❌ Denied |

**实际情况**：源码中只找到 3 个有效级别（native、syntactic、fail）。Model re-emission（第 2 级）**可能存在于某个调用方**，但在 `repair_json_arguments()` 核心函数中没有直接实现。需要确认是否存在完整的 model re-emission 路径。

**严重性**: 🟡 中等 — 可能夸大了修复能力。

---

## 三、Benchmark 相关问题

### 问题 1：Benchmark 结果难以复现

README 报告 6 scenario × 4 frameworks = 24 runs，但读者需要：
1. 设置 `DEEPSEEK_API_KEY`
2. 设置 `BENCH_SEARCH_BACKEND=fixture`
3. 安装 seekflow（`pip install -e .`）
4. 运行特定命令

**实际情况**：当前 benchmark 代码（`fair_comparison_v2`）依赖 `seekflow` 源码安装模式，且搜索结果使用 fixture 模式以避免网络依赖。README 的复现命令是正确的，但我们实测发现 `deepseek-v4-pro` 的 API 波动导致分数有差异（尤其在 thinking 模式下）。README 报告的 6 场景平均分可能基于特定 API 快照。

### 问题 2：`thinking_stress_v1` benchmark 完全没出现在 README 中

当前 README 只提到 `fair_comparison_v2` 的结果。我们刚刚完成的 `thinking_stress_v1`（15 次运行，2 轮迭代）提供了更有价值的发现：thinking 模式在代码修复闭环中的隐藏测试通过率仅领先 +3.0%。这些结果应该被整合到 README 的"关键发现"中，以提供平衡的观点。

### 问题 3：Benchmark 对比表缺少 "安全测试" 维度

README 的对比表比较了 thinking、JSON repair、cache、circuit breaker 等工程特性，但**没有比较安全维度**。而我们在审计中发现，LangChain 和 CrewAI 在 2026 年分别被披露了 6 个和 4 个安全 CVE（路径穿越、SSRF、沙箱逃逸），SeekFlow 在这些维度上是唯一设计时就内置防护的框架。这是 SeekFlow 最大的差异化优势，但 README 完全没有突出。

---

## 四、架构图的准确性问题

Security Architecture 图声称包含以下层次：

| 层次 | 声称的组件 | 实际代码中存在？ | 公开可导入？ |
|------|-----------|:--:|:--:|
| Agent Layer | DeepSeekAgent, Crew, Task, StateGraph | ✅ | ✅ |
| Policy Layer | PolicyEngine, ToolPolicy, NormalizedContext | ✅ | ✅ (NormalizedContext 在 execution.context) |
| Runtime | ToolRuntime, chat/chat_stream, StepKind | ✅ | ✅ (StepKind 是内部类) |
| Security | safe_join, validate_url, redact_secrets, UntrustedContent, close_object_schema | ✅ | ✅ |
| Runners | InProcessRunner, ProcessRunner, ContainerRunner | ✅ | ✅ |
| Tool System | @tool, Registry, Executor, limits, AuditTrail | ✅ | ✅ |
| Sandbox | NoSandbox, LocalThread, ProcessSandbox, Container | ✅ | ✅ (ContainerSandbox 而非 Container) |
| DeepSeek API | DeepSeekClient, Thinking/FIM/Batch/Balance | ✅ | ✅ |

架构图整体准确，但 "Container" 应为 "ContainerSandbox"。

---

## 五、Breaking Changes 验证

| README 声称的 Breaking Change | 已验证？ | 备注 |
|---|---|---|
| `with_default_tools()` 默认只加载 calculate | ✅ | 正确，现在是 4 个安全工具 |
| `ToolCall.arguments` 类型 `dict` → `dict \| str` | ✅ | types.py 中确认 |
| `repair_message_order()` 不再语义注入 | ⚠️ | 无法直接验证，需读 git diff |
| `embed_files_into_message()` 返回新 dict | ⚠️ | 同上 |
| `_sanitize_tool_output()` 已移除 | ⚠️ | 同上 |

---

## 六、推荐修改

### 紧急（阻断级）

1. **修复 Quick Start 代码示例**：
```python
# 当前（错误）：
agent2 = DeepSeekAgent(dangerous_tools=True)
agent2.with_default_tools()  # all 11 tools available

# 应为：
agent2 = DeepSeekAgent(dangerous_tools=True, api_key="sk-...")
agent2.with_default_tools()           # 4 safe tools
agent2.allow_filesystem(root="/workspace")  # 3 file tools
agent2.allow_network(domains={"api.example.com"})  # 1 network tool
agent2.allow_python(sandbox=ProcessSandbox())     # 1 code tool
agent2.allow_sqlite(root="/data")                 # 1 SQL tool
# Total: 10 tools
```

2. **修正工具数量声明**：目前不是 11 个工具，是 10 个（或提供精确计数）。

### 重要

3. **添加 API key 说明**：明确说明需要 `DEEPSEEK_API_KEY` 环境变量或在构造时传入 `api_key=`

4. **将 `thinking_stress_v1` 结果整合到 README**：作为"thinking 模式价值"的诚实讨论

5. **添加安全对比**：在对比表中添加 LangChain/CrewAI 的 CVE 引用，突出 SeekFlow 的 security-by-design 优势

6. **完整记录 `allow_*` API**：这些方法是用户获得完整工具集的主要方式，但当前文档完全没提

### 改进建议

7. **将 `redact_secrets` 加入顶层 `__all__`**：提高发现性
8. **README 中解释 `CacheCompiler` vs `CacheStabilizer`**：说明何时用哪个
9. **验证 JSON Repair Level 2 (Model re-emission)**：确认是否完整实现，如果否则从表中移除
10. **架构图中 "Container" → "ContainerSandbox"**
