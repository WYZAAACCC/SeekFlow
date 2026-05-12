# polish-003: MCP 生命周期鲁棒性测试

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

MCP 是 DTK 声称支持的功能中**最脆弱的一环**。当前实现：
- 子进程通过 `_connect_mcp_servers()` 启动
- 工具发现走 JSON-RPC handshake
- 清理走 `Agent.__del__`（不可靠）
- 没有针对 MCP server 崩溃、超时、返回畸形数据的恢复逻辑

生产环境中 MCP server 不可靠是常态——需要验证 DTK 不会因为 MCP server 的问题而崩溃。

## 任务

构造 4 个鲁棒性测试：

**测试A：MCP server 启动失败**
- Agent 配置一个不存在的 MCP server 命令
- 验证：Agent.run() 正常完成（MCP 工具不可用，但不崩溃）

**测试B：MCP server 中途崩溃**
- MCP server 在处理 tools/call 时崩溃（SIGKILL）
- 验证：Agent 捕获错误，工具调用返回 error，Agent 继续执行

**测试C：MCP server 超时**
- MCP server 的 tools/list 响应超过 10 秒
- 验证：Agent 在合理时间内超时，不无限等待

**测试D：MCP server 返回畸形响应**
- MCP server 返回非 JSON 或缺少必需字段的响应
- 验证：Agent 优雅降级，不崩溃

## 验收标准

- [ ] 4 个测试场景全部不崩溃
- [ ] MCP server 故障时 Agent 降级继续执行（不影响其他工具）
- [ ] 超时控制在 15 秒以内
- [ ] 畸形数据不导致 Python 异常逃逸到用户层

## 测试建议

- 构造简单的 Mock MCP server（Python subprocess）
- 测试 A/B/C/D 各跑 10 次
- 验证 `AgentResult` 中错误信息清晰
- 结果写入 `output/polish/mcp/` 目录

## 分类: ready-for-agent
