# polish-005: 真实生产场景端到端测试

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

现有测试都是单元测试 + 简单 E2E。缺少完整的、多步骤、多工具的生产级场景测试。这是发现集成问题的最后一道防线。

## 任务

写 3 个完整场景，每个跑 20 次：

### 场景A：财务分析 Agent
```
步骤: 读取 financial_report.json
     → 计算 12 项财务比率（毛利率/净利率/ROE/资产负债率/流动比率/速动比率/
        利息保障倍数/存货周转率/应收账款周转率/总资产周转率/营收增长率/净利润增长率）
     → web_search "字节跳动 2025 行业对比"
     → 生成分析报告
验证: 12 项比率全部有值、报告 > 500 字、有行业对比
```

### 场景B：多 Agent 研究团队
```
Crew(Sequential):
  researcher → 搜索"2025 AI 芯片市场趋势"，输出 3 个关键发现
  analyst   → 基于研究结果，分析对中国半导体行业的影响
  writer    → 将分析整理为 300 字商业简报
验证: 3 个 Task 都成功、简报 > 200 字、包含数据引用
```

### 场景C：条件工作流
```
StateGraph:
  plan → execute → evaluate
           ↑         │
           │  score<80│ score≥80
           └─retry────┘        → finalize
验证: 20 次运行中至少 1 次触发 retry 循环、最终成功率 > 90%
```

## 验收标准

- [ ] 场景A 20 次运行，12 项比率准确率 > 90%
- [ ] 场景B 20 次运行，上下文传递正确率 100%
- [ ] 场景C 条件路由正确率 100%
- [ ] 无 Python 异常逃逸到测试框架
- [ ] 平均每场景成本 < ¥0.50

## 测试建议

- 全部使用真实 DeepSeek API
- 记录每次运行的成本、延迟、token 用量
- 失败时保存完整 AgentResult.diagnostics
- 所有结果写入 `output/polish/production/{scenario}/` 目录
- 最终生成一份 `output/polish/REPORT.md` 汇总所有 5 个 polish issue 的结果

## 分类: ready-for-agent
