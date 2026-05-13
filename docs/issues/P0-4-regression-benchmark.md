# P0-4: 端到端回归 — 重跑 12-agent benchmark 验证全部修复

**状态**: `ready-for-agent`
**优先级**: P0
**类型**: AFK

## Parent

[PRD: 竞品差距收敛](../PRD-benchmark-gap-closure.md)

## What to build

在 P0-1、P0-2、P0-3、P1-1、P2-1 全部完成后，重新运行完整的 12-agent benchmark，验证所有修复生效且无回归。

这是整个 PRD 的验收关卡。对比 baseline（2026-05-10 的首次 benchmark 数据）检查以下维度：

**必须达标的指标：**

| 指标 | Baseline | 目标 |
|------|----------|------|
| DTK agent 成功率 | 100% | 保持 100% |
| DTK cost 显示 | CNY 0.000000 | CNY > 0（每个 agent） |
| DTK runtime_dumps 文件 | 0 | 12 个（4 agent × 3 JSON） |
| thinking_mode="enabled" 多轮 | 400 报错 | 正常运行或自动降级 + warning |
| web_search 超时 | 全部超时 | 至少 1 个 agent 的搜索成功（如有 Bing key） |
| DTK 平均 features/agent | 10 | ≥ 10（不减少） |

**对比报告检查：**
- `comparison_report.md` 中 DTK 列 cost 不为 CNY 0.000000
- `comparison_report.md` 中 DTK 列包含 runtime_dump 路径
- `runtime_comparison.json` 中 `total_runs: 12`（DTK 4 + LangChain 4 + CrewAI 4）

## Acceptance criteria

- [ ] 12 个 agent 全部运行成功，无报错
- [ ] DTK 的 4 个 agent cost 全部 > 0
- [ ] `output/runtime_dumps/SeekFlow/` 下有 4 个子目录，每个含 3 个 JSON
- [ ] `runtime_comparison.json` 中 `total_runs` 为 12
- [ ] `comparison_report.md` 生成成功，包含完整的 3 框架 × 4 agent 对比
- [ ] `thinking_mode` 相关测试通过（显式传 enabled/disabled 均正常）
- [ ] Baseline 对比：DTK 平均延迟无明显退化（< baseline × 1.3）

## Test suggestions

- 运行 `python benchmarks/agents_comparison/compare_agents.py` 完整流程
- 检查退出码为 0
- 脚本化验证：检查所有 runtime_dumps 文件存在、cost > 0、success = true

## Blocked by

- [P0-1: CostTracker 修复](P0-1-cost-tracker-fix.md)
- [P0-2: ThinkModeGuard](P0-2-think-mode-guard.md)
- [P0-3: ThinkingMode 默认策略](P0-3-thinking-mode-default-strategy.md)
- [P1-1: AgentRuntimeSaver](P1-1-agent-runtime-saver.md)
- [P2-1: SearchProvider 抽象](P2-1-search-provider-abstraction.md)
