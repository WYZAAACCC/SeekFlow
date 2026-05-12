# polish-001: StateGraph 复杂场景稳定性测试

**状态**: 待开始
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

StateGraph 是 DTK 最新（v0.1）、最脆弱的模块。目前只有 5 个单元测试，覆盖了线性图、channel append、条件边、interrupt/resume 的基础路径。但生产环境中的真实图工作流比这复杂得多——嵌套、循环、异常处理——这些都没有测试。

## 任务

1. 写 3 个复杂场景的 E2E 测试：

   **场景A：质量循环工作流**
   ```
   research → analyze → quality_check
                           ├── score >= 80 → write → done
                           └── score < 80  → loop back to analyze (max 3 loops)
   ```
   - 每个节点是一个真实 Agent
   - quality_check 返回 JSON `{"score": N, "feedback": "..."}`
   - 条件边根据 score 路由
   - 跑 20 次，验证平均循环次数 ≤ 3

   **场景B：嵌套图**
   ```
   orchestrator → [parallel: researcher, analyst, writer] → merge
   ```
   - orchestrator 是主图节点
   - 它内部调用另一个 StateGraph（子图）做并行研究
   - 验证子图状态正确隔离

   **场景C：interrupt + 异常恢复**
   ```
   step1 → human_approval(interrupt) → step2
              └── approval 超时 30s → fallback_node
   ```
   - human_approval 发出 Interrupt
   - 30s 内未收到 Command(resume=...) → 自动路由到 fallback_node
   - 验证超时后状态正确

2. 每个场景跑 20 次，收集统计：
   - 成功率（期望 > 95%）
   - 平均延迟
   - 条件边的路由准确率（期望 100%）
   - 状态污染（跨运行的状态泄漏，期望 0）

## 验收标准

- [ ] 场景A 20 次运行，条件路由 100% 正确
- [ ] 场景B 子图状态与主图完全隔离
- [ ] 场景C interrupt 超时后正确 fallback
- [ ] 所有场景成功率 > 95%

## 测试建议

- 使用真实 DeepSeek API（不用 mock——这里是测集成稳定性）
- 每个场景单独一个测试函数
- 失败时打印完整 state 快照便于调试
- 结果写入 `output/polish/stategraph/` 目录

## 分类: ready-for-agent
