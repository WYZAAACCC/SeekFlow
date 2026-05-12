# v3-033: Reflection 模式 — Agent 自我评估并迭代改进输出

**状态**: 已完成
**优先级**: P2
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景
Reflection 是 SOTA Agent 模式之一：生成→自我评估→改进。LangChain 和 CrewAI 均无原生 Reflection 支持。

## 任务
1. Agent.reflect(task, max_refinements=2): 生成→critic评估→改进循环
2. 复用 Agent.run() 和 critic agent

## 验收标准
- [x] reflect() 至少执行一轮 self-critique
- [x] 当 critic 返回 "无需改进" 时停止

## 分类: ready-for-agent
