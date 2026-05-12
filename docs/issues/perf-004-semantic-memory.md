# perf-004: 语义记忆升级 — TF-IDF + LLM 自动提取 + 重要性评分

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

当前 AgentMemory 使用 char-trigram 向量进行语义检索，精度有限且无重要性评分。CrewAI 的 Memory 使用 LanceDB + LLM 编码 + 复合评分（语义相似度 + 时间衰减 + 重要性）。DTK 需要在不引入 LanceDB 重依赖的前提下达到可用精度。

## 任务

1. 添加可选 numpy/sklearn 支持（try/except ImportError fallback）
2. 使用 TF-IDF 替代 char-trigram（numpy 可用时）
3. LLM 自动记忆提取：Agent 空闲时调用小模型总结对话要点
4. 时间衰减：`score = sim * 0.6 + importance * 0.3 + recency * 0.1`
5. 记忆压缩：相似记忆自动合并（consolidation_threshold=0.85）
6. 后台写入队列（memory.drain_writes）：不阻塞 Agent 执行

## 验收标准

- [ ] TF-IDF 检索精度显著优于 char-trigram（同一 query 的 top-1 命中率）
- [ ] 记忆时间衰减：7 天前的记忆得分低于当天的相同记忆
- [ ] 相似记忆自动合并：两条相似度 > 0.85 的记忆合并为一条
- [ ] 后台写入不阻塞 Agent.run()

## 测试建议

- 单元测试：TF-IDF vs char-trigram 检索精度对比
- 单元测试：时间衰减计算公式
- 单元测试：记忆合并逻辑
- 边界测试：numpy 不可用时退化为 char-trigram

## 分类: ready-for-agent
