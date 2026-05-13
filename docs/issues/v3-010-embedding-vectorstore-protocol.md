# v3-010: Embedding + VectorStore Protocol — callable 接口桥接

**状态**: 待开始
**优先级**: P2
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)
**阻塞**: v3-009

---

## 背景

当文档总量超过 1M token 时，全量导入上下文不再可行，需要检索增强（RAG）。DTK 不实现 chunk→embed→retrieve 管道（1M 上下文使大部分场景不需要），但需要提供与外部 embedding 函数和 vector store 对接的能力。

策略同上：用 Python Protocol 定义最小接口，不引入任何外部依赖。用户传入的任何 callable 或对象只要满足协议就能工作。

## 任务

1. 创建 `seekflow/compat/embeddings.py`：
   - 定义 `EmbeddingFunction = Callable[[str], list[float]]` 类型别名
   - `DeepSeekAgent.use_embedding(fn: EmbeddingFunction)` 配置 embedding 函数

2. 创建 `seekflow/compat/vector_stores.py`：
   - 定义 `VectorStoreLike` Protocol：
     - `search(query: str | list[float], top_k: int = 5) -> list[DocumentLike]`
   - `DeepSeekAgent.use_vector_store(store: VectorStoreLike)` 配置 vector store

3. Agent 在执行任务时：
   - 如果配置了 vector store 和 embedding function → 对用户 query 做 embedding → vector store.search() → 检索结果注入上下文
   - 如果只配置了 vector store（无 embedding function）→ 直接将 query 字符串传给 search()

## 验收标准

- [ ] Agent 配置 embedding + vector store 后，query 自动触发检索
- [ ] 检索结果以 `DocumentLike` 列表形式注入 Agent 上下文
- [ ] 未配置 vector store 时 Agent 正常运行（不报错）
- [ ] 自定义 embedding 函数（如返回固定向量的 mock）正常工作

## 测试建议

- 单元测试：Mock EmbeddingFunction + Mock VectorStoreLike → 验证调用链
- 集成测试：真实 Chroma/Qdrant client → 验证检索结果格式
- 边界测试：embedding 函数返回空向量、vector_store.search() 抛出异常

## 分类

**ready-for-agent** — Protocol 定义简单，核心逻辑是检索结果→上下文的注入。但 Chroma 等真实 vector store 的集成测试可能需要额外环境配置。
