# P1-1: AgentRuntimeSaver — DTK agent 接入完整数据采集

**状态**: `ready-for-agent`
**优先级**: P1
**类型**: AFK

## Parent

[PRD: 竞品差距收敛](../PRD-benchmark-gap-closure.md)

## What to build

将 `comprehensive_saver.py` 中的 `RuntimeSaver` 集成进 `deepseek_toolkit_agent.py`，使 DTK agent 与 LangChain/CrewAI 一样保存完整的运行数据。

当前 DTK agent 使用自己的 `DTKAgentReport` dataclass 保存摘要数据，但缺少：
- 每步的 token 消耗时间线（per-step breakdown）
- 每个工具调用的延迟和结果（name, args, result, elapsed_ms per call）
- 完整的消息历史（message_trace.json）
- 与 LangChain/CrewAI 统一的 summary.json 格式

改动范围仅在 `deepseek_toolkit_agent.py` 的 `run_dtk_agent()` 函数内部：

1. 导入 `RuntimeSaver`, `get_framework_features`
2. Agent 启动时初始化 `RuntimeSaver("DeepSeekToolkit", agent_type, MODEL)`
3. 在 streaming/non-streaming 路径中插入记录点：
   - `begin_step()` — 每轮模型调用开始
   - `record_model_call()` — 模型响应完成（content, reasoning, finish_reason）
   - `record_token_usage()` — token 统计（从 `event.usage` 或 `result.usage` 提取）
   - `record_tool_call()` — 每个工具执行完成
4. Agent 结束时 `finish()` + `save()` 到 `output/runtime_dumps/DeepSeekToolkit/{agent_type}/`

输出三件套：
- `runtime_dump.json` — 完整运行数据
- `message_trace.json` — 消息历史（截断 >2000 字符的内容）
- `summary.json` — 快速对比摘要（与 LangChain/CrewAI 格式一致）

## Acceptance criteria

- [ ] 运行 DTK financial agent 后在 `output/runtime_dumps/DeepSeekToolkit/financial/` 下存在 3 个 JSON 文件
- [ ] `summary.json` 中 `framework` 字段为 `"DeepSeekToolkit"`，格式与 LangChain/CrewAI 一致
- [ ] `runtime_dump.json` 中 steps 数组非空，每个 step 包含 `model_call_latency_ms`
- [ ] `message_trace.json` 包含完整的消息历史（user、assistant、tool 消息）
- [ ] 更新 `compare_agents.py` 使其读取 DTK 的 runtime_dump 数据
- [ ] `runtime_comparison.json` 的 `total_runs` 从 8 变为 12（增加 DTK 的 4 个 agent）

## Test suggestions

- 集成测试：跑 DTK financial agent，断言 `output/runtime_dumps/DeepSeekToolkit/financial/summary.json` 存在且 `success: true`
- 集成测试：验证 `summary.json` 的 `total_latency_ms > 0` 且 `total_tokens > 0`

## Blocked by

- [P0-1: CostTracker 修复](P0-1-cost-tracker-fix.md)（确保 summary 中 `total_cost_cny > 0`）
