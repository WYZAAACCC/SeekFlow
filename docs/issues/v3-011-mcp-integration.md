# v3-011: MCP 工具集成 — Agent 层直接使用 MCP 工具

**状态**: 待开始
**优先级**: P2
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)
**阻塞**: v3-003

---

## 背景

MCP（Model Context Protocol）是 Anthropic 发布的开放标准，用于 LLM 与外部工具/资源/提示之间的互操作。LangChain 已支持 MCP，DTK v2 已有 MCP 适配器（`docs/issues/009-MCP-stdio适配.md`）。

v3 需要在 Agent 层使 MCP 工具像普通工具一样可用——开发者不需要关心工具来自哪里（Python 函数还是 MCP 服务）。

## 任务

1. 在 `DeepSeekAgent` 上实现 `.add_mcp_tools(server_command: str, server_args: list[str] | None = None)`
2. 内部逻辑：
   - 启动 MCP server 子进程
   - 通过 stdio 通信获取 tools/list
   - 将 MCP 工具转换为 DTK tool schema
   - 注册到 Agent 的工具列表
3. 工具调用时：
   - DTK ToolRuntime 识别 MCP 工具 → 通过 stdio 发送 tools/call → 获取结果
4. 支持同时注册多个 MCP server
5. Agent 销毁时自动清理 MCP server 子进程

## 验收标准

- [ ] `agent.add_mcp_tools("python", ["-m", "my_mcp_server"])` 注册 MCP 工具
- [ ] Agent 执行任务时能调用 MCP 工具
- [ ] MCP 工具调用结果正确返回给模型
- [ ] Agent 对象被垃圾回收时 MCP 子进程自动终止

## 测试建议

- 集成测试：启动一个简单的 MCP echo server → Agent 调用 echo 工具 → 验证结果
- 单元测试：MCP 工具 schema 转换逻辑
- 边界测试：MCP server 启动失败、通信超时、返回非 JSON 响应

## 分类

**needs-investigation** — v2 已有 MCP 适配器，但需确认其接口在 v3 Agent 层集成时是否够用。可能需要先阅读 v2 MCP 实现，确认 schema 转换和错误处理逻辑。
