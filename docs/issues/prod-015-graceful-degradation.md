# prod-015: 优雅降级 — 过载时自动切换模型或降低参数

**状态**: 待开始
**优先级**: P2
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

DeepSeek API 过载时（503/高延迟），生产环境不能干等。需要自动降级：切换到更快/更便宜的模型，或降低 max_tokens 以加速响应。FallbackChain 骨架存在但未实现具体策略。

## 任务

1. Agent.__init__ 增加 `fallback_models: list[str] | None` 参数
2. 发生 503 或延迟超过 `degradation_threshold` 时自动切换到下一个模型
3. 支持 `degradation_threshold: float = 10.0`（秒）
4. AgentResult 增加 `model_used: str`（记录实际使用的模型）
5. 降级时发出 warning 日志

## 验收标准

- [ ] 主模型超时 → 自动切换 fallback 模型
- [ ] AgentResult.model_used 显示实际使用的模型
- [ ] 所有 fallback 模型都不可用时返回错误

## 测试建议

- Mock 主模型超时 → 验证自动切换
- Mock 所有模型不可用 → 验证错误处理

## 分类: ready-for-agent
