# v3-031: ReAct 模式 — 显式 Thought→Action→Observation 循环

**状态**: 已完成
**优先级**: P2
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景
Anthropic "Building Effective Agents" 明确 ReAct 是最基础的 Agent 模式。DTK 的 ToolRuntime.chat() 内建多步循环但 Agent 未将其包装为显式 ReAct 接口。SOTA 趋势是显式展示 Thought→Action→Observation 循环而非黑盒执行。

## 任务
1. Agent.react(task) 方法：增强 prompt 引导模型输出 Thought/Action/Observation
2. 复用 ToolRuntime 的多步循环
3. 支持 max_iterations 参数

## 验收标准
- [x] react() 成功执行多步推理任务
- [x] 输出包含完整的推理链

## 分类: ready-for-agent
