# v3-009: Document Protocol — 接受 LangChain Document / plain text / dict

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

---

## 背景

LangChain 有 800+ document loader 集成（PDF、网页、数据库、Office 文档等），这是社区 5 年积累的结果。DTK 不可能、也不应该重复造这些 loader。

但 DTK 可以**接受** LangChain 的 Document 输出。策略是：用 Python Protocol 定义 `DocumentLike` 接口，任何有 `page_content` 和 `metadata` 属性的对象都能被 DTK Agent 处理。这样开发者可以继续用 LangChain 的 loader 加载文件，然后把 Document 传给 DTK Agent。

这不需要引入 LangChain 作为运行时依赖——Python 的 duck typing 天然支持。

## 任务

1. 创建 `seekflow/compat/documents.py`
2. 定义 `DocumentLike` Protocol：
   - `page_content: str`
   - `metadata: dict`
3. 实现 `to_agent_text(docs: list[DocumentLike]) -> str` 函数：
   - 将 Document 列表转换为 Agent 可直接消费的文本格式
   - 每个 Document 格式化为 `## {metadata.get('source', '文档')}\n\n{page_content}\n`
4. 实现 `validate_document(obj)` 函数：
   - 检查对象是否满足 DocumentLike 协议
   - 不满足时给出清晰的修复建议
5. 支持传入 `dict`（自动包装为 DocumentLike）：`{"page_content": "...", "metadata": {...}}`
6. 支持传入 `str`（纯文本，metadata 为 `{"source": "inline"}`）

## 验收标准

- [ ] 传入 LangChain `Document` 对象 → Agent 能正确处理
- [ ] 传入 `{"page_content": "hello", "metadata": {}}` → 自动包装
- [ ] 传入 `"plain text"` → 自动包装为 DocumentLike
- [ ] 传入不符合协议的对象 → 抛出清晰的错误提示
- [ ] 不引入 langchain 作为 import 依赖

## 测试建议

- 单元测试：validate_document 对有效/无效对象的判断
- 单元测试：to_agent_text 格式化输出
- 集成测试：用 LangChain 的 TextLoader 加载文件 → 传给 DTK Agent → 验证 Agent 输出
- 边界测试：空 page_content、超大 page_content、缺失 metadata

## 分类

**ready-for-agent** — 纯 Python Protocol + 简单函数，无外部依赖。但需确认 Protocol 字段名与 LangChain Document 兼容。
