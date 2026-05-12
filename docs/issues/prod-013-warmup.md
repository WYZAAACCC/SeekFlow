# prod-013: 连接预热 — 消除首次 API 调用的 2-3 秒冷启动延迟

**状态**: 待开始
**优先级**: P2
**父级**: [DTK-v3-agent-framework](../prd/DTK-v3-agent-framework.md)

## 背景

OpenAI SDK 的 httpx 连接池延迟初始化——首次 API 调用的 TCP/TLS 握手耗时 2-3 秒。后续调用 0.5 秒。生产环境中这 2-3 秒直接影响用户体验。LangChain/CrewAI 同样有这个问题——都没有预热。

## 任务

1. Agent 增加 `prewarm()` 方法：发送一个最小请求来初始化连接池
2. prewarm 请求使用 `max_tokens=1, temperature=0` 最小化成本
3. prewarm 结果缓存 300s（5 分钟内不重复预热）
4. Agent.run() 首次调用时自动 prewarm（可关闭）
5. 预热失败不影响后续正常调用

## 验收标准

- [ ] 预热后首次 real run() 延迟显著低于未预热
- [ ] 预热请求 token 消耗 < 10
- [ ] 预热失败不阻塞正常运行

## 测试建议

- 计时对比：预热 vs 未预热的首次 run() 延迟
- 验证预热请求 token 消耗最小化

## 分类: ready-for-agent
