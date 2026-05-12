# prod-007: 中文精确 Token 计数 — 替换 char/4 启发式

**状态**: 待开始
**优先级**: P1
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

当前 ContextCompressor 和 runtime 的 _estimate_tokens() 使用 char/4 启发式。中文 1 字符 ≈ 1-2 tokens（非 0.25）。50 万中文字符预估 12.5 万 token，实际可能 50 万——4 倍误差。1M 上下文管理不可靠。

token_counter.py 有 tiktoken（cl100k_base），但 runtime 和 compressor 已改为调用 count_tokens()。问题在于：cl100k_base 是 OpenAI 的 tokenizer，对中文的估计同样不精确。需要收集 DeepSeek 实际返回的 usage 数据来校准。

## 任务

1. 在 AgentResult 中记录 API 返回的真实 usage（已有）和 char/4 预估的对比
2. 每次 run() 后计算预估误差率并累积
3. 误差率超过 20% 时发出 warning 建议用户使用较小的 max_context_tokens
4. 提供一个 `estimate_tokens_conservative(text)` 函数：中文用字符数*1.5，英文用 tiktoken
5. 在 ContextCompressor 中使用保守估计以确保不超过上下文限制

## 验收标准

- [ ] 中文文本的 token 估计误差 < 30%（原 char/4 误差 4x）
- [ ] 中英混合文本的 token 估计比纯 char/4 更接近实际值
- [ ] 误差率持续偏高时发出 warning

## 测试建议

- 用真实 DeepSeek API usage 数据验证估计精度
- 测试纯中文、纯英文、中英混合三种场景

## 分类: needs-investigation（需要收集真实 token usage 数据来校准估计器）
