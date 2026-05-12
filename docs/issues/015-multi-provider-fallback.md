# Issue #15: 多 Provider 降级链

**优先级**: P3  
**状态**: 待开始  
**分类**: enhancement  
**Triage**: ready-for-agent  
**Phase**: 4 — 生态补齐  
**依赖**: 无 — 可立即开始  
**覆盖用户故事**: #18 (多 Provider 降级)

---

## 背景

DeepSeek API 虽然是主要 provider，但以下场景需要备选方案：
- DeepSeek 官方 API 故障或限流
- 降低成本的备选渠道（硅基流动等第三方）
- 隐私敏感场景需要本地模型

当前库仅支持单一的 `base_url`，没有故障切换能力。用户需要自己实现重试到不同 provider。

备选 provider 的兼容性：
- 硅基流动：支持 `/v1/chat/completions`，兼容 OpenAI SDK
- Ollama：本地运行，支持 OpenAI 兼容 API
- 其他 DeepSeek API 代理

## 任务

1. 新建 `deepseek_toolkit/fallback.py`
2. 实现 `ProviderConfig` 数据类：
   - `name`, `base_url`, `api_key`, `models`（该 provider 支持的模型列表）
   - `priority`（数字越小越优先）
   - `health_check_interval: float = 60.0`
3. 实现 `FallbackChain`：
   - 按 priority 排序的 provider 列表
   - `execute(fn, *args, **kwargs)` — 按序尝试 provider，遇错自动切换
   - 健康检查：定期探测 provider 可用性，标记不可用的 provider
   - 自动恢复：不可用 provider 定时重试探测
4. 配置方式：
   ```python
   chain = FallbackChain([
       ProviderConfig(name="deepseek", base_url="https://api.deepseek.com", api_key="sk-..."),
       ProviderConfig(name="siliconflow", base_url="https://api.siliconflow.cn/v1", api_key="sf-..."),
       ProviderConfig(name="ollama", base_url="http://localhost:11434/v1", api_key="ollama"),
   ])
   rt = ToolRuntime(tools=[...], provider_chain=chain)
   ```
5. YAML/JSON 配置文件支持：`FallbackChain.from_config("providers.yaml")`

## 验收标准

- [ ] 主 provider 健康时所有请求走主 provider
- [ ] 主 provider 返回 503 后自动切换到第二个
- [ ] 主 provider 恢复后自动切回
- [ ] 所有 provider 不可用时抛出 `AllProvidersFailedError`
- [ ] 健康检查间隔正确
- [ ] 新增 ≥8 个测试

## 测试建议

- Mock HTTP 使主 provider 失败，验证切换
- 测试健康检查恢复逻辑
- 测试全部不可用的异常
- 测试配置文件加载
- 测试不同 provider 的 model 名称映射
- 测试并发访问的线程安全
- 参考现有重试逻辑：[src/deepseek_toolkit/retry.py](../../src/deepseek_toolkit/retry.py)
