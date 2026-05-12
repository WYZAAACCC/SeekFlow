# Issue #11: 成本追踪

**优先级**: P2  
**状态**: 待开始  
**分类**: enhancement  
**Triage**: ready-for-agent  
**Phase**: 3 — 开发者体验  
**依赖**: 无 — 可立即开始  
**覆盖用户故事**: #14 (实时成本追踪)

---

## 背景

DeepSeek V4 的定价模型：
- V4-Pro: ¥1.74/M 输入, ¥3.48/M 输出 ($0.24/$0.48)
- V4-Flash: ¥0.14/M 输入, ¥0.28/M 输出 ($0.02/$0.04)
- Cached tokens: ¥0.028/M 输入（Pro 的 1.6%）
- 不同模型的 cached 定价不同

当前库仅在 `usage` dict 中返回原始 token 数，不做费用计算。用户需要自己理解不同模型、cached token 的定价差异来估算费用。这导致：
1. 调试阶段不知道一次对话花了多少钱
2. 无法按 session/tool/model 维度分析成本
3. 无法设置成本预算告警

## 任务

1. 新建 `deepseek_toolkit/cost.py`
2. 实现定价表 `PRICING`：
   ```python
   PRICING = {
       "deepseek-v4-pro": {"input": 1.74, "output": 3.48, "cached_input": 0.028, "unit": "CNY/1M"},
       "deepseek-v4-flash": {"input": 0.14, "output": 0.28, "cached_input": 0.002, "unit": "CNY/1M"},
   }
   ```
3. 实现 `CostTracker` 类：
   - `record(model, usage)` — 记录一次 API 调用的费用（自动查定价表）
   - `total_cost` — 累计费用
   - `by_session / by_model / by_tool` — 按维度统计数据
   - `reset()` — 清零
4. 提供回调机制：`on_cost_update(callback: Callable[[CostUpdate], None])`
5. 集成到 `ToolRuntime`：每个 API 调用后自动记录成本
6. `runtime.stats` 属性展示累计成本

## 验收标准

- [ ] V4-Pro 1M prompt + 500K completion 费用计算正确：1.74 + 3.48*0.5 = 3.48
- [ ] V4-Flash 费用按 flash 定价计算
- [ ] Cached tokens 按 cached 定价计算
- [ ] `by_model` 维度统计正确
- [ ] `CostTracker.reset()` 清零所有统计
- [ ] 未识别模型回退到 Pro 定价（安全默认）
- [ ] 新增 ≥8 个测试

## 测试建议

- 测试各种模型和 token 组合的费用计算
- 测试 cached token 的费用
- 测试未知模型回退
- 测试回调触发
- 测试 reset 行为
- 测试大数值精度（避免浮点误差）
- 参考现有 usage 处理：[src/deepseek_toolkit/types.py](../../src/deepseek_toolkit/types.py)
