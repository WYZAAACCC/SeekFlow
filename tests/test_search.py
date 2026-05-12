"""Tests for deepseek_toolkit.search — SearchProvider abstraction."""
import pytest
from unittest.mock import patch, MagicMock


class TestSearchProviderABC:
    def test_cannot_instantiate_abstract(self):
        from deepseek_toolkit.search import SearchProvider
        with pytest.raises(TypeError):
            SearchProvider()  # type: ignore[abstract]


class TestDuckDuckGoProvider:
    def test_search_returns_snippets(self):
        from deepseek_toolkit.search import DuckDuckGoProvider

        mock_html = """
        <html><body>
        <a class="result__snippet">First result snippet</a>
        <a class="result__snippet">Second <b>result</b> snippet</a>
        </body></html>
        """
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = mock_html.encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            provider = DuckDuckGoProvider()
            results = provider.search("test query", max_results=3)

        assert len(results) == 2
        assert "First result snippet" in results[0]
        assert "Second result snippet" in results[1]

    def test_search_timeout_returns_graceful_message(self):
        from deepseek_toolkit.search import DuckDuckGoProvider
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            provider = DuckDuckGoProvider()
            results = provider.search("test", timeout=1)

        assert len(results) == 1
        assert "暂时不可用" in results[0]

    def test_no_results_returns_message(self):
        from deepseek_toolkit.search import DuckDuckGoProvider

        mock_html = "<html><body>No results here</body></html>"
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = mock_html.encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            provider = DuckDuckGoProvider()
            results = provider.search("xyzabc123")

        assert len(results) == 1
        assert "No results" in results[0]


class TestBingWebSearchProvider:
    def test_requires_api_key(self):
        from deepseek_toolkit.search import BingWebSearchProvider
        with patch("os.environ", {}):
            with pytest.raises(ValueError, match="BING_API_KEY"):
                BingWebSearchProvider()

    def test_accepts_explicit_api_key(self):
        from deepseek_toolkit.search import BingWebSearchProvider
        provider = BingWebSearchProvider(api_key="test-key")
        assert provider.api_key == "test-key"

    def test_search_parses_response(self):
        from deepseek_toolkit.search import BingWebSearchProvider
        import json

        mock_response = {
            "webPages": {
                "value": [
                    {"name": "Result 1", "url": "https://a.com", "snippet": "Snippet A"},
                    {"name": "Result 2", "url": "https://b.com", "snippet": "Snippet B"},
                ]
            }
        }
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(mock_response).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            provider = BingWebSearchProvider(api_key="test-key")
            results = provider.search("test", max_results=5)

        assert len(results) == 2
        assert "1. Result 1" in results[0]
        assert "Snippet A" in results[0]

    def test_search_api_error_returns_graceful_message(self):
        from deepseek_toolkit.search import BingWebSearchProvider
        import json

        mock_response = {"error": {"code": "401", "message": "Access denied"}}
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps(mock_response).encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            provider = BingWebSearchProvider(api_key="bad-key")
            results = provider.search("test")

        assert len(results) == 1
        assert "Bing API error" in results[0]

    def test_search_timeout_returns_graceful_message(self):
        from deepseek_toolkit.search import BingWebSearchProvider
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            provider = BingWebSearchProvider(api_key="test-key")
            results = provider.search("test", timeout=1)

        assert len(results) == 1
        assert "暂时不可用" in results[0]


class TestBingChinaSearchProvider:
    def test_search_parses_results(self):
        from deepseek_toolkit.search import BingChinaSearchProvider

        mock_html = """
        <html><body>
        <li class="b_algo"><h2><a href="https://example.com">Example Title</a></h2>
        <p>This is a snippet about the example.</p></li>
        <li class="b_algo"><h2><a href="https://test.com">Test Page</a></h2>
        <div class="b_caption">Another snippet here.</div></li>
        </body></html>
        """
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = mock_html.encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            provider = BingChinaSearchProvider()
            results = provider.search("test query", max_results=3)

        assert len(results) == 2
        assert "Example Title" in results[0]
        assert "example.com" in results[0]
        assert "Test Page" in results[1]

    def test_search_timeout_returns_graceful_message(self):
        from deepseek_toolkit.search import BingChinaSearchProvider
        import urllib.error

        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            provider = BingChinaSearchProvider()
            results = provider.search("test", timeout=1)

        assert len(results) == 1
        assert "暂时不可用" in results[0]

    def test_no_results_returns_message(self):
        from deepseek_toolkit.search import BingChinaSearchProvider

        mock_html = "<html><body>No results here</body></html>"
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = mock_html.encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            provider = BingChinaSearchProvider()
            results = provider.search("xyzabc123")

        assert len(results) == 1
        assert "未找到" in results[0]

    def test_results_truncated_to_max(self):
        from deepseek_toolkit.search import BingChinaSearchProvider

        # Create 10 result blocks
        blocks = []
        for i in range(10):
            blocks.append(
                f'<li class="b_algo"><h2><a href="https://site{i}.com">Result {i}</a></h2>'
                f"<p>Snippet {i}</p></li>"
            )
        mock_html = "<html><body>" + "".join(blocks) + "</body></html>"
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = mock_html.encode("utf-8")
            mock_resp.__enter__.return_value = mock_resp
            mock_urlopen.return_value = mock_resp

            provider = BingChinaSearchProvider()
            results = provider.search("test", max_results=3)

        assert len(results) == 3


class TestAutoDetectProvider:
    def test_with_bing_key_returns_bing_provider(self):
        from deepseek_toolkit.search import auto_detect_provider, BingWebSearchProvider
        with patch.dict("os.environ", {"BING_API_KEY": "test-key"}):
            provider = auto_detect_provider()
        assert isinstance(provider, BingWebSearchProvider)

    def test_without_bing_key_returns_bingchina(self):
        from deepseek_toolkit.search import auto_detect_provider, BingChinaSearchProvider
        with patch.dict("os.environ", {}, clear=True):
            provider = auto_detect_provider()
        assert isinstance(provider, BingChinaSearchProvider)


class TestGetSearchProvider:
    def test_auto_string_with_key_returns_bing(self):
        from deepseek_toolkit.search import get_search_provider, BingWebSearchProvider
        with patch.dict("os.environ", {"BING_API_KEY": "test-key"}):
            provider = get_search_provider("auto")
        assert isinstance(provider, BingWebSearchProvider)

    def test_auto_string_without_key_returns_bingchina(self):
        from deepseek_toolkit.search import get_search_provider, BingChinaSearchProvider
        with patch.dict("os.environ", {}, clear=True):
            provider = get_search_provider("auto")
        assert isinstance(provider, BingChinaSearchProvider)

    def test_bingchina_string_returns_bingchina(self):
        from deepseek_toolkit.search import get_search_provider, BingChinaSearchProvider
        provider = get_search_provider("bingchina")
        assert isinstance(provider, BingChinaSearchProvider)

    def test_duckduckgo_string_returns_duckduckgo(self):
        from deepseek_toolkit.search import get_search_provider, DuckDuckGoProvider
        provider = get_search_provider("duckduckgo")
        assert isinstance(provider, DuckDuckGoProvider)

    def test_bing_string_returns_bing(self):
        from deepseek_toolkit.search import get_search_provider, BingWebSearchProvider
        provider = get_search_provider("bing", api_key="test-key")
        assert isinstance(provider, BingWebSearchProvider)

    def test_passing_provider_instance_returns_same(self):
        from deepseek_toolkit.search import get_search_provider, DuckDuckGoProvider
        original = DuckDuckGoProvider()
        result = get_search_provider(original)
        assert result is original
