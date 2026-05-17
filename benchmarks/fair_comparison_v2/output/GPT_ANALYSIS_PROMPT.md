# SeekFlow Stable 模式在 v4-pro 下得分崩塌 — 深度分析请求

**仓库**: https://github.com/WYZAAACCC/SeekFlow  
**分支**: `main`  
**关键目录**: `benchmarks/fair_comparison_v2/`

---

## 一、项目背景

我在进行四个 AI Agent 框架的公平横向对比基准测试：

| 框架 | 模式 | 工具执行 | thinking | 模型 |
|------|------|:--:|:--:|------|
| SeekFlow | fast | 策略拒绝（不执行） | 关 | deepseek-v4-pro |
| SeekFlow | stable | 真正执行工具 | **开** | deepseek-v4-pro |
| LangChain | default | 模型自主选择 | 关 | deepseek-v4-pro |
| CrewAI | default | 黑盒执行 | 未控制 | deepseek-v4-pro |

**公平保证**：同一模型、同一 8 个工具、同一系统提示词、同一任务描述、同一温度(0.0)、同一 DeepSeek API、同一盲审评委。

## 二、涉及的所有文件

### 核心文件（问题所在）

1. **[shared_tools.py](https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/shared_tools.py)** — 共享工具函数 + 系统提示词 + 任务描述
   - `web_search()` (L62-88): 360 搜索(so.com) HTML 抓取实现
   - `_TASK_INSTRUCTIONS` (L208-257): 新建的任务指令前缀（工具铁律+痕迹要求+报告结构）
   - `TASKS` (L264-301): 完整任务描述（`_TASK_INSTRUCTIONS` + 场景任务）
   - `SYSTEM_PROMPTS` (L191-200): 精简的身份描述（仅 2 行）

2. **[seekflow_agents.py](https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/seekflow_agents.py)** — SeekFlow Fast/Stable 实现
   - `run_seekflow_stable()` (L106-159): thinking=True, dangerous_tools=True, max_steps=12

3. **[runner.py](https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/runner.py)** — 主编排器
   - `run_all()` (L39-135): 随机化执行顺序, AGENT_TIMEOUT=300s
   - `AGENT_TIMEOUT` (L30): 当前 300s，Stable 频繁超时

4. **[judge.py](https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/judge.py)** — 盲审评委
   - `judge_output()` (L65+): 6 维度评分，MAX_OUTPUT_CHARS=6000

5. **[langchain_agent.py](https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/langchain_agent.py)** — LangChain 实现（对照组）
   - `run_langchain()` (L40-141): thinking disabled, recursion_limit=15

6. **[crewai_agent.py](https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/crewai_agent.py)** — CrewAI 实现（对照组）
   - `run_crewai()` (L41-129): max_iter=15

### 数据文件

7. **[output/_incremental_results.json](https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/output/_incremental_results.json)** — 原始运行结果（17/24 成功，含 Judge 评语和输出文本）

8. **[output/benchmark_20260517_080013.json](https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/output/benchmark_20260517_080013.json)** — 完整归档数据

---

## 三、v4-pro 测试结果

### 最终排名（严格评委）

| 排名 | 框架 | 模式 | 分数 | 范围 | 延迟 | Token | 成本 | Accuracy |
|:--:|------|------|:--:|------|-----:|------:|------:|:--:|
| 1 | LangChain | default | **7.9** | 7.3-8.3 | 124.9s | 8,359 | Y0.015 | 6.2 |
| 2 | SeekFlow | fast | **7.4** | 6.2-8.5 | 131.4s | 4,935 | Y0.012 | 6.0 |
| 3 | **SeekFlow** | **stable** | **7.0** | **5.7-8.5** | **320.2s** | **19,462** | **Y0.026** | **5.3** |
| — | CrewAI | default | DNF | — | — | — | — | — |

### SeekFlow Stable 逐轮详情

| 轮次 | 场景 | 分数 | C | A | D | S | Ac | P | TC | Token | 延迟 | 截断 |
|:--:|------|:--:|:-:|:-:|:-:|:-:|:-:|:-:|:--:|------:|-----:|:--:|
| R1 | financial | **6.7** | 6 | **5** | 7 | 8 | 7 | 7 | 19 | 13,595 | 327s | ✅ |
| R1 | supply | **5.2** | 4 | **3** | 4 | 7 | 7 | 6 | 20 | 27,726 | 376s | ✅ |
| R2 | financial | **7.3** | 7 | 6 | 7 | 8 | 8 | 8 | 19 | 12,519 | 251s | — |
| R2 | supply | **5.5** | 5 | **4** | 5 | 7 | 6 | 6 | 22 | 33,580 | 334s | ✅ |
| R3 | financial | **8.3** | 9 | **7** | 8 | 9 | 9 | 8 | 19 | 11,731 | 271s | — |
| R3 | supply | **8.2** | 8 | **7** | 8 | 9 | 9 | 8 | 11 | 17,618 | 363s | ✅ |

> C=Completeness, A=Accuracy, D=Depth, S=Structure, Ac=Actionability, P=Professionalism  
> TC=Tool Calls, 截断=输出达到 6000 字符上限

### v4-flash 基线对比

| 框架 | v4-flash | v4-pro | 变化 |
|------|:--:|:--:|:--:|
| LangChain | 6.9 | 7.9 | **+1.0** |
| SeekFlow fast | 6.9 | 7.4 | **+0.5** |
| **SeekFlow stable** | **7.0** | **7.0** | **0.0** ← 唯一零增长的 |

---

## 四、Stable 低分的根因分析（本地已识别）

### 根因 1：360 搜索并发限流 → web_search 大面积失败

**证据链**：
- R2 supply_chain 的 **12 次** web_search 全部返回空结果
- R1 supply_chain 的 **所有** web_search 返回空
- 单独测试 6 并发 HTTP 请求到 `so.com` 触发第 2 个调用 8 秒超时
- 用 `threading.Semaphore(2)` 限制并发后 **18/18 零失败**

**代码位置**: `shared_tools.py:62-88` — `web_search()` 函数无任何并发保护，SeekFlow stable 按提示词要求"并行发起多个独立工具调用"时，6+ 个 HTTP 连接同时冲击 `so.com` 触发反爬限流。

### 根因 2：模型在工具失败时伪造数据

**证据链**：
- R1 supply (A=3): Judge 评"引用未经验证的场景数据作为事实依据，违反工具使用铁律"
- R2 supply (A=4): Judge 评"risk_score 输入参数缺乏来源依据，属于自行编造"
- v4-pro 模型在 web_search 返回空后，**选择编造看似合理的数据而非诚实宣告失败**

**代码位置**：
- `shared_tools.py:71-72` — web_search 失败时返回 `{"results":[],"error":"Search unavailable"}`，缺少对模型的**行为引导**
- `shared_tools.py:208-257` — `_TASK_INSTRUCTIONS` 中"工具返回的数值是你唯一的数据来源"这条铁律让模型**没有安全出口**：承认失败=违反铁律被扣分，编造数据=可能蒙混。模型选择了后者

### 根因 3：Thinking + 长 Prompt = 延迟爆炸

**证据链**：
- v4-flash TASK 长度: ~478 字符 → v4-pro TASK: ~1060/1359 字符 (+200%)
- v4-flash 延迟: 136s → v4-pro 延迟: 320s (+135%)
- 4/6 轮超时（>300s），超时导致输出截断，截断导致 Completeness/Structure 连带扣分
- R3 证明 Prompt 长≠必然差——R3 分数 8.3/8.2 是全场最高，关键区别是 R3 的 web_search **恰好成功了**

**代码位置**:
- `shared_tools.py:208-257` — `_TASK_INSTRUCTIONS` 562/799 字符，包含大量冗余示例和重复规则
- `runner.py:30` — `AGENT_TIMEOUT=300` 对 thinking 模式太紧

### 根因 4：工具调用悖论

**数据**：
- LangChain (TC=0-4): 7.9 分 ← 最少工具调用，最高分
- SeekFlow fast (TC=0): 7.4 分 ← 零工具调用，第二高分  
- SeekFlow stable (TC=11-22): 7.0 分 ← 最多工具调用，最低分

v4-pro 下**调用工具反而成为负担**。R3 证明不是工具本身的问题——R3 supply 只有 11 TC（vs R1/R2 的 20-22），得分 8.2。问题在于：工具不可靠时多调用=多失败=多扣分。

### 根因 5：市值单位持续混淆

**代码位置**: `shared_tools.py:216` — 提示词写"market_cap_billions=85.0 表示 850亿美元"，但模型在 3/6 轮中都搞错了单位。需要在工具调用参数层面给出更精确的示例。

---

## 五、请 GPT 分析以下问题

1. **验证根因**：上述 5 个根因是否准确？有没有遗漏的？

2. **方案评估**：我对每个根因提出了以下修复方向，请评估并改进：
   - 根因1: `web_search` 加 `threading.Semaphore(2)` + 重试 + 超时 5s
   - 根因2: 工具失败返回中加入 `instruction` 字段直接告诉模型写什么；Prompt 中提供"搜索失败声明模板"；弱化"铁律"的绝对措辞
   - 根因3: 精简 `_TASK_INSTRUCTIONS` ~50%；AGENT_TIMEOUT 提高到 600s
   - 根因4: 不需单独修复（根因1+2解决后自动缓解）
   - 根因5: Prompt 中加入具体单位转换示例

3. **公平性审查**：所有修改在 `shared_tools.py` 中，四个框架共享同一份工具和提示词。这种方法是否真正公平？LangChain 的 `extra_body` 参数被传递为 `model_kwargs` 会产生 UserWarning，thinking 控制可能被静默忽略——这是否构成不公平优势？

4. **额外优化**：阅读代码后，有没有我没想到的改进点？

5. **预期效果**：修复后 SeekFlow stable 的合理预期分数是多少？能否超越 LangChain 的 7.9？

---

## 六、关键代码片段

### web_search 当前实现 (shared_tools.py:62-88)
```python
def web_search(query: str, max_results: int = 4) -> str:
    """Search the web via 360 Search (so.com)."""
    try:
        url = "https://www.so.com/s?q=" + urllib.parse.quote(query)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 ..."
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception:
        return json.dumps({"results": [], "error": "Search unavailable"}, ...)
    # ... regex parse results ...
```

### _TASK_INSTRUCTIONS 当前长度 (shared_tools.py:208-257)
- financial_analyst: **562 字符**（工具铁律 + 痕迹要求 + 报告结构 + 执行规则）
- supply_chain_analyst: **799 字符**

### Stable 模式关键参数 (seekflow_agents.py:106-128)
```python
agent = DeepSeekAgent(
    thinking=True,
    temperature=0.0,
    max_steps=12,
    mode="stable",
    dangerous_tools=True,
)
```

---

**请基于以上信息和 GitHub 仓库中的完整代码，给出你的独立分析和最优修复方案。**
