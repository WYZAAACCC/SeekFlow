# v3-005: Thinking Mode Agent 端到端 — 多轮 reasoning_content 透传

**状态**: 待开始
**优先级**: P0
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)
**阻塞**: v3-001

---

## 背景

这是 DTK 最核心的差异化能力。LangChain 的 ChatOpenAI 在 `_format_message_content()` 中显式过滤丢弃 `reasoning_content` 块，多轮 thinking 必 400 错误。CrewAI 整个代码库 `reasoning_content` 出现零次。

DTK v2 已在 runtime 层完整支持 thinking mode（包括 reasoning_content 提取、Session 持久化、流式事件）。v3 需要在 Agent 层验证完全集成，并确保开发者能"忘记"这一切复杂性——开箱即用。

## 任务

1. `DeepSeekAgent(thinking=True)` 默认开启 thinking mode
2. Agent `.run()` 自动完成：
   - 首次请求传入 `thinking_mode="enabled"`
   - 流式接收 reasoning_content chunk，通过 `StreamEvent(type="reasoning")` 实时输出
   - 将 reasoning_content 保存在 assistant 消息中
   - 后续轮次自动将 reasoning_content 随消息历史一起发送（这是多轮 thinking 的关键）
3. `.run()` 返回的 `AgentResult.reasoning_content` 包含完整推理过程
4. 提供 `agent.thinking` 属性让开发者在运行时查看/切换
5. 如果 API 返回的 reasoning_content 为空（某些模型版本可能不支持），Agent 正常降级，打印 info 日志

## 验收标准

- [ ] `agent.run("分析数据")` 开启 thinking → 多轮工具调用后 reasoning_content 非空
- [ ] 多轮对话（≥3 轮）不出现 400 错误
- [ ] reasoning_content 在流式输出中实时显示
- [ ] 对比测试：同一任务 thinking=False vs thinking=True，thinking=True 输出质量更高（更详细的分析）
- [ ] AgentResult.reasoning_content 可被开发者获取和检查

## 测试建议

- E2E 测试：Agent(thinking=True) → 多轮任务（需要工具调用）→ 验证无 400 错误 + reasoning_content 非空
- 回归测试：Agent(thinking=False) → 验证正常运行（不退化）
- 对比测试：同一个复杂分析任务，thinking on vs off → 人工评估输出质量差异
- 参照：`tests/test_thinking.py` 中已有的 thinking mode 测试

## 分类

**ready-for-agent** — v2 runtime 层已完整实现 reasoning_content 处理，v3 Agent 层仅需集成验证。这是 DTK 最硬核的差异化功能，优先级最高。
