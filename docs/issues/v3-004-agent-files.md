# v3-004: Agent 文件输入 — `.run(files=[...])` 1M 上下文全量导入

**状态**: 待开始
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)
**阻塞**: v3-001

---

## 背景

DeepSeek V4 支持 1M 上下文窗口。100 页 PDF 全文约 30 万 token，完全可以直接扔进上下文。这改变了传统的 chunk→embed→retrieve 范式。

当前 DTK v2 的 `read_file` 工具可以读文件，但文件内容被截断到 4000 字符，且作为工具调用结果返回——模型在后续轮次才能"看到"完整内容。v3 应在 Agent 启动时就将文件内容嵌入 system prompt 或首批消息中，让模型在第一轮就拥有完整上下文。

同时，LangChain 和 CrewAI 对 DeepSeek 1M 上下文的支持极差：LangChain 完全没有 DeepSeek 模型 profile（上下文大小未知），CrewAI 仅识别 `deepseek-chat: 128K`（少 8 倍）。

## 任务

1. `DeepSeekAgent.run(files: list[str] | None = None)` 支持传入文件路径列表
2. 支持的文件类型：`.txt`、`.md`、`.csv`、`.json`、`.pdf`（通过 PyPDF2 或 pdfplumber 读取）
3. 文件内容嵌入到 system prompt 末尾（格式：`## 参考文件\n\n### 文件名\n文件内容\n`）
4. 自动检测总 token 数：如果所有文件 + system prompt 的总 token 超过 900K（1M 的 90%），截断并警告
5. 截断策略：优先保留文件开头和结尾，中间用 `[...已截断 X 字符...]` 标记
6. 支持传入 `max_context_tokens: int = 900000` 参数自定义截断阈值
7. 文件不存在或无法读取时，抛出明确的中文错误

## 验收标准

- [ ] `agent.run("总结这份 PDF", files=["report.pdf"])` 能正确处理 PDF 文件
- [ ] 单个 200 万 token 的文件自动截断到 ~90 万 token，并打印截断警告
- [ ] 不存在的文件路径给出 "文件未找到: xxx" 错误
- [ ] 多个文件合并后不超过上下文限制

## 测试建议

- E2E 测试：Agent + 真实 PDF/CSV 文件 → 验证输出中引用了文件内容
- 单元测试：token 计数逻辑 → 截断逻辑 → 多文件合并逻辑
- 边界测试：空文件、二进制文件、超大文件、不存在的文件

## 分类

**ready-for-agent** — 文件读取 + token 计数 + 截断逻辑，现有 token_counter 可复用。
