# SeekFlow 竞品差距收敛 — PRD

**日期:** 2026-05-10
**来源:** SeekFlow vs LangChain vs CrewAI 三方benchmark

---

## 背景

2026年5月完成了一轮完整的三方agent框架对比benchmark：使用相同的DeepSeek API（deepseek-v4-pro），相同的4个agent类型（财务分析/投资分析/数据分析/影视策划），相同的4个工具（read_file/web_search/calculate/save_result），对比SeekFlow、LangChain 1.2.18、CrewAI 1.14.4的表现。

### Benchmark 关键数据

```
                    SeekFlow    LangChain        CrewAI
平均延迟            179.8s             312.8s           211.0s
每agent功能数        10                 5                6
DeepSeek专属功能      12                 0                0
agent成功率          100%               100%             100%
```

### 发现的问题

1. **Cost tracking始终显示CNY 0.000000** — DTK的CostTracker在所有4个agent运行中都没有正确计算费用，而LangChain正常计费（CNY 0.013~0.104/agent）
2. **reasoning_content多轮传递bug** — 当thinking mode启用时，DeepSeek API要求将前一轮的reasoning_content原样传回，ToolRuntime未正确处理，导致多轮工具调用场景下400报错。benchmark靠`thinking_mode="disabled"`绕过
3. **RuntimeSaver未接入DTK agent** — LangChain和CrewAI的agent都通过comprehensive_saver保存了完整的runtime_dump.json、message_trace.json、summary.json，DTK agent没有接入
4. **Web search在国内网络不可用** — DuckDuckGo在CN网络下超时，所有3个框架均受影响。作为面向中国开发者的库，应提供国内搜索引擎支持
5. **Thinking mode默认策略缺失** — `thinking_mode`参数默认`None`，依赖模型默认行为。deepseek-v4-pro默认启用thinking，导致多轮场景直接报错

### 竞品差距确认

benchmark验证了DTK在DeepSeek专属功能上的绝对优势（12 vs 0），但也暴露了工程化层面的不足。12个专属功能是有价值的护城河，但上述5个问题会严重影响新用户的首次体验。

---

## 目标

**一句话：收敛benchmark暴露的工程差距，让DTK在多轮agent场景下开箱即用。**

具体目标：

1. **修复CostTracker** — Cost tracking正确输出CNY费用
2. **修复reasoning_content传递** — 多轮对话中自动处理reasoning_content回传，消除400错误
3. **RuntimeSaver接入DTK agent** — DTK agent的输出数据采集能力不低于LangChain/CrewAI
4. **搜索后端可配置** — 支持国内可用的搜索引擎
5. **Thinking mode智能默认** — 根据单轮/多轮场景自动选择合适的默认值

---

## 非目标

本PRD**不涉及**：

- 不新增DeepSeek专属功能（12个已足够，当前重点是稳定性）
- 不改变ToolRuntime的公开API签名（向后兼容）
- 不添加新的agent类型或工具
- 不修改benchmark数据或对比框架
- 不涉及前端/UI
- 不涉及MCP协议变更

---

## 用户故事

### CostTracker修复

1. 作为使用DTK构建agent的开发者，我希望`CostTracker.record()`返回正确的CNY费用，以便我能实时监控API消费
2. 作为运行批量benchmark的测试者，我希望每个agent运行后能看到准确的cost，以便在不同框架之间做公平对比
3. 作为生产环境运维，我希望cost累计值准确反映实际API消费，以便做预算管理

### reasoning_content传递修复

4. 作为使用thinking mode构建多轮agent的开发者，我不希望因为忘记传递reasoning_content而收到400错误
5. 作为想使用`thinking_mode="enabled"`的用户，我希望DTK自动处理reasoning_content的保存和回传，无需我手动管理
6. 作为在单轮场景下使用thinking mode的开发者，我希望行为不变，thinking mode正常工作

### RuntimeSaver接入

7. 作为运行benchmark的测试者，我希望DTK agent与LangChain/CrewAI一样保存完整的runtime_dump、message_trace和summary，以便统一分析
8. 作为调试agent行为的开发者，我希望看到每一步的token消耗、工具调用延迟和模型响应内容
9. 作为对比不同框架表现的架构师，我希望DTK的数据采集格式与comprehensive_saver完全兼容

### 搜索后端可配置

10. 作为中国开发者，我希望web_search工具在国内网络环境下可用，而不是每次都超时
11. 作为库的维护者，我希望搜索后端是可插拔的，以便未来支持更多搜索引擎
12. 作为海外用户，我仍然希望使用DuckDuckGo等国外搜索引擎

### Thinking mode智能默认

13. 作为新用户，我不需要知道thinking mode的细节就能让agent正常工作
14. 作为高级用户，我仍然可以显式设置`thinking_mode="enabled"|"disabled"|"max"`来覆盖默认行为
15. 作为调试问题的开发者，我希望当thinking mode因为多轮场景被自动降级时能看到warning

---

## 核心功能

### 功能1：CostTracker修复

**问题诊断**：CostTracker.record()可能在以下环节出错：
- 从API响应中提取token usage的路径不正确
- 模型名称与定价表匹配失败
- 累计值使用了错误的数据结构

**修复方向**：
- 对齐LangChain的token提取方式（从`usage_metadata`或`usage`字段提取）
- 确保pricing table中包含`deepseek-v4-pro`的正确价格（input: 1.74 CNY/1M tokens, output: 3.48 CNY/1M tokens）
- 在benchmark agent中验证：连续4个agent运行后cost > 0

### 功能2：ThinkModeGuard

**新增内部组件**，对用户透明。

```
ThinkModeGuard
  - check(messages) -> bool          # 检测是否需要传递reasoning_content
  - sanitize(messages) -> list[dict] # 修复消息列表，确保reasoning_content完整
  - should_downgrade(messages, thinking_mode) -> str | None  # 判断是否需要降级
```

**行为逻辑**：
1. `chat()`调用前自动扫描消息列表
2. 如果发现assistant消息包含`reasoning_content`，确保其格式完整
3. 如果thinking mode启用但消息列表存在不兼容情况（如外部传入的消息缺少reasoning_content），
   - 自动降级为`thinking_mode="disabled"`
   - 发出`UserWarning("thinking_mode downgraded to 'disabled': reasoning_content missing from prior assistant messages")`
4. 如果用户显式传入`thinking_mode`，尊重用户选择，不降级（但会在出错时给出清晰的错误信息）

### 功能3：AgentRuntimeSaver

**新增适配层**，桥接DTK agent和comprehensive_saver。

与LangChain/CrewAI agent已有的RuntimeSaver保持接口一致：

```python
from comprehensive_saver import RuntimeSaver, FrameworkFeatures, get_framework_features

# 集成方式（在 run_dtk_agent() 内部）
saver = RuntimeSaver("SeekFlow", agent_type, MODEL)
saver.start(task=task, system_prompt=system_prompt)
saver.set_features(get_framework_features("SeekFlow"))

# 每步记录
saver.begin_step()                        # 开始新步骤
saver.record_model_call(step, ...)        # 模型调用完成
saver.record_token_usage(step, usage, cost)  # token统计
saver.record_tool_call(step, name, args, result, ok, elapsed)  # 工具调用

# 结束时保存
saver.finish(final_output=text, error=None)
saver.save()  # -> output/runtime_dumps/SeekFlow/{agent_type}/
```

保存到 `output/runtime_dumps/SeekFlow/{agent_type}/` 的三件套：
- `runtime_dump.json` — 完整运行数据
- `message_trace.json` — 消息历史
- `summary.json` — 快速对比摘要

### 功能4：SearchProvider 抽象

```python
# 搜索后端注册
from seekflow.tools import SearchProvider, DuckDuckGoProvider, BingProvider

# 自动选择（默认）
@tool(search_provider="auto")  # CN网络 → Bing, 海外 → DuckDuckGo
def web_search(query: str) -> str: ...

# 显式指定
@tool(search_provider="bing")
def web_search(query: str) -> str: ...
```

**优先级**：DuckDuckGo（免费，无需API key） > Bing（国内可用，需API key） > 用户自定义

### 功能5：ThinkingMode 默认策略

修改`_apply_thinking_mode()`的行为：

| 场景 | 用户传参 | 实际行为 |
|------|---------|---------|
| 单轮（messages只有system+user） | None | `"enabled"` |
| 多轮（messages包含assistant+tool） | None | `"disabled"` + UserWarning |
| 任意 | `"enabled"` | 尊重用户，启用ThinkModeGuard |
| 任意 | `"disabled"` | 尊重用户，不做任何处理 |
| 任意 | `"max"` | 尊重用户，启用ThinkModeGuard |

---

## 实现决策

### 模块修改清单

| 模块 | 类型 | 影响范围 |
|------|------|---------|
| `ThinkModeGuard` | 新增 | `runtime.py` 内部，不影响公开API |
| `CostTracker` | 修改 | `cost.py`，修正record逻辑 |
| `AgentRuntimeSaver` | 新增 | `seekflow_agent.py`，benchmark专用 |
| `SearchProvider` | 新增 | `tools.py`，新增抽象+内置provider |
| `_apply_thinking_mode` | 修改 | `runtime.py`，增加多轮检测逻辑 |

### 向后兼容

- 所有现有公开API签名不变
- `thinking_mode`参数的合法值不变（`None`, `"enabled"`, `"disabled"`, `"max"`）
- 仅`None`（默认）的行为从"不传参"变为"智能选择"
- `CostTracker.record()`签名不变，仅修复内部逻辑
- `@tool`装饰器新增可选参数`search_provider`，默认`"auto"`

### 数据格式

RuntimeSaver输出的summary.json格式已在comprehensive_saver中定义，DTK的输出与LangChain/CrewAI完全一致：

```json
{
  "framework": "SeekFlow",
  "agent_type": "financial",
  "success": true,
  "total_latency_ms": 162018,
  "total_cost_cny": 0.052,
  "total_tokens": 45210,
  "prompt_tokens": 32000,
  "completion_tokens": 12210,
  "cached_tokens": 8500,
  "reasoning_tokens": 0,
  "steps": 5,
  "tool_calls": 17,
  "error": null,
  "features_available": ["thinking_mode_param", "balance_query", ...],
  "features_missing": []
}
```

---

## 测试决策

### 测试原则

- 仅测试外部行为，不测试实现细节
- 优先端到端测试（agent跑通 → 检查输出文件）
- 单元测试覆盖边界情况（reasoning_content缺失/损坏、cost为0、搜索超时）

### 需测试的模块

| 模块 | 测试类型 | 参考 |
|------|---------|------|
| ThinkModeGuard | 单元测试 | 参考 `tests/test_thinking.py` |
| CostTracker | 单元测试 + 集成测试 | 参考LangChain的cost计算验证 |
| AgentRuntimeSaver | 集成测试 | 跑完agent检查output/runtime_dumps文件存在性 |
| SearchProvider | 单元测试 | mock网络请求，验证provider切换逻辑 |
| ThinkingMode默认 | 单元测试 | 参考 `tests/test_thinking.py` 扩展 |

### 验收测试

1. 运行完整的12 agent benchmark，验证：
   - DTK cost > 0（不再是CNY 0.000000）
   - `output/runtime_dumps/SeekFlow/`下有4个agent类型×3个JSON文件 = 12个文件
   - 所有agent成功完成，0错误
2. 显式传入`thinking_mode="enabled"`运行多轮agent，验证ThinkModeGuard生效（不报400）
3. CN网络下运行web_search，不再超时

---

## 边界情况

### ThinkModeGuard
- assistant消息中`reasoning_content`字段缺失 vs 为None vs 为空字符串的处理
- 混合消息列表：部分assistant有reasoning_content，部分没有
- 外部通过API传入的消息（非DTK session生成的）缺少reasoning_content
- reasoning_content被意外截断或编码损坏

### CostTracker
- API返回的usage字段结构与OpenAI不完全一致（DeepSeek的差异）
- 模型不在pricing table中时的fallback
- 并发调用时累计值的线程安全
- cached_tokens的计算边界（prompt_tokens_details可能不存在）

### AgentRuntimeSaver
- agent中途异常退出时仍能保存已收集的数据
- 超长tool result的截断（当前2000字符限制是否合理）
- 空步骤（模型直接返回final，没有tool call）的处理
- 中文字符在JSON序列化中的编码

### SearchProvider
- "auto"模式下网络检测失败时的fallback
- Bing API key未配置时的fallback链
- 搜索超时不应阻塞agent执行（返回"搜索不可用"并继续）

### ThinkingMode默认策略
- 单轮/多轮的判断依据：仅根据messages中包含assistant+tool消息判断
- 用户显式传`thinking_mode="enabled"`但ThinkModeGuard检测到不兼容 → 不降级，信任用户
- reasoning模型（deepseek-reasoner）的thinking行为可能与v4-pro不同

---

## 开发阶段

### Phase 1：致命bug修复（P0，预计1-2天）

| 任务 | 优先级 | 验证方式 |
|------|--------|---------|
| CostTracker修复 | P0 | 单元测试 + agent运行后cost > 0 |
| ThinkModeGuard实现 | P0 | 单元测试 + `thinking_mode="enabled"`多轮agent不报400 |
| ThinkingMode默认策略 | P0 | 默认参数下多轮agent成功运行 |

### Phase 2：数据采集补齐（P1，预计1天）

| 任务 | 优先级 | 验证方式 |
|------|--------|---------|
| AgentRuntimeSaver集成到DTK agent | P1 | benchmark后检查runtime_dumps文件 |
| DTK runtime_comparison.json参与聚合 | P1 | comparison报告包含DTK的详细数据 |

### Phase 3：体验提升（P2，预计1天）

| 任务 | 优先级 | 验证方式 |
|------|--------|---------|
| SearchProvider抽象 + Bing支持 | P2 | CN网络下web_search不超时 |
| benchmark agent中web_search切换为auto | P2 | 端到端benchmark通过 |

### Phase 4：全面验证（预计半天）

| 任务 | 验证方式 |
|------|---------|
| 重新运行完整12-agent benchmark | 所有指标达标 |
| 生成新版comparison_report.md | DTK列数据完整（含cost + runtime_dump路径） |
| 与Phase 0 baseline对比 | 回归检查 |

---

## 进一步说明

### 关于"DTK的定位"

这次benchmark验证了一个核心判断：**SeekFlow的价值不在于"比LangChain做得更多"，而在于"LangChain做不了的事"。**

12个DeepSeek专属功能中，balance query、error classification、JSON repair、rate limit awareness这4个是生产环境刚需。LangChain和CrewAI的provider-agnostic架构注定了它们不会提供这些能力。

但这次benchmark也暴露了DTK的短板：**工程化细节不如成熟框架**。Cost tracking、数据采集、多轮兼容性这些"无聊但重要"的事情，LangChain做得更好。Phase 1-2就是要拉平这些差距。

### 关于benchmark的价值

建议将benchmark作为DTK的回归测试套件保留。每次大版本发布前跑一次完整的12-agent benchmark，对比baseline数据，确保：
- 性能不退化（延迟 < baseline × 1.2）
- 功能不减少（features exercised ≥ 10）
- 数据采集完整（runtime_dumps文件数 = 12）
