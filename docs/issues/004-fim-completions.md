# Issue #4: FIM 补全端点封装

**优先级**: P0  
**状态**: 待开始  
**分类**: enhancement  
**Triage**: ready-for-agent  
**Phase**: 1 — DeepSeek 核心 API  
**依赖**: 无 — 可立即开始  
**覆盖用户故事**: #4 (FIM 代码补全)

---

## 背景

DeepSeek 通过 beta 端点 `POST https://api.deepseek.com/beta/completions` 提供 FIM（Fill-in-the-Middle）补全能力。这是 DeepSeek 独有的功能，用于 IDE 代码补全场景——给定光标前后的代码（`prefix` + `suffix`），模型生成中间缺失的代码。

目前市面上没有任何 Python 库封装 DeepSeek 的 FIM 端点。用户需要自己拼接 HTTP 请求。

FIM 请求格式与 OpenAI Completions API 类似，但使用特定的 token 标记：
- `<|fim_begin|>` — prefix 开始
- `<|fim_hole|>` — 缺口（suffix 开始）
- `<|fim_end|>` — suffix 结束

## 任务

1. 新建 `deepseek_toolkit/fim.py`
2. 实现 `fim_complete(prefix, suffix, *, model, api_key=None, **kwargs) -> FIMResponse`：
   - `FIMResponse` 数据类：`text`, `usage`, `model`, `finish_reason`
3. 实现 `fim_complete_stream(prefix, suffix, *, model, api_key=None, **kwargs) -> Iterator[FIMChunk]`：
   - `FIMChunk` 数据类：`text`, `finish_reason`
4. 使用 beta 端点：`POST https://api.deepseek.com/beta/completions`
5. 支持常用参数：`max_tokens`, `temperature`, `top_p`, `stop`
6. 内置 `DeepSeekFIMClient`，复用 `DeepSeekClient` 的认证逻辑

## 验收标准

- [ ] `fim_complete()` 返回非空补全文本
- [ ] `fim_complete_stream()` 逐 token 产出
- [ ] 空 `prefix` + 非空 `suffix` 不崩溃
- [ ] 空 `suffix` + 非空 `prefix` 不崩溃
- [ ] 极长 `prefix + suffix` 超过上下文窗口时返回友好错误（#1 的 `ContextLengthExceededError`）
- [ ] 真实 API 验证通过
- [ ] 新增 ≥8 个测试

## 测试建议

- Mock beta 端点响应
- 测试 streaming 和非 streaming 路径
- 测试空输入边界
- 测试超长输入被拒绝
- 测试认证失败场景
- 参考 streaming 测试模式：[tests/test_files.py](../../tests/test_files.py)
