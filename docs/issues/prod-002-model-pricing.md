# prod-002: 模型感知定价表 — 根据模型名自动计算成本

**状态**: 待开始
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

当前 Agent._result_from_runtime() 硬编码 V4-pro 价格：prompt ¥1.74/M, cached ¥0.028/M, completion ¥3.48/M。切换模型时成本算错。DeepSeek 有多个模型（chat, V3, V4-pro, V4-flash），价格和上下文窗口都不同。

## 任务

1. 创建 `PRICING` 字典：model_name → {input, cached_input, output, max_context}
2. 至少覆盖：deepseek-chat, deepseek-v3, deepseek-v4-pro, deepseek-v4-flash
3. _result_from_runtime() 根据 self._model 查表计算
4. 找不到模型时用默认价格 + 发出 warning
5. max_context_tokens 默认值根据模型自动设定（chat=128K, v4-pro=1M）

## 验收标准

- [ ] Agent(model="deepseek-chat") 按 chat 价格计算成本
- [ ] Agent(model="deepseek-v4-pro") 按 v4-pro 价格计算成本
- [ ] 未知模型名发出 warning 并使用默认价格
- [ ] max_context_tokens 根据模型自动调整

## 测试建议

- 单元测试：不同模型的 cost 计算结果不同
- 单元测试：未知模型 fallback 到默认价格

## 分类: ready-for-agent
