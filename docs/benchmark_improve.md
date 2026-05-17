下面这份方案我会按“**修一次之后，SeekFlow stable 不再靠运气拿分，而是稳定、可复现、可解释地体现 Stable 模式优势**”来设计。你的本地结果显示，Stable 在 v4-pro 下平均 7.0，尤其 supply 场景 R1/R2 掉到 5.2/5.5，而 R3 在 web_search 成功后又能到 8.2，这已经说明问题不是 Stable 天生弱，而是 benchmark 环境和任务约束把 Stable 的真实工具执行能力反向变成了惩罚项。

我先给最终判断：**不要只把它当成 `web_search` 加锁的问题。真正要修的是一个四层系统：工具可靠性层、任务语义层、Agent 编排层、Judge/Runner 评测层。** 只修 `Semaphore(2)`，Stable 分数会变好，但仍然会被供应链任务的 `risk_score` 语义错配、Judge 只看报告不看真实工具日志、输出截断、LangChain thinking 控制不确定等问题继续污染。

---

# 一、核心诊断：现在的 benchmark 在惩罚“真实执行工具”的框架

当前 `shared_tools.py` 的 `web_search()` 是直接访问 360 搜索 HTML，没有并发保护、没有缓存、没有重试状态、没有区分“真实无结果”和“搜索失败/反爬/解析失败”；异常时只返回 `{"results": [], "error": "Search unavailable"}`，模型拿到的信息太少，既不知道是否可以降级，也不知道 final report 应该怎么诚实表达。代码里确实可以看到它直接 `urlopen(..., timeout=8)`，异常后只返回空 results 和 error。([GitHub][1])

但更关键的是，任务指令又要求“多个独立工具调用必须在一次回复中同时发起（并行）”，这对 Stable 是一个诱导性陷阱：Stable 真会并行、多轮、多工具执行，于是更容易把 `so.com` 打到限流；反过来 LangChain 或 fast 如果少调、不调工具，反而不会暴露工具失败。这个并行硬要求在 financial 和 supply 两套 `_TASK_INSTRUCTIONS` 里都存在。([GitHub][1])

Stable 模式本身还明确设置了 `thinking=True`、`max_steps=12`、`mode="stable"` 和 `dangerous_tools=True`。这意味着它天然会比 fast 和 LangChain 有更多推理轮次、更高 token、更长延迟。([GitHub][2]) DeepSeek 官方文档还说明，v4-pro thinking 默认是 enabled，thinking 模式下 `temperature` 等参数不会生效，并且如果 thinking 模式里发生 tool call，后续请求必须正确回传 `reasoning_content`。这说明你所谓“同温度 0.0”在 Stable thinking 模式下其实并不是完全同等约束。([DeepSeek API Docs][3])

Runner 也有一个容易误判的地方。当前 `AGENT_TIMEOUT` 在 main 里已经是 600 秒，不再是你本地描述里的 300 秒；而且代码只是运行完后判断 `elapsed > AGENT_TIMEOUT` 并打印 TIMEOUT，并没有真正中断任务。真正影响评分的是 `OUTPUT_TRUNCATION = 6000`，以及结果记录里只保存 `result.final_output[:OUTPUT_TRUNCATION]`。([GitHub][4]) Judge 也确实只把 `output[:MAX_OUTPUT_CHARS]` 发给评委模型，`MAX_OUTPUT_CHARS = 6000`。([GitHub][5]) 这会导致 Stable 越认真写、越详细展示工具痕迹，越容易在末尾关键建议、总结、缓解策略处被截断。

所以，根因不是一个点，而是这个链条：

**任务要求并行工具调用 → Stable 真实并行执行 → 360 搜索限流/空结果 → Prompt 没有安全降级出口 → v4-pro 为完成报告倾向补全/编造 → Judge 只看文本不看真实 tool log → 长输出被 6000 字符截断 → Completeness/Accuracy/Structure 一起掉分。**

---

# 二、第一优先级：把 `web_search` 从“不可靠外部依赖”改成“可控工具”

这里我建议你做两层修复。第一层是 hotfix，保留真实 `so.com`；第二层是 benchmark 正式版，默认用 fixture search。**真正严肃的基准测试，不应该把 live search 作为主评测路径。** 你现在想比较的是四个 Agent 框架，不是比较谁更不容易触发 360 搜索反爬。

## 2.1 hotfix：给真实 `web_search` 加限流、缓存、重试、失败语义

当前函数问题是：失败返回太贫血，模型只知道 `Search unavailable`，不知道该如何继续。你应该让工具返回一个结构化状态，至少包含 `status`、`query`、`results`、`error_type`、`instruction`、`data_quality`。为了兼容现有 Agent 框架，短期内可以继续返回 JSON string，不强行改成 dict。

建议改成这样：

```python
# shared_tools.py

import hashlib
import json
import random
import re
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

_SEARCH_SEM = threading.Semaphore(2)
_SEARCH_CACHE: dict[tuple[str, int], dict[str, Any]] = {}
_SEARCH_CACHE_LOCK = threading.Lock()

_SEARCH_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/605.1.15 Safari/605.1.15",
]

def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)

def _search_trace_id(query: str) -> str:
    return hashlib.sha1(query.encode("utf-8")).hexdigest()[:10]

def web_search(query: str, max_results: int = 4) -> str:
    """
    Search web via 360 Search.

    Return JSON string:
    {
      "status": "ok" | "unavailable" | "empty",
      "query": "...",
      "results": [...],
      "instruction": "...",
      "data_quality": "live_search_verified" | "search_unavailable" | "no_results"
    }
    """
    max_results = max(1, min(int(max_results), 6))
    cache_key = (query.strip(), max_results)

    with _SEARCH_CACHE_LOCK:
        cached = _SEARCH_CACHE.get(cache_key)
        if cached:
            payload = dict(cached)
            payload["cached"] = True
            return _json_result(payload)

    trace_id = _search_trace_id(query)
    last_error = ""

    with _SEARCH_SEM:
        for attempt in range(3):
            try:
                # 关键：不要每次完全同时打出去，给 so.com 留一点喘息
                if attempt > 0:
                    time.sleep(0.8 * (2 ** (attempt - 1)) + random.uniform(0.1, 0.4))

                url = "https://www.so.com/s?q=" + urllib.parse.quote(query)
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": random.choice(_SEARCH_USER_AGENTS),
                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    },
                )

                with urllib.request.urlopen(req, timeout=8) as resp:
                    html = resp.read().decode("utf-8", errors="replace")

                results = []
                for m in re.finditer(
                    r'<h3[^>]*class="res-title"[^>]*>(.*?)</h3>',
                    html,
                    re.DOTALL,
                ):
                    if len(results) >= max_results:
                        break

                    raw_title = m.group(1)
                    title = re.sub(r"<[^>]+>", "", raw_title).strip()
                    title = re.sub(r"\s+", " ", title)

                    if not title:
                        continue

                    tail = html[m.end(): m.end() + 1000]
                    desc_m = re.search(
                        r'class="res-list-summary"[^>]*>(.*?)</[^>]+>',
                        tail,
                        re.DOTALL,
                    )
                    snippet = ""
                    if desc_m:
                        snippet = re.sub(r"<[^>]+>", "", desc_m.group(1)).strip()
                        snippet = re.sub(r"\s+", " ", snippet)[:240]

                    results.append({
                        "rank": len(results) + 1,
                        "title": title[:150],
                        "snippet": snippet,
                    })

                if results:
                    payload = {
                        "status": "ok",
                        "query": query,
                        "trace_id": trace_id,
                        "cached": False,
                        "results": results,
                        "data_quality": "live_search_verified",
                        "instruction": (
                            "Use only these returned titles/snippets as external-search evidence. "
                            "Do not invent additional facts, dates, sources, or numeric values."
                        ),
                    }
                    with _SEARCH_CACHE_LOCK:
                        _SEARCH_CACHE[cache_key] = payload
                    return _json_result(payload)

                last_error = "empty_or_parse_failed"

            except Exception as e:
                last_error = f"{type(e).__name__}: {str(e)[:120]}"

    return _json_result({
        "status": "unavailable",
        "query": query,
        "trace_id": trace_id,
        "cached": False,
        "results": [],
        "error": last_error,
        "data_quality": "search_unavailable",
        "instruction": (
            "Search failed for this query. In the final report, explicitly write: "
            "「web_search 对该主题不可用，未获得可验证搜索结果」. "
            "Do not invent search findings, source names, dates, or numeric facts."
        ),
    })
```

这里的设计重点不是“让搜索永远成功”，而是让失败也成为可评分、可审计、不可伪造的状态。模型拿到 `status="unavailable"` 时，final report 里就必须写“未获得可验证搜索结果”，这比让它在铁律压力下编造要好。

另外，5 秒 timeout 我不建议。你本地测试是 8 秒超时触发失败，说明 360 在并发下会慢；如果你降成 5 秒，会让临界请求更多失败。我的建议是：**单请求 8 秒，最多 3 次，总并发 2，失败间隔指数退避。** 搜索任务不是高频在线服务，benchmark 里更重要的是结果稳定。

## 2.2 正式 benchmark：默认使用 fixture search，不用 live web

更高质量的做法是加一个环境变量：

```python
SEARCH_BACKEND = os.getenv("BENCH_SEARCH_BACKEND", "fixture")
```

默认 `fixture`，只有你专门想测真实搜索能力时才切到 `live`。原因很简单：live search 会受到网络、反爬、HTML 结构、地区、时间、搜索引擎状态影响；这些都不是 Agent 框架能力。主基准应该可复现。

你可以在 `shared_tools.py` 里内置一个最小 fixture：

```python
_FIXTURE_SEARCH = {
    "科技行业趋势": [
        {"title": "AI 基础设施投资持续增长", "snippet": "云计算、AI 芯片和企业智能化仍是科技行业主要增长方向。"},
        {"title": "软件订阅和算力需求推动科技企业收入", "snippet": "企业数字化预算继续向 AI、数据平台和自动化工具倾斜。"},
    ],
    "消费品行业趋势": [
        {"title": "消费品行业关注品牌韧性和渠道效率", "snippet": "高端化、健康化和线上线下融合成为消费品企业竞争重点。"},
    ],
    "新能源行业趋势": [
        {"title": "新能源需求受电动车和储能市场拉动", "snippet": "电动车、储能、电池材料和电网升级继续支撑新能源产业链增长。"},
    ],
    "台海芯片供应风险": [
        {"title": "芯片供应链高度集中带来地缘风险", "snippet": "先进制程和封装产能集中在东亚，地缘扰动可能影响汽车芯片供应稳定性。"},
    ],
    "南美锂矿供应风险": [
        {"title": "锂资源供应受政策、环保和基础设施影响", "snippet": "南美锂矿开发周期长，政策调整和社区环保要求可能影响供应节奏。"},
    ],
    "欧洲碳关税政策": [
        {"title": "欧洲碳边境调节机制提高出口企业合规成本", "snippet": "高碳排产品进入欧洲市场需要更严格的碳排放核算和成本管理。"},
    ],
}
```

然后：

```python
def fixture_search(query: str, max_results: int = 4) -> str:
    hits = []
    for key, rows in _FIXTURE_SEARCH.items():
        if key in query or query in key:
            hits = rows[:max_results]
            break

    if not hits:
        hits = [{
            "title": f"Fixture fallback for {query}",
            "snippet": "No exact fixture key matched. This is a controlled fallback, not live web evidence.",
        }]

    return _json_result({
        "status": "ok",
        "backend": "fixture",
        "query": query,
        "results": [
            {"rank": i + 1, **row}
            for i, row in enumerate(hits)
        ],
        "data_quality": "fixture_verified",
        "instruction": "Use only these fixture snippets as benchmark evidence.",
    })
```

然后 `web_search()` 变成：

```python
def web_search(query: str, max_results: int = 4) -> str:
    backend = os.getenv("BENCH_SEARCH_BACKEND", "fixture").lower()
    if backend == "live":
        return live_web_search(query, max_results)
    return fixture_search(query, max_results)
```

这样你可以跑两套结果：

```bash
BENCH_SEARCH_BACKEND=fixture python runner.py
BENCH_SEARCH_BACKEND=live python runner.py
```

主论文/README 里报告 fixture 结果，附录报告 live stress 结果。这样才是架构上干净的设计。

---

# 三、第二优先级：修正任务语义，不要让 supply 场景强行套金融 `risk_score`

这是我认为你目前漏掉的最大根因。`risk_score(volatility_percent, debt_ratio, market_cap_billions)` 明显是金融风险工具，内部公式也是 volatility、debt、market cap 三项加权。([GitHub][6]) 但 supply 任务要求它评估“台海芯片、南美锂矿、欧洲碳关税”等供应链风险，这些风险没有 volatility、debt_ratio、market_cap_billions。任务又要求“引用 risk_score 工具返回的评分”，模型只能自己造参数。

这不是模型不老实，而是任务逼它不老实。

这里有两个方案。

## 3.1 最优方案：新增供应链风险工具

如果你允许 benchmark v2.1 从 8 个工具变成 9 个工具，建议新增：

```python
def supply_risk_score(
    probability_percent: float,
    impact_score: float,
    exposure_percent: float,
) -> dict:
    """
    Calculate supply-chain risk score.

    probability_percent: likelihood of disruption, 0-100
    impact_score: business impact, 1-10
    exposure_percent: share of supply/revenue/cost exposed, 0-100
    """
    p = max(0, min(100, probability_percent)) / 100
    i = max(1, min(10, impact_score)) / 10
    e = max(0, min(100, exposure_percent)) / 100

    score = round((p * 0.4 + i * 0.35 + e * 0.25) * 10, 1)
    return {
        "risk_score": score,
        "rating": "LOW" if score < 3 else "MEDIUM" if score < 6 else "HIGH" if score < 8 else "CRITICAL",
        "input_echo": {
            "probability_percent": probability_percent,
            "impact_score": impact_score,
            "exposure_percent": exposure_percent,
        },
        "formula": "risk_score=(probability*0.4 + impact*0.35 + exposure*0.25)*10",
        "data_quality": "scenario_inputs_or_explicit_proxy",
    }
```

然后 `SHARED_TOOLS` 加上它：

```python
SHARED_TOOLS = [
    calculate_roi,
    compound_growth,
    risk_score,
    supply_risk_score,
    web_search,
    statistical_summary,
    read_file,
    convert_currency,
    extract_keywords,
]
```

供应链任务改为：

```text
- supply_risk_score：评估不同供应链风险维度的综合评分
  参数必须使用下列情景代理值：
  1. 台海芯片：probability_percent=35, impact_score=9, exposure_percent=45
  2. 南美/非洲电池原材料：probability_percent=30, impact_score=8, exposure_percent=60
  3. 欧洲碳关税：probability_percent=70, impact_score=6, exposure_percent=35
```

这个方案最干净，因为工具语义和任务语义一致。唯一代价是：你不能把它叫“同一 8 个工具”的旧 benchmark 了，应该明确命名为 `fair_comparison_v2_1` 或 `v3`。

## 3.2 保守方案：不新增工具，但显式给出 risk_score 代理参数

如果你必须保持 8 个工具，就不要再让模型自己推 risk_score 参数。直接在 supply 任务中写：

```text
risk_score 仅作为统一评分器使用，供应链风险参数采用以下固定代理映射：
1. 台海芯片风险：volatility_percent=45, debt_ratio=0.65, market_cap_billions=20
2. 电池原材料风险：volatility_percent=38, debt_ratio=0.55, market_cap_billions=30
3. 欧洲碳关税风险：volatility_percent=28, debt_ratio=0.35, market_cap_billions=80

这些参数是 benchmark 给定代理值，不代表真实财务指标。报告中必须写明「工具代理评分」。
```

这虽然语义不完美，但至少消除了“模型自行编造输入参数”的扣分点。

---

# 四、第三优先级：Prompt 要从“铁律压迫”改成“可审计工作流”

现在 `_TASK_INSTRUCTIONS` 的问题不是长，而是有几条指令互相冲突。比如 supply 里写“工具返回的数值是你唯一的数据来源”，又写“报告中绝不出现基于经验/专业知识”，但 web_search 失败时模型又必须完成报告。这会把模型逼进死角。([GitHub][1])

我建议把两个场景统一成一个短模板，减少重复，同时给出诚实失败出口。

```python
_COMMON_TASK_RULES = """
## 执行规则

1. 数值计算必须调用工具。工具成功返回后，报告必须引用工具返回值，并标注「工具：tool_name」。
2. 搜索类工具若返回 status=ok，只能使用返回的 title/snippet 作为外部证据。
3. 搜索类工具若返回 status=unavailable 或 results=[]，必须写明「未获得可验证搜索结果」，不得编造搜索结论、来源、日期或数字。
4. 报告必须包含一个「工具调用摘要」小节，列出工具名、关键输入、关键返回值。
5. 不强制并行调用；可以并行，但不得超过工具限流。所有必需工具完成或明确失败后，再写最终报告。
6. 最终报告控制在 4500 中文字符以内，优先保留结论、关键数值、工具来源和建议。
"""
```

financial 专用任务改成更明确：

```python
_FINANCIAL_TASK = """
请分析以下三家公司的投资价值，生成中文投资备忘录。

公司数据：
A 科技公司：
- volatility_percent=32
- debt_ratio=0.15
- market_cap_billions=85.0  # 850亿美元 = 85.0 billion USD
- investment=500  # 万美元
- revenue=870     # 万美元
- growth_rate_percent=15

B 消费品公司：
- volatility_percent=18
- debt_ratio=0.42
- market_cap_billions=12.0  # 120亿美元 = 12.0 billion USD
- investment=300
- revenue=410
- growth_rate_percent=8

C 新能源公司：
- volatility_percent=45
- debt_ratio=0.28
- market_cap_billions=3.5  # 35亿美元 = 3.5 billion USD
- investment=800
- revenue=1250
- growth_rate_percent=25

必须执行：
- web_search：科技行业趋势、消费品行业趋势、新能源行业趋势
- calculate_roi：A/B/C 各一次
- compound_growth：A/B/C 各一次，principal 使用 revenue，years=5
- risk_score：A/B/C 各一次，严格使用上方 volatility/debt/market_cap 参数
- statistical_summary：输入 "85.0,12.0,3.5"
- convert_currency：将 A/B/C investment 分别从 USD 转 CNY、EUR

输出结构：
1. 执行摘要
2. 工具调用摘要
3. 三家公司关键指标对比
4. 风险与增长分析
5. 投资建议
"""
```

supply 专用任务也要给定所有可计算参数：

```python
_SUPPLY_TASK = """
请分析中国电动汽车制造商供应链风险，生成中文风险评估报告。

场景数据：
- 年产量：50万辆
- 电池原材料60%来自南美和非洲
- 芯片供应45%依赖台湾和韩国
- 欧洲市场需求增长35%
- 海运成本12个月数据：3200,3400,3800,4100,3900,3600,3400,3100,3300,3600,4200,4500
- 欧洲建厂投资：2亿欧元
- 欧洲年运营成本：3500万欧元

必须执行：
- web_search：台海芯片供应风险、南美锂矿供应风险、欧洲碳关税政策
- statistical_summary：分析海运成本数据
- compound_growth：principal=500000, rate_percent=18, years=3，用于估算产量/需求增长
- convert_currency：amount=200000000, from_currency=EUR, to_currency=CNY
- extract_keywords：输入三个 web_search 返回 snippet 拼接文本；若搜索失败，则输入失败声明文本
- risk_score 或 supply_risk_score：按下方固定参数执行，不得自行改参数

如果保留 risk_score：
1. 台海芯片风险：volatility_percent=45, debt_ratio=0.65, market_cap_billions=20
2. 电池原材料风险：volatility_percent=38, debt_ratio=0.55, market_cap_billions=30
3. 欧洲碳关税风险：volatility_percent=28, debt_ratio=0.35, market_cap_billions=80

输出结构：
1. 执行摘要
2. 工具调用摘要
3. 风险矩阵
4. 海运成本趋势
5. 原材料/产量需求增长
6. 欧洲建厂成本影响
7. 缓解策略
8. 总结建议
"""
```

这个 Prompt 的核心是：**把“模型应该推理的部分”和“模型绝不能编造的部分”分开。** 工具参数、单位、固定场景数据都给死；模型负责解释、比较、排序、建议。

---

# 五、第四优先级：工具函数必须返回 `input_echo` 和 `warnings`

现在 `risk_score` 最大的问题是输入进去什么，报告里不一定能审计。建议所有计算工具都返回 `input_echo`、`formula`、`data_quality`。这样 Judge 或程序化检查器可以自动核对。

例如 `risk_score`：

```python
def risk_score(
    volatility_percent: float,
    debt_ratio: float,
    market_cap_billions: float,
) -> dict:
    """
    Calculate a composite financial risk score.
    market_cap_billions means billion USD.
    Example: 850亿美元 = 85.0 billion USD.
    """
    warnings = []

    if market_cap_billions <= 0:
        warnings.append("market_cap_billions must be positive.")
    if market_cap_billions > 250:
        warnings.append(
            "market_cap_billions unusually large. "
            "If the source value is 亿美元, convert 850亿美元 -> 85.0 billion USD."
        )
    if debt_ratio > 1:
        warnings.append("debt_ratio is usually 0-1. Check whether percent was passed accidentally.")

    v_score = min(10, volatility_percent / 5)
    d_score = min(10, debt_ratio * 10)
    m_score = max(0, 5 - market_cap_billions / 50) if market_cap_billions < 250 else 0
    composite = round((v_score * 0.4 + d_score * 0.35 + m_score * 0.25), 1)

    return {
        "risk_score": composite,
        "rating": (
            "LOW" if composite < 3
            else "MEDIUM" if composite < 6
            else "HIGH" if composite < 8
            else "CRITICAL"
        ),
        "breakdown": {
            "volatility_component": round(v_score, 1),
            "debt_component": round(d_score, 1),
            "size_component": round(m_score, 1),
        },
        "input_echo": {
            "volatility_percent": volatility_percent,
            "debt_ratio": debt_ratio,
            "market_cap_billions": market_cap_billions,
        },
        "unit_note": "market_cap_billions is billion USD; 850亿美元 = 85.0",
        "formula": "0.4*volatility_component + 0.35*debt_component + 0.25*size_component",
        "warnings": warnings,
        "data_quality": "tool_calculated",
    }
```

`calculate_roi` 也建议加：

```python
def calculate_roi(investment: float, revenue: float) -> dict:
    roi = ((revenue - investment) / investment) * 100
    return {
        "roi_percent": round(roi, 2),
        "net_profit": round(revenue - investment, 2),
        "profit_margin_percent": round((revenue - investment) / revenue * 100, 2) if revenue else 0,
        "input_echo": {
            "investment": investment,
            "revenue": revenue,
        },
        "formula": "roi=(revenue-investment)/investment*100",
        "data_quality": "tool_calculated",
    }
```

`compound_growth`：

```python
def compound_growth(principal: float, rate_percent: float, years: int) -> dict:
    rate = rate_percent / 100
    values = [round(principal * (1 + rate) ** y, 2) for y in range(years + 1)]
    return {
        "final_value": values[-1],
        "total_growth_percent": round((values[-1] / principal - 1) * 100, 2),
        "year_by_year": values,
        "input_echo": {
            "principal": principal,
            "rate_percent": rate_percent,
            "years": years,
        },
        "formula": "principal*(1+rate)^year",
        "data_quality": "tool_calculated",
    }
```

这样做的好处是，模型即便写错，后面的程序化 Judge 也能查出来。

---

# 六、第五优先级：增加全局工具调用日志，不再依赖各框架自己报 TC

现在 LangChain 的工具调用计数并不等价于 SeekFlow。LangChain 代码里 `tool_calls_count = sum(1 for m in messages if ... m.tool_calls)`，这统计的是“有 tool_calls 的消息数”，不是具体 tool call 个数。([GitHub][7]) CrewAI 更明显，当前直接 `tool_calls_count=0`，注释说 CrewAI 不暴露 per-tool count。([GitHub][8])

这会污染你的“工具调用悖论”分析。正确做法是：**不要相信框架暴露的 tool count，而是在 shared_tools 层统一打点。** 因为四个框架最后都调用同一批 Python 函数，所以只要函数入口统一包装，tool log 就天然公平。

在 `shared_tools.py` 里加：

```python
import functools
import threading
import time
import traceback
from dataclasses import dataclass, asdict
from typing import Callable

_TOOL_EVENTS_LOCK = threading.Lock()
_TOOL_EVENTS: list[dict] = []

def reset_tool_events() -> None:
    with _TOOL_EVENTS_LOCK:
        _TOOL_EVENTS.clear()

def get_tool_events() -> list[dict]:
    with _TOOL_EVENTS_LOCK:
        return list(_TOOL_EVENTS)

def _safe_preview(obj, max_chars: int = 800) -> str:
    try:
        text = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        text = str(obj)
    return text[:max_chars]

def instrument_tool(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        started = time.perf_counter()
        event = {
            "tool": fn.__name__,
            "args": args,
            "kwargs": kwargs,
            "started_at_perf": started,
            "success": False,
            "latency_seconds": None,
            "result_preview": "",
            "error": "",
        }
        try:
            result = fn(*args, **kwargs)
            event["success"] = True
            event["result_preview"] = _safe_preview(result)
            return result
        except Exception as e:
            event["error"] = f"{type(e).__name__}: {str(e)}"
            event["traceback"] = traceback.format_exc()[-1000:]
            raise
        finally:
            event["latency_seconds"] = round(time.perf_counter() - started, 3)
            with _TOOL_EVENTS_LOCK:
                _TOOL_EVENTS.append(event)

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    wrapper.__module__ = fn.__module__
    return wrapper
```

然后把 `SHARED_TOOLS` 改成：

```python
_RAW_TOOLS = [
    calculate_roi,
    compound_growth,
    risk_score,
    web_search,
    statistical_summary,
    read_file,
    convert_currency,
    extract_keywords,
]

SHARED_TOOLS = [instrument_tool(t) for t in _RAW_TOOLS]
```

接着扩展 `AgentRunResult`：

```python
@dataclass
class AgentRunResult:
    ...
    tool_calls_count: int
    tool_events: list[dict] = field(default_factory=list)
```

在每个 runner 函数开头 reset，结尾收集：

```python
from benchmarks.fair_comparison_v2.shared_tools import (
    SHARED_TOOLS,
    SYSTEM_PROMPTS,
    TASKS,
    reset_tool_events,
    get_tool_events,
)

def run_seekflow_stable(api_key: str, scenario: str) -> AgentRunResult:
    reset_tool_events()
    ...
    result = agent.run(TASKS[scenario])
    tool_events = get_tool_events()
    return AgentRunResult(
        ...
        tool_calls_count=len(tool_events),
        tool_events=tool_events,
    )
```

LangChain、CrewAI 也同样处理。这样四个框架的 TC 才真正可比。CrewAI 即便不暴露内部记录，你也能从实际 Python 函数调用层拿到真实调用日志。

---

# 七、第六优先级：Runner 要保存 full output、tool_events、truncation 状态

现在 Runner 只保存截断后的输出：

```python
"output": result.final_output[:OUTPUT_TRUNCATION]
```

这会导致两个问题：第一，后续 `rescore.py` 永远拿不到完整报告；第二，你不知道 Judge 评分到底是因为报告差，还是因为被截断。`rescore.py` 当前也是直接读 `r.get("output", "")` 复评，因此复评仍然基于截断文本。([GitHub][9])

建议记录结构改成：

```python
output_full = result.final_output or ""
output_for_judge = output_full[:OUTPUT_TRUNCATION]

record = {
    "round": rnd,
    "framework": fw_name,
    "mode": mode,
    "scenario": scenario,
    "success": True,

    "latency_seconds": result.latency_seconds,
    "prompt_tokens": result.prompt_tokens,
    "completion_tokens": result.completion_tokens,
    "total_tokens": result.total_tokens,
    "cached_tokens": result.cached_tokens,
    "cache_hit_rate": result.cache_hit_rate,
    "cost_cny": result.cost_cny,

    "tool_calls_count": len(result.tool_events),
    "tool_events": result.tool_events,

    "model_used": result.model_used,
    "scores": scores,

    "output_full": output_full,
    "output_for_judge": output_for_judge,
    "output_chars": len(output_full),
    "judge_output_chars": len(output_for_judge),
    "was_truncated_for_judge": len(output_full) > OUTPUT_TRUNCATION,
}
```

同时 `judge_output()` 可以先不改，继续只看 6000 字符；但你必须把 `was_truncated_for_judge` 放进报告分析。更好的做法是两种分数都保存：

```python
scores_truncated = judge_output(api_key, TASKS[scenario], output_for_judge)
scores_full = judge_output(api_key, TASKS[scenario], output_full[:12000])
```

然后报告里分别显示：

```text
overall_6k
overall_12k
delta_due_to_truncation
```

如果 Stable 的 12k 分数显著高于 6k，那你就能证明它不是报告质量差，而是输出长度和 Judge 截断机制导致扣分。

---

# 八、第七优先级：Judge 必须引入“工具合规评分”，不能只看最终报告

当前 Judge 是盲审没错，但它只看 task 和 output，不看真实 tool events。Rubric 里 Accuracy 只是判断事实和计算是否正确，1 分是 mostly incorrect or fabricated data；但如果一个框架没有真实调用工具，却在文本里伪造漂亮的工具痕迹，LLM Judge 不一定能识别。([GitHub][5])

所以最优设计是“双 Judge”：

**第一层：LLM Judge，评报告质量。**

保留现在 6 维度：Completeness、Accuracy、Depth、Structure、Actionability、Professionalism。

**第二层：Programmatic Compliance Judge，评工具真实性。**

程序化评分不靠模型，直接看 `tool_events` 和任务要求。

建议新增 `compliance.py`：

```python
REQUIRED_TOOLS = {
    "financial_analyst": {
        "web_search": 3,
        "calculate_roi": 3,
        "compound_growth": 3,
        "risk_score": 3,
        "statistical_summary": 1,
        "convert_currency": 6,  # A/B/C to CNY/EUR
    },
    "supply_chain_analyst": {
        "web_search": 3,
        "statistical_summary": 1,
        "compound_growth": 1,
        "convert_currency": 1,
        "extract_keywords": 1,
        "risk_score": 3,
        # or "supply_risk_score": 3
    },
}

EXPECTED_RISK_ARGS = {
    "financial_analyst": [
        {"volatility_percent": 32, "debt_ratio": 0.15, "market_cap_billions": 85.0},
        {"volatility_percent": 18, "debt_ratio": 0.42, "market_cap_billions": 12.0},
        {"volatility_percent": 45, "debt_ratio": 0.28, "market_cap_billions": 3.5},
    ],
    "supply_chain_analyst": [
        {"volatility_percent": 45, "debt_ratio": 0.65, "market_cap_billions": 20},
        {"volatility_percent": 38, "debt_ratio": 0.55, "market_cap_billions": 30},
        {"volatility_percent": 28, "debt_ratio": 0.35, "market_cap_billions": 80},
    ],
}

def score_tool_compliance(scenario: str, tool_events: list[dict], output: str) -> dict:
    counts = {}
    for e in tool_events:
        if e.get("success"):
            counts[e["tool"]] = counts.get(e["tool"], 0) + 1

    required = REQUIRED_TOOLS[scenario]
    missing = {}
    coverage_points = 0
    coverage_total = 0

    for tool, min_count in required.items():
        actual = counts.get(tool, 0)
        coverage_total += min_count
        coverage_points += min(actual, min_count)
        if actual < min_count:
            missing[tool] = {"expected": min_count, "actual": actual}

    coverage_score = round(10 * coverage_points / coverage_total, 1) if coverage_total else 10

    honesty_penalty = 0
    if "Search unavailable" in output and "web_search" not in counts:
        # 可选：这不是错，说明模型诚实降级
        pass

    fabricated_trace_penalty = 0
    # 如果输出声称调用了工具，但 tool_events 没有，可扣分
    for tool in required:
        if tool in output and counts.get(tool, 0) == 0:
            fabricated_trace_penalty += 1

    final = max(0, coverage_score - fabricated_trace_penalty)

    return {
        "tool_coverage_score": coverage_score,
        "tool_compliance_score": round(final, 1),
        "tool_counts": counts,
        "missing_required_tools": missing,
        "fabricated_trace_penalty": fabricated_trace_penalty,
    }
```

然后总分不要只用 LLM overall。建议：

```python
overall_final = round(
    0.70 * scores["overall"] +
    0.30 * compliance["tool_compliance_score"],
    1
)
```

或者更干净地分开报告：

```text
Report Quality Score: 7.9
Tool Compliance Score: 4.0
Final Agent Benchmark Score: 6.7
```

这样 LangChain 如果少调工具但写得漂亮，报告质量可能高，工具合规就会低。Stable 如果真调用且报告略长，工具合规会把它拉回来。这才是 Agent benchmark，而不是“报告写作 benchmark”。

---

# 九、第八优先级：修复 LangChain 的 `extra_body` 传参，否则 thinking 控制不可靠

当前 LangChain 代码是：

```python
model_kwargs={"extra_body": {"thinking": {"type": "disabled"}}}
```

这确实有问题。LangChain 官方文档明确说，OpenAI-compatible provider 的自定义参数应使用顶层 `extra_body`，不要把非标准参数放进 `model_kwargs`；`model_kwargs` 会作为顶层 request payload 合并，而 `extra_body` 才是推荐的 provider-specific 参数入口。([LangChain Reference Docs][10])

应该改成：

```python
llm = ChatOpenAI(
    model=MODEL,
    api_key=api_key,
    base_url="https://api.deepseek.com/v1",
    temperature=0.0,
    request_timeout=120,
    extra_body={"thinking": {"type": "disabled"}},
)
```

这不是小问题。DeepSeek 官方文档说 v4-pro thinking 默认 enabled，而且 thinking 模式下 temperature 不生效。([DeepSeek API Docs][3]) 如果 LangChain 的 thinking disabled 没有真的生效，那它就可能不是你表格里写的“thinking 关”。如果它反而被静默启用了 thinking，又没有正确处理 `reasoning_content`，还可能造成隐藏错误。DeepSeek 文档说明 thinking + tool calls 后续必须回传 `reasoning_content`，否则可能 API 报错。([DeepSeek API Docs][3])

所以你要加一个 smoke test，而不是靠配置猜。

```python
def smoke_test_thinking_control(api_key: str):
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    for mode in ["enabled", "disabled"]:
        resp = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=[{"role": "user", "content": "只回答 OK"}],
            extra_body={"thinking": {"type": mode}},
        )
        msg = resp.choices[0].message
        print(mode, {
            "content": getattr(msg, "content", None),
            "has_reasoning_content": bool(getattr(msg, "reasoning_content", None)),
            "usage": getattr(resp, "usage", None),
        })
```

然后给 LangChain 单独测一次：

```python
def smoke_test_langchain(api_key: str):
    llm = ChatOpenAI(
        model="deepseek-v4-pro",
        api_key=api_key,
        base_url="https://api.deepseek.com/v1",
        temperature=0.0,
        extra_body={"thinking": {"type": "disabled"}},
    )
    r = llm.invoke("只回答 OK")
    print(r.response_metadata)
    print(r.usage_metadata)
```

只有确认没有 `reasoning_content`，你才能说 LangChain thinking 真的关了。

---

# 十、第九优先级：CrewAI 必须显式处理 thinking，否则 DNF 不可解释

CrewAI 当前只配置：

```python
llm = LLM(
    model=f"deepseek/{MODEL}",
    api_key=api_key,
    temperature=0.0,
)
```

没有看到任何 `extra_body={"thinking": {"type": "disabled"}}` 或 provider-specific 参数。([GitHub][8]) 如果 CrewAI/LiteLLM 默认没有传 thinking disabled，那么在 v4-pro 默认 thinking enabled 的情况下，它可能会进入 reasoning_content 协议问题。DeepSeek 文档对 thinking 默认 enabled、tool call 后必须回传 reasoning_content 的说明，让 CrewAI 的 DNF 有很大概率不是“框架能力差”，而是 provider 参数和协议没有适配。([DeepSeek API Docs][3])

你需要做两个选择：

如果 CrewAI 当前版本能传 provider-specific kwargs，就显式传：

```python
llm = LLM(
    model=f"deepseek/{MODEL}",
    api_key=api_key,
    temperature=0.0,
    extra_body={"thinking": {"type": "disabled"}},
)
```

如果 CrewAI 不支持这个参数，就不要把 CrewAI v4-pro 结果纳入主排名，而是标注：

```text
CrewAI excluded from v4-pro main comparison because current adapter cannot reliably disable DeepSeek thinking mode or replay reasoning_content during tool calls.
```

否则 CrewAI DNF 会污染“框架公平性”结论。

---

# 十一、第十优先级：统一系统提示解析，修掉 `strip()` 的隐性 bug

SeekFlow 和 CrewAI 都有类似代码：

```python
role=sys_prompt.split("\n")[0].strip("你是一名")
goal=sys_prompt.split("\n")[1].strip("1. ")
```

`strip("你是一名")` 不是移除前缀“你是一名”，而是从字符串两端删除任意出现在这个字符集合里的字符。这个 bug 现在可能没直接导致崩塌，但它是不专业、不稳定的。建议统一写一个 helper：

```python
def parse_system_prompt(sys_prompt: str) -> tuple[str, str, str]:
    lines = [x.strip() for x in sys_prompt.splitlines() if x.strip()]
    role_line = lines[0] if lines else "通用分析师"
    goal_line = lines[1] if len(lines) > 1 else "完成任务"

    role = role_line
    if role.startswith("你是一名"):
        role = role.removeprefix("你是一名").strip("。 ")

    goal = goal_line.strip("。 ")
    backstory = role_line

    return role, goal, backstory
```

然后 SeekFlow 和 CrewAI 都用：

```python
role, goal, backstory = parse_system_prompt(SYSTEM_PROMPTS[scenario])
```

这属于工程质量修复，成本很低，值得做。

---

# 十二、建议按三个版本推进，不要一次全改导致不可归因

## v2.0.1：最小热修复版

目标是验证你原来的 5 个根因能不能被修掉。只改这些：

第一，`web_search` 加 `Semaphore(2)`、重试、缓存、结构化失败 instruction。

第二，Prompt 去掉“必须并行”，加入“搜索失败声明模板”，加入 4500 字符输出上限。

第三，financial 任务写死 `market_cap_billions` 参数：85.0、12.0、3.5。

第四，supply 任务写死 `risk_score` 代理参数，避免模型自己编。

第五，Runner 保存 `output_full`、`output_for_judge`、`was_truncated_for_judge`。

第六，LangChain 把 `model_kwargs={"extra_body": ...}` 改成顶层 `extra_body=...`。

这一版做完，Stable 预计能从 7.0 到 **7.6–8.0**。如果 `web_search` 成功率稳定，supply R1/R2 不会再掉到 5 分段。

## v2.1：可审计版

目标是修正评测公平性。新增这些：

第一，全局 `tool_events` 打点。

第二，所有框架的 `tool_calls_count` 都来自 `tool_events`。

第三，新增 `compliance.py`，输出工具覆盖率、参数正确率、搜索诚实度、单位一致性。

第四，报告同时输出 `report_quality_score` 和 `tool_compliance_score`。

这一版做完，LangChain “少调工具但报告好看”的优势会被重新校正，Stable 的真实执行能力会反映到分数里。Stable 合理预期 **8.0–8.4**。

## v3.0：严格公平基准版

目标是让 benchmark 可以公开、复现、论文级别可信。

第一，默认 `BENCH_SEARCH_BACKEND=fixture`。

第二，live search 只作为附录 stress test。

第三，供应链任务新增 `supply_risk_score`，不再复用金融 `risk_score`。

第四，每个 scenario 都提供 expected tool contract，比如必须调用哪些工具、每个工具的允许参数范围、哪些数字必须来自工具。

第五，Judge 使用 full output 或至少 12k 字符，同时仍保存 6k 截断分数用于对照。

第六，所有模型 thinking 状态先跑 smoke test，未通过的框架不进入主榜。

这一版才是真正的“框架公平横评”。

---

# 十三、你应该新增哪些测试

不要直接跑完整 benchmark。先写单元测试和小型 smoke test。

## 13.1 web_search 并发测试

```python
def test_web_search_concurrency():
    from concurrent.futures import ThreadPoolExecutor
    from shared_tools import web_search

    queries = [
        "台海芯片供应风险",
        "南美锂矿供应风险",
        "欧洲碳关税政策",
        "科技行业趋势",
        "消费品行业趋势",
        "新能源行业趋势",
    ] * 3

    with ThreadPoolExecutor(max_workers=6) as ex:
        rows = list(ex.map(web_search, queries))

    parsed = [json.loads(x) for x in rows]
    unavailable = [x for x in parsed if x["status"] == "unavailable"]

    assert len(unavailable) <= 2  # live 模式可以放宽
```

fixture 模式则应该是：

```python
assert len(unavailable) == 0
```

## 13.2 单位测试

```python
def test_market_cap_units():
    r = risk_score(32, 0.15, 85.0)
    assert r["input_echo"]["market_cap_billions"] == 85.0
    assert r["risk_score"] < 6

    wrong = risk_score(32, 0.15, 850.0)
    assert wrong["warnings"]
```

## 13.3 supply 统计测试

你的海运成本数据用当前 `statistical_summary` 的总体标准差公式，应该得到：

```text
mean = 3675.0
median = 3600.0
std_dev ≈ 414.5781
min = 3100
max = 4500
range = 1400
```

这个可以作为程序化 Judge 的校验基准。如果模型报告里写均值 3658 或标准差 428，就要看它是否用了不同公式；如果工具返回是 3675.0，而报告写别的，就应该扣 Accuracy。

## 13.4 LangChain thinking smoke test

修复前后都跑一次。如果修复前 UserWarning 出现，修复后不出现，并且响应 metadata 没有 reasoning_content，才算通过。

## 13.5 Stable 截断敏感性测试

同一个 Stable 输出，分别用 6000、9000、12000 字符 Judge：

```python
for limit in [6000, 9000, 12000]:
    scores = judge_output(api_key, task, output[:limit])
    print(limit, scores["overall"], scores["critique"])
```

如果分数随字符数明显上升，就证明 Stable 被截断机制惩罚。

---

# 十四、最终代码改动清单

你可以按这个顺序提交 PR。

**Commit 1：shared_tools search robustness**

改 `web_search`，新增限流、缓存、重试、status、instruction、data_quality。

**Commit 2：shared_tools tool result contracts**

给 `risk_score`、`calculate_roi`、`compound_growth`、`statistical_summary`、`convert_currency` 增加 `input_echo`、`formula`、`data_quality`、`warnings`。

**Commit 3：prompt/task cleanup**

重写 `_TASK_INSTRUCTIONS`，去掉“必须并行”，加失败声明模板，加 4500 字符限制，加明确参数表。

**Commit 4：supply risk semantic fix**

保守版：给 supply 的 `risk_score` 固定代理参数。
理想版：新增 `supply_risk_score`，并更新 supply task。

**Commit 5：tool event instrumentation**

新增 `reset_tool_events()`、`get_tool_events()`、`instrument_tool()`，让所有框架共享真实 tool log。

**Commit 6：AgentRunResult extension**

`AgentRunResult` 增加 `tool_events`，SeekFlow/LangChain/CrewAI 都填充它，`tool_calls_count` 改成 `len(tool_events)`。

**Commit 7：LangChain thinking fix**

`model_kwargs={"extra_body": ...}` 改成 `extra_body={"thinking": {"type": "disabled"}}`。

**Commit 8：Runner output preservation**

保存 `output_full`、`output_for_judge`、`was_truncated_for_judge`、`tool_events`。

**Commit 9：compliance judge**

新增 `compliance.py`，Runner 同时保存 `quality_scores`、`compliance_scores`、`final_scores`。

**Commit 10：fixture backend**

加 `BENCH_SEARCH_BACKEND=fixture/live`，默认 fixture。

---

# 十五、修复后预期结果

如果你只做 hotfix，也就是 web_search 限流、Prompt 精简、失败 instruction、单位示例、timeout 600，那么 Stable 大概率能从 **7.0 提到 7.6–7.9**。但它能不能稳定超过 LangChain 7.9，不一定，因为当前 Judge 仍然偏向“最终报告好看”，没有真正奖励“工具真实执行”。

如果你做完整方案，也就是 fixture search、supply 风险工具语义修复、tool event logging、compliance judge、LangChain/CrewAI thinking 控制修复，那么 Stable 合理区间应该是 **8.0–8.4**。它不仅有机会超过 LangChain，而且这个超过会更有说服力，因为你能证明：Stable 的工具覆盖率、参数正确率、失败诚实度、单位一致性都更高。

但我要强调一句：**如果你不引入 tool log 和 compliance judge，那么这个 benchmark 本质上仍然更像“报告生成质量评测”，不是严格的 Agent 工具执行能力评测。** 在那种评分机制下，LangChain 少调工具、少暴露失败、输出更短更整洁，继续拿高分并不奇怪。真正要让 SeekFlow stable 的优势显现，必须让评测系统看见“它真的执行了什么、工具返回了什么、报告是否忠实使用了这些返回值”。

[1]: https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/shared_tools.py "SeekFlow/benchmarks/fair_comparison_v2/shared_tools.py at main · WYZAAACCC/SeekFlow · GitHub"
[2]: https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/seekflow_agents.py "SeekFlow/benchmarks/fair_comparison_v2/seekflow_agents.py at main · WYZAAACCC/SeekFlow · GitHub"
[3]: https://api-docs.deepseek.com/guides/thinking_mode?utm_source=chatgpt.com "Thinking Mode | DeepSeek API Docs"
[4]: https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/runner.py "SeekFlow/benchmarks/fair_comparison_v2/runner.py at main · WYZAAACCC/SeekFlow · GitHub"
[5]: https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/judge.py "SeekFlow/benchmarks/fair_comparison_v2/judge.py at main · WYZAAACCC/SeekFlow · GitHub"
[6]: https://raw.githubusercontent.com/WYZAAACCC/SeekFlow/main/benchmarks/fair_comparison_v2/shared_tools.py "raw.githubusercontent.com"
[7]: https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/langchain_agent.py "SeekFlow/benchmarks/fair_comparison_v2/langchain_agent.py at main · WYZAAACCC/SeekFlow · GitHub"
[8]: https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/crewai_agent.py "SeekFlow/benchmarks/fair_comparison_v2/crewai_agent.py at main · WYZAAACCC/SeekFlow · GitHub"
[9]: https://github.com/WYZAAACCC/SeekFlow/blob/main/benchmarks/fair_comparison_v2/rescore.py "SeekFlow/benchmarks/fair_comparison_v2/rescore.py at main · WYZAAACCC/SeekFlow · GitHub"
[10]: https://reference.langchain.com/python/langchain-openai/chat_models/base/BaseChatOpenAI/extra_body?utm_source=chatgpt.com "extra_body | langchain_openai | LangChain Reference"
