# Issue #14: Token 计数工具

**优先级**: P3  
**状态**: 待开始  
**分类**: enhancement  
**Triage**: ready-for-agent  
**Phase**: 4 — 生态补齐  
**依赖**: 无 — 可立即开始  
**覆盖用户故事**: #17 (Token 计数)

---

## 背景

在以下场景中需要在发送请求前预估 token 数：
- **上下文预算控制**：确保 messages 不超过模型窗口
- **成本预估**：在调用前给出费用估算
- **截断决策**：判断是否需要压缩/截断消息

DeepSeek 使用标准的 tokenizer（与 OpenAI `cl100k_base` 兼容），可使用 `tiktoken` 库进行计数。当前库不提供计数功能，用户需要自己集成 `tiktoken`。

## 任务

1. 新建 `seekflow/token_counter.py`
2. 实现 `count_tokens(messages, model="deepseek-v4-pro") -> int`：
   - 计算消息列表中所有文本的 token 数
   - 包含 `content`、`tool_calls`、`reasoning_content` 的计数
3. 实现 `count_text(text, model="deepseek-v4-pro") -> int`：
   - 计算单段文本的 token 数
4. 使用 `tiktoken` 库（可选依赖，`try/except ImportError`）
5. `tiktoken` 不可用时回退到字符/4 的粗略估算，并输出警告
6. 与 #7（上下文管理）集成：使用精确的 token 计数替代估算

## 验收标准

- [ ] `count_tokens()` 返回结果与 API 返回的 `usage.prompt_tokens` 误差 < 5%
- [ ] `tiktoken` 不可用时回退到估算模式
- [ ] 计数包含 `reasoning_content`
- [ ] 计数包含 tool call 的 `arguments`
- [ ] 空消息列表返回 0
- [ ] 新增 ≥8 个测试

## 测试建议

- 使用已知 token 数的文本验证计数
- 测试多消息组合的计数
- 测试 tool_calls 的 token 计数
- 测试 tiktoken 不可用时的回退
- 测试中英文混合文本
- 测试极长文本的计数
- 参考 types：[src/seekflow/types.py](../../src/seekflow/types.py)
