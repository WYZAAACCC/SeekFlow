# perf-003: 内置工具库 — 20 个高质量 DeepSeek 常用工具

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

当前 `with_default_tools()` 只有 5 个基础工具（read_file, web_search, download_page, calculate, save_result）。用户开箱后需要自己写工具。LangChain 有 800+ 集成，CrewAI 有 `@tool` 生态。DTK 不需要 800 个，但需要 20 个用得最多的工具让用户立刻能干活。

## 任务

创建 `seekflow/tools/builtin/` 包，包含 20 个工具：

### 网络与数据
1. `web_search(query)` — Bing 搜索（已有，移至 builtin）
2. `fetch_url(url)` — HTTP GET 请求，返回文本
3. `call_api(url, method, headers, body)` — 通用 API 调用
4. `query_sql(db_path, query)` — SQLite 查询

### 文件处理
5. `read_file(path)` — 读文件（已有，移至 builtin）
6. `write_file(path, content)` — 写文件
7. `parse_pdf(path)` — PDF 文本提取
8. `parse_csv(path)` — CSV 解析为 JSON

### 计算与代码
9. `calculate(expression)` — 数学计算（已有，移至 builtin）
10. `run_python(code)` — 沙箱 Python 执行

### AI 增强
11. `summarize(text)` — 文本摘要（调用 Agent）
12. `extract_entities(text)` — 实体提取
13. `translate(text, target_lang)` — 翻译
14. `classify(text, labels)` — 文本分类
15. `compare(text_a, text_b)` — 文本对比

### 输出
16. `save_result(filename, content)` — 保存结果（已有，移至 builtin）
17. `generate_chart(data, chart_type)` — 生成图表
18. `send_email(to, subject, body)` — 发送邮件

### 搜索与检索
19. `search_vector(query, collection)` — 向量搜索
20. `embed_text(text)` — 文本嵌入

## 验收标准

- [ ] `agent.with_default_tools()` 加载全部 20 个工具
- [ ] 每个工具有完整的 docstring、type hints、错误处理
- [ ] 网络工具支持超时和重试
- [ ] 文件工具支持路径验证

## 测试建议

- 每个工具有至少 1 个单元测试
- 网络工具 mock HTTP 响应
- E2E：Agent + 5 个工具组合完成复杂任务

## 分类: ready-for-agent
