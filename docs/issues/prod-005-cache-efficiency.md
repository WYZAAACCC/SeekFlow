# prod-005: 缓存效率优化 — 主动引导用户最大化 Prompt Cache 命中

**状态**: 待开始
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

DeepSeek cached tokens ¥0.028/M vs uncached ¥1.74/M — 62 倍价差。CacheSentinel 检测前缀变化但只警告。生产环境需要：(1) 缓存命中率百分比 (2) 系统提示变更前的破坏警告 (3) 消息排序建议以保持前缀稳定。

## 任务

1. AgentResult 增加 `cache_hit_rate: float`（cached_tokens/prompt_tokens 百分比）
2. Agent 增加 `_last_system_hash` 跟踪系统提示是否变化
3. _build_system_prompt() 变化时发出 UserWarning："系统提示变更，缓存将失效"
4. 为 Agent 添加 `cache_stats` 属性：累计缓存 tokens、累计请求数、平均命中率
5. 工具调用结果被截断时，输出可能无法被缓存——记录并提示

## 验收标准

- [ ] AgentResult.cache_hit_rate 显示为百分比（如 87.3%）
- [ ] 修改 agent.role 后再 run() → 发出缓存失效警告
- [ ] agent.cache_stats 提供跨 run() 的累积统计

## 测试建议

- 第一次 run() 缓存命中率低，第二次相同 run() 缓存命中率高
- 修改系统提示后缓存命中率归零

## 分类: ready-for-agent
