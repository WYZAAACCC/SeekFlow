# P2-1: SearchProvider 抽象 — web_search 支持国内搜索引擎

**状态**: `ready-for-agent`
**优先级**: P2
**类型**: AFK

## Parent

[PRD: 竞品差距收敛](../PRD-benchmark-gap-closure.md)

## What to build

将 web_search 工具从硬编码 DuckDuckGo 改为可配置的搜索后端，优先支持国内可用的搜索引擎。

当前问题：DuckDuckGo 在中国网络环境下超时（benchmark 中所有 3 个框架的 web_search 均超时）。作为面向中国开发者的库，应提供国内可用的搜索方案。

设计：

```python
# SearchProvider 抽象基类
class SearchProvider(ABC):
    @abstractmethod
    def search(self, query: str, max_results: int = 5, timeout: int = 10) -> list[str]: ...

class DuckDuckGoProvider(SearchProvider):  # 现有逻辑重构
    ...

class BingWebSearchProvider(SearchProvider):  # 新增，国内可用
    """Bing Web Search API v7.0 — 国内可用，免费层 1000 次/月。
    
    API details:
      Endpoint: GET https://api.bing.microsoft.com/v7.0/search
      Auth header: Ocp-Apim-Subscription-Key: {api_key}
      Query params: q={query}, count={max_results}, mkt=zh-CN
      Response JSON: {"webPages": {"value": [{"name": str, "url": str, "snippet": str}]}}
      Error response: {"error": {"code": str, "message": str}}
    """
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("BING_API_KEY", "")
        if not self.api_key:
            raise ValueError("BING_API_KEY env var or explicit api_key required for BingWebSearchProvider")
        ...
```

`@tool` 装饰器新增可选参数 `search_provider`：
- `"auto"`（默认）：自动检测网络环境，国内 → Bing，海外 → DuckDuckGo。Bing API key 未配置时 fallback 到 DuckDuckGo
- `"duckduckgo"`：强制 DuckDuckGo
- `"bing"`：强制 Bing

网络检测逻辑（`"auto"` 模式）：
- 尝试连接 DuckDuckGo，2 秒内无响应 → 判定为 CN 网络
- 判定为 CN 网络且有 Bing API key → 使用 Bing
- 判定为 CN 网络但无 Bing API key → 使用 DuckDuckGo + 返回结果中附带提示 "搜索受限，建议配置 BING_API_KEY 环境变量以获得更好的搜索体验"

搜索超时不应阻塞 agent 执行，返回 `"搜索暂时不可用: {原因}"` 并继续。

## Acceptance criteria

- [ ] `search_provider="duckduckgo"` 行为与当前完全一致
- [ ] `search_provider="bing"` 在配置了 `BING_API_KEY` 后能正常返回搜索结果
- [ ] `search_provider="auto"` 在 CN 网络下自动选择 Bing（如果配置了 key）
- [ ] `search_provider="auto"` 在 CN 网络下无 Bing key 时 fallback 到 DuckDuckGo 并附带提示
- [ ] 搜索超时返回友好提示而不抛异常阻塞 agent
- [ ] benchmark agent 中的 web_search 改为 `search_provider="auto"`

## Test suggestions

- 单元测试：mock 网络请求，验证 provider 切换逻辑
- 单元测试：mock 超时，验证不抛异常
- 集成测试：在 CN 网络下运行 `search_provider="auto"` 的 web_search，验证不超时

## Blocked by

None - can start immediately
