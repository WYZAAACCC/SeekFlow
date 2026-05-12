"""Search provider abstraction — pluggable backends for web_search."""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod


def _decode_html_entities(text: str) -> str:
    """Decode common HTML entities to Unicode."""
    import html as _html
    return _html.unescape(text)


class SearchProvider(ABC):
    """Abstract base for search backends."""

    @abstractmethod
    def search(self, query: str, max_results: int = 5, timeout: int = 10) -> list[str]:
        """Execute a search query.

        Returns a list of result strings. On failure, returns a single-element
        list with a user-friendly error message — never raises.
        """


class DuckDuckGoProvider(SearchProvider):
    """Search via DuckDuckGo HTML endpoint (no API key required)."""

    def search(self, query: str, max_results: int = 5, timeout: int = 10) -> list[str]:
        url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        req = urllib.request.Request(url, headers={"User-Agent": "DeepSeekToolkit/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception:
            return [u"搜索暂时不可用 (DuckDuckGo): 请检查网络连接或配置 BING_API_KEY"]

        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)
        results = []
        for s in snippets[:max_results]:
            text = re.sub(r'<[^>]+>', '', s).strip()
            if text:
                results.append(text)
        return results if results else ["No results."]


class BingWebSearchProvider(SearchProvider):
    """Search via Bing Web Search API v7.0.

    Requires BING_API_KEY environment variable or explicit api_key.
    Free tier: 1000 requests/month.
    """

    ENDPOINT = "https://api.bing.microsoft.com/v7.0/search"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("BING_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "BING_API_KEY env var or explicit api_key required for BingWebSearchProvider"
            )

    def search(self, query: str, max_results: int = 5, timeout: int = 10) -> list[str]:
        params = urllib.parse.urlencode({
            "q": query,
            "count": str(max_results),
            "mkt": "zh-CN",
        })
        url = f"{self.ENDPOINT}?{params}"
        req = urllib.request.Request(url, headers={
            "Ocp-Apim-Subscription-Key": self.api_key,
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return [u"搜索暂时不可用 (Bing): 请检查网络连接或 API key 是否有效"]

        if "error" in data:
            err = data["error"]
            return [f"Bing API error {err.get('code', 'unknown')}: {err.get('message', 'unknown')}"]

        web_pages = data.get("webPages", {})
        values = web_pages.get("value", [])
        results = [
            f"{i+1}. {page.get('name', '')}\n   {page.get('snippet', '')}\n   {page.get('url', '')}"
            for i, page in enumerate(values[:max_results])
        ]
        return results if results else ["No results."]


class BingChinaSearchProvider(SearchProvider):
    """Search via cn.bing.com HTML scraping (China-accessible, no API key required).

    Uses cn.bing.com which is accessible in mainland China without VPN.
    Falls back gracefully on network errors.
    """

    BASE_URL = "https://cn.bing.com/search"

    def search(self, query: str, max_results: int = 5, timeout: int = 10) -> list[str]:
        params = urllib.parse.urlencode({"q": query, "setlang": "zh-cn"})
        url = f"{self.BASE_URL}?{params}"
        req = urllib.request.Request(url, headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception:
            return [u"搜索暂时不可用 (Bing China): 请检查网络连接"]

        # Parse Bing HTML results
        results: list[str] = []
        sections = re.split(r'<li class="b_algo', html)
        for section in sections[1:]:
            if len(results) >= max_results:
                break
            # Extract URL from <h2><a href="..."> specifically (avoid CSS/file links)
            h2_link_match = re.search(
                r"<h2[^>]*><a[^>]*href=\"(https?://[^\"]+)\"[^>]*>", section
            )
            page_url = h2_link_match.group(1) if h2_link_match else ""
            # Extract title from <h2><a>...</a></h2>
            title_match = re.search(r"<h2[^>]*><a[^>]*>(.*?)</a></h2>", section, re.DOTALL)
            title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else ""
            # Extract snippet — try <p> first, then <div class="b_caption">
            snippet = ""
            p_match = re.search(r"<p[^>]*>(.*?)</p>", section, re.DOTALL)
            if p_match:
                snippet = re.sub(r"<[^>]+>", "", p_match.group(1)).strip()
            if not snippet:
                cap_match = re.search(
                    r'class="b_caption[^"]*"[^>]*>(.*?)</div>', section, re.DOTALL
                )
                if cap_match:
                    snippet = re.sub(r"<[^>]+>", "", cap_match.group(1)).strip()
            # Decode HTML entities
            title = _decode_html_entities(title)
            snippet = _decode_html_entities(snippet)
            page_url = _decode_html_entities(page_url)
            if title:
                entry = f"{len(results) + 1}. {title}"
                if snippet:
                    entry += f"\n   {snippet}"
                if page_url:
                    entry += f"\n   {page_url}"
                results.append(entry)

        return results if results else [u"未找到相关搜索结果"]


def auto_detect_provider(api_key: str | None = None) -> SearchProvider:
    """Auto-select: Bing API if key configured, else Bing China (CN-accessible)."""
    key = api_key or os.environ.get("BING_API_KEY", "")
    if key:
        return BingWebSearchProvider(api_key=key)
    return BingChinaSearchProvider()


def get_search_provider(
    provider: str | SearchProvider = "auto",
    api_key: str | None = None,
) -> SearchProvider:
    """Resolve a search provider specification to a SearchProvider instance.

    Args:
        provider: "auto", "duckduckgo", "bing", "bingchina", or a SearchProvider instance.
        api_key: Optional Bing API key (used when provider="bing").

    Returns:
        A SearchProvider instance.
    """
    if isinstance(provider, SearchProvider):
        return provider
    if provider == "duckduckgo":
        return DuckDuckGoProvider()
    if provider == "bing":
        return BingWebSearchProvider(api_key=api_key)
    if provider == "bingchina":
        return BingChinaSearchProvider()
    if provider == "auto":
        return auto_detect_provider(api_key=api_key)
    raise ValueError(f"Unknown search provider: {provider!r}")
