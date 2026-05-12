# Issue #12: 结构化输出封装

**优先级**: P2  
**状态**: 待开始  
**分类**: enhancement  
**Triage**: ready-for-agent  
**Phase**: 3 — 开发者体验  
**依赖**: 无 — 可立即开始  
**覆盖用户故事**: #15 (结构化输出)

---

## 背景

DeepSeek V4 支持 `response_format={"type": "json_object"}` 参数，强制模型输出合法 JSON。这比后置 JSON repair（当前库的核心功能）更可靠——从源头保证 JSON 合法性，而非事后修复。

当前库的用户需要手动传递 `extra_body={"response_format": {"type": "json_object"}}`，且没有与 Pydantic 模型的类型整合。

## 任务

1. 新建 `deepseek_toolkit/structured.py`
2. 在 `chat()` 和 `chat_stream()` 签名中新增 `response_format` 参数：
   ```python
   response_format: Literal["text", "json_object"] | None = None
   ```
3. 提供 Pydantic 集成辅助函数 `structured_output(model: BaseModel)`：
   - 自动生成 JSON Schema
   - 通过 system message 注入 schema 要求
   - 返回时自动 `model.model_validate_json()`
4. 输出验证：解析失败时抛出 `StructuredOutputError` 含原始文本

## 验收标准

- [ ] `response_format="json_object"` 等价于 `extra_body={"response_format": {"type": "json_object"}}`
- [ ] `structured_output(PydanticModel)` 返回解析后的模型实例
- [ ] 模型返回非 JSON 时抛出 `StructuredOutputError`
- [ ] `response_format=None`（默认）不发送该参数
- [ ] 与 `thinking_mode` 参数共存不受影响
- [ ] 新增 ≥8 个测试

## 测试建议

- 测试 `response_format` 参数正确编码
- 测试 Pydantic 模型往返
- 测试非法 JSON 的容错
- 测试嵌套模型
- 测试与 thinking_mode 的交互
- 测试 schema 生成与模型输出匹配
- 参考 JSON repair 测试：[tests/test_files.py](../../tests/test_files.py)
