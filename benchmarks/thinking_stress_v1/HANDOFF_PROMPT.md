# SeekFlow Thinking Stress Benchmark v1 — 交接 Prompt

将此文件完整内容复制给新对话。

---

## 项目上下文

你正在 `WYZAAACCC/SeekFlow` 项目（v0.3.7）中。仓库地址：https://github.com/WYZAAACCC/SeekFlow

**当前状态**：v3.0 fair comparison benchmark 已完成（6 场景 × 4 框架，机械+推理），但暴露了一个核心问题：**v4-pro 裸推理已足够强，thinking 模式在写报告类任务中没有质量增益。**

关键证据（已记录在 [README.md](https://github.com/WYZAAACCC/SeekFlow#readme)）：
- 三个极端推理场景（三难困境/因果追踪/谈判僵局）：全部框架 8.8-8.9，零差距
- Stable 的 thinking 只增加了延迟（267s vs 100-122s），没有提高质量
- README 已如实记录："v4-pro 裸推理已足够强，thinking 模式未带来质量增益，仅增加延迟"

**因此需要一个新的 benchmark**，从"写报告"转向"代码修复闭环"来真正证明 thinking 的价值。

---

## 新 Benchmark 方案

完整设计文档：[docs/new_benchmark.md](https://github.com/WYZAAACCC/SeekFlow/blob/main/docs/new_benchmark.md)

### 核心思路

```
旧范式：给信息 → 调工具 → 写报告 → LLM judge 评分（thinking 没有优势）
新范式：给坏仓库 → 读代码 → 跑测试 → 定位根因 → 修改代码 → 回归验证 → 隐藏测试验收
```

### 目录结构

```
benchmarks/thinking_stress_v1/
├── __init__.py
├── README.md
├── scenario.py          # 任务 prompt
├── tools.py             # 受控工具（禁止任意 shell）
├── runner.py            # 主编排器
├── agents.py            # 框架接入层
├── scorer.py            # 程序化评分（100分制）
├── report.py            # 结果报告生成
├── contracts.py         # 类型定义
├── output/
├── fixture_repo/        # 故意写坏的 Python Agent Runtime
│   ├── pyproject.toml
│   ├── src/mini_agent_runtime/  (7个模块，各含bug)
│   └── tests/                   (公开测试)
└── hidden_tests/        # agent 不可见，scorer 最终验收
```

### 对比组设计（关键）

| 组 | thinking | mode | max_steps | 目的 |
|---|:--:|------|:--:|------|
| stable-thinking | **True** | stable | 30 | **实验组** |
| stable-no-thinking | **False** | stable | 30 | 隔离 thinking 变量 |
| fast-no-thinking | False | fast | 16 | 轻量对照组 |

**为什么必须加 stable-no-thinking**：如果不加，无法区分优势来自 thinking 还是来自 stable mode 的工程能力（cache/policy/JSON repair 等）。

### 7 个 Bug 类别

| 模块 | Bug | 为什么考验 thinking |
|------|-----|-------------------|
| messages.py | 丢失 reasoning_content | 不开thinking不会触发此路径 |
| tool_runtime.py | 并行结果顺序错乱 | 简单修复是串行化（破坏性能），正确修复是保序并行 |
| security.py | path traversal + SSRF多向量绕过 | 6种绕过向量需要系统性思考 |
| redaction.py | 只redact sk- 漏4类凭据 | 需要识别模式而非硬编码 |
| cache_cost.py | cache前缀含timestamp + 计费错误 | 涉及缓存稳定性+成本精度两个维度 |
| policy.py | 缺失策略默认放行 | 安全逻辑翻转，deny-by-default |
| json_repair.py | dangerous tool允许低置信修复 | 安全权衡判断 |

### 评分体系（100分）

```
公开测试通过率：25分  (agent可见)
隐藏测试通过率：30分  (agent不可见，防硬编码)
静态安全扫描：  10分
工具流程合规：  15分
Patch质量：    10分
最终报告质量：  10分
```

**关键验收标准**：stable-thinking vs stable-no-thinking 的隐藏测试通过率差距 ≥ 15%。

---

## 🔴 方案中发现的问题（需要在新对话中修正）

### 问题1：`tools.py` 中 `read_file` 返回类型不一致

```python
# 当前草案（有问题的）：
def read_file(path, max_chars=12000) -> str:
    ...
    if "hidden_tests" in p.parts:
        result = {"status": "error", ...}
        return json.dumps(result)  # 返回 JSON 字符串
    ...
    return content  # 返回纯文本字符串
```

**修正**：统一返回 dict，和 `list_files`/`search_code`/`run_tests` 保持一致。Agent 处理多种返回类型容易出错。建议所有工具统一返回 `dict`，错误状态用 `status` 字段区分。

### 问题2：`apply_patch` 的 finally 块中 `result` 可能未绑定

```python
def apply_patch(path, old, new):
    try:
        ...
        if old not in text:
            result = {...}  # early return 前赋值
            return result
        ...
    finally:
        _audit("apply_patch", ..., locals().get("result", {"status": "unknown"}))
```

当 `old not in text` 时 `result` 已赋值，没问题。但如果 `write_text` 抛出异常，`result` 未赋值。需在 try 块开头初始化 `result = None`。

### 问题3：`_safe_path` 的 `relative_to` 返回值被丢弃但用作校验

```python
p.relative_to(ws)  # 如果 p 不在 ws 下会抛 ValueError，返回值未使用
```

这实际上能工作（ValueError 即为拒绝），但写法不清晰。建议显式包 try/except 或改用 `p.is_relative_to(ws)`（Python 3.9+）。

### 问题4：Fixture repo 的公开测试初始必须全部或大部分失败

文档中提到"至少 8 个测试失败"。Phase 2 完成后必须手动验证：
```bash
cd benchmarks/thinking_stress_v1/fixture_repo && python -m pytest -q
```
确保有足够多的失败测试，否则 agent 无需修复就能通过。

### 问题5（经验教训）：SeekFlow 的 tool event logging 需要跨进程支持

在 fair_comparison_v2 中，我们花了大量时间解决 tool event logging 被 SeekFlow multiprocessing 绕过的问题。最终方案是基于文件的 `_logged_call` 内联日志。新 benchmark 中的 `tools.py` 直接使用 Python 函数调用，不存在此问题——因为工具函数在 `agents.py` 中直接传给 SeekFlow Agent，不涉及子进程。

但如果未来要支持 subprocess 执行工具，需要复用 `_SEEKFLOW_BENCH_EVENTS_FILE` 环境变量机制。

---

## 实施顺序（按 Phase 执行）

```
Phase 1: 搭建骨架（目录 + scenario.py + contracts.py + README.md）
Phase 2: 实现 fixture_repo（7个坏模块 + 公开测试，验证测试失败）
Phase 3: 实现 tools.py（10个工具 + audit log + workspace隔离）
Phase 4: 实现 scorer.py（public/hidden tests + static scan + 6维度评分）
Phase 5: 实现 agents.py + runner.py（3组SeekFlow + 随机化 + JSON输出）
Phase 6: 实现 report.py（Markdown报告生成）
Phase 7: （可选）接入 LangChain/CrewAI
```

**Phase 2 验证命令**：
```bash
cd benchmarks/thinking_stress_v1/fixture_repo && python -m pytest -q -v
# 预期：至少 8 个测试失败
```

**Phase 5 smoke test**：
```bash
python -m benchmarks.thinking_stress_v1.runner --rounds 1 --frameworks seekflow_fast_no_thinking
```

---

## 当前 v3.0 Benchmark 参考

新对话可能需要参考现有代码：

| 文件 | 说明 |
|------|------|
| [benchmarks/fair_comparison_v2/shared_tools.py](https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/shared_tools.py) | 工具函数、fixture search、_logged_call 内联日志 |
| [benchmarks/fair_comparison_v2/seekflow_agents.py](https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/seekflow_agents.py) | Fast/Stable 的 DeepSeekAgent 构造方式 |
| [benchmarks/fair_comparison_v2/compliance.py](https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/compliance.py) | 程序化合规评委（可参考评分逻辑） |
| [benchmarks/fair_comparison_v2/runner.py](https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/runner.py) | 随机化执行、原子写入、AGENT_TIMEOUT |
| [benchmarks/fair_comparison_v2/judge.py](https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/judge.py) | LLM 评委（新 benchmark 主要靠程序化评分，LLM judge 仅用于 F 维度） |

### 已踩过的坑（不重复犯）

1. **不要改 `src/seekflow/` 框架源码**——所有修改限于 `benchmarks/thinking_stress_v1/`
2. **不要用 functools.wraps 包装工具函数**——SeekFlow 通过 `inspect.unwrap()` 绕过
3. **工具函数签名必须保持原样**——SeekFlow 依赖类型注解生成 JSON Schema
4. **`python` 不是 `python3`**——本机用 Anaconda 的 `python`
5. **GitHub push 有时需要重试**——国内网络不稳定

---

## 你的任务

1. 阅读 [docs/new_benchmark.md](https://github.com/WYZAAACCC/SeekFlow/blob/main/docs/new_benchmark.md) 完整方案
2. 按 Phase 1-6 顺序实施（Phase 7 可跳过）
3. 修正上方列出的 5 个问题
4. 每个 Phase 完成后验证
5. 最终运行完整 3 轮测试并输出 Markdown 报告
