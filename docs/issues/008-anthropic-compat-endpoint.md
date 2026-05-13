# Issue #8: Anthropic 兼容端点适配

**优先级**: P1  
**状态**: 待开始  
**分类**: enhancement  
**Triage**: ready-for-agent  
**Phase**: 2 — 生产级可靠性  
**依赖**: 无 — 可立即开始  
**覆盖用户故事**: #9 (Anthropic SDK 用户零代码迁移)

---

## 背景

DeepSeek 提供 `POST https://api.deepseek.com/anthropic/v1/messages` 端点，实现了 Anthropic Messages API 的接口兼容。这意味着使用 Anthropic SDK 的应用只需修改 `base_url` 即可迁移到 DeepSeek。

当前库没有对此端点的任何封装。用户需要：
1. 了解 DeepSeek 有这个端点
2. 自行处理 Anthropic 格式与 DeepSeek 格式的差异
3. 处理 tool_use/tool_result 的格式转换

## 任务

1. 新建 `seekflow/adapters/anthropic_compat.py`
2. 实现 `DeepSeekAnthropicClient`：
   - 接受 Anthropic SDK 格式的 `messages`（`content: [TextBlock, ToolUseBlock, ...]`）
   - 内部转换为 DeepSeek 的 `content: str` 格式
   - 调用 `POST https://api.deepseek.com/anthropic/v1/messages`
3. 支持 Anthropic 风格的 tool_use/tool_result 循环
4. 内容块转换：
   - Anthropic `TextBlock` ↔ DeepSeek `content: str`
   - Anthropic `ToolUseBlock` ↔ DeepSeek `tool_calls`
   - Anthropic `ToolResultBlock` ↔ DeepSeek `role: "tool"`
5. 文档说明已知差异（图片不支持、streaming 格式差异等）

## 验收标准

- [ ] Anthropic 格式 messages 正确转换为 DeepSeek 格式并返回结果
- [ ] tool_use + tool_result 循环正常工作（至少 2 轮）
- [ ] 无效 Anthropic 格式输入返回友好错误
- [ ] 图片 `ImageBlockSource` 输入明确报错（V4 不支持）
- [ ] 真实 API 验证通过
- [ ] 新增 ≥8 个测试

## 测试建议

- 构造标准 Anthropic messages 格式测试转换
- 测试 tool_use → tool_result 往返
- 测试 system message 提取
- 测试 streaming 和非 streaming
- 测试 Anthropic 特有参数（top_k, top_p）的映射
- 参考现有适配器：[src/seekflow/adapters/openai_compatible.py](../../src/seekflow/adapters/openai_compatible.py)
