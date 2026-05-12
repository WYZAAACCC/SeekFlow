# prod-012: FIM Agent — 代码补全 Agent 集成

**状态**: 待开始
**优先级**: P2
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

DeepSeek 支持 FIM（Fill-in-the-Middle）补全，fim.py 有完整的 FIM client。但 Agent 层零集成——不能用 FIM 做代码补全、文档生成、模板填充。这是 DeepSeek 的独占 API 能力，LangChain/CrewAI 完全不支持。

## 任务

1. 创建 `CodeAgent`（继承 DeepSeekAgent）预设
2. 提供 `agent.complete(prefix, suffix) -> str` 方法调用 FIM API
3. 提供 `agent.fill_template(template, variables) -> str` 使用 FIM 填充模板
4. 支持 `fim_temperature` 独立于 chat temperature

## 验收标准

- [ ] `CodeAgent().complete("def add(a,b):\n    ", "\n    return result")` 返回代码补全
- [ ] FIM 补全结果正确返回

## 测试建议

- Mock FIM API → 验证 Agent 调用路径
- E2E：真实 DeepSeek FIM API 补全简单函数

## 分类: ready-for-agent
