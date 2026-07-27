"""Tests for src/data/news_client/ (Google News RSS + NHK RSS fallback)."""

import xml.etree.ElementTree as ET
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.no_auto_mock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_GOOGLE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:ns0="https://news.google.com/rss">
  <channel>
    <title>Google News</title>
    <item>
      <title>日経平均が反発、半導体株に買い</title>
      <link>https://example.com/1</link>
      <pubDate>Thu, 30 Apr 2026 09:00:00 +0900</pubDate>
      <ns0:source>日本経済新聞</ns0:source>
    </item>
    <item>
      <title>米国株ナスダック小幅続伸</title>
      <link>https://example.com/2</link>
      <pubDate>Thu, 30 Apr 2026 08:00:00 +0900</pubDate>
      <ns0:source>Bloomberg</ns0:source>
    </item>
  </channel>
</rss>""".encode("utf-8")

_NHK_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>NHK</title>
    <item>
      <title>日銀 金融政策決定会合 現状維持を決定</title>
      <link>https://nhk.or.jp/1</link>
      <pubDate>Thu, 30 Apr 2026 12:00:00 +0900</pubDate>
    </item>
    <item>
      <title>為替 円安進む 1ドル160円台</title>
      <link>https://nhk.or.jp/2</link>
      <pubDate>Thu, 30 Apr 2026 11:00:00 +0900</pubDate>
    </item>
  </channel>
</rss>""".encode("utf-8")


def _mock_urlopen_factory(xml_by_url: dict):
    """urlopen を URL で分岐させるモック工場。"""
    def _mock_urlopen(req, timeout=10):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        for key, content in xml_by_url.items():
            if key in url:
                mock_resp = MagicMock()
                mock_resp.read.return_value = content
                mock_resp.__enter__ = lambda s: s
                mock_resp.__exit__ = MagicMock(return_value=False)
                return mock_resp
        raise ConnectionError(f"unexpected URL: {url}")
    return _mock_urlopen


# ---------------------------------------------------------------------------
# TestFetchGoogleNews
# ---------------------------------------------------------------------------

class TestFetchGoogleNews:
    def test_returns_items(self):
        from src.data.news_client._rss import fetch_google_news, clear_cache
        clear_cache()

        with patch("src.data.news_client._rss.urlopen",
                   _mock_urlopen_factory({"news.google.com": _GOOGLE_RSS_XML})):
            items = fetch_google_news("日本株", max_items=5)

        assert len(items) == 2
        assert items[0]["title"] == "日経平均が反発、半導体株に買い"
        assert items[0]["source"] == "日本経済新聞"

    def test_cached_second_call(self):
        from src.data.news_client._rss import fetch_google_news, clear_cache
        clear_cache()

        call_count = 0
        original_fetch = None

        def counting_urlopen(req, timeout=10):
            nonlocal call_count
            call_count += 1
            return _mock_urlopen_factory({"news.google.com": _GOOGLE_RSS_XML})(req, timeout)

        with patch("src.data.news_client._rss.urlopen", counting_urlopen):
            fetch_google_news("日本株")
            fetch_google_news("日本株")  # should hit cache

        assert call_count == 1  # only one real HTTP call

    def test_fetch_error_returns_empty(self):
        from src.data.news_client._rss import fetch_google_news, clear_cache
        clear_cache()

        with patch("src.data.news_client._rss.urlopen", side_effect=ConnectionError("offline")):
            items = fetch_google_news("日本株")

        assert items == []

    def test_max_items_respected(self):
        from src.data.news_client._rss import fetch_google_news, clear_cache
        clear_cache()

        with patch("src.data.news_client._rss.urlopen",
                   _mock_urlopen_factory({"news.google.com": _GOOGLE_RSS_XML})):
            items = fetch_google_news("日本株", max_items=1)

        assert len(items) == 1


# ---------------------------------------------------------------------------
# TestFetchNhkNews
# ---------------------------------------------------------------------------

class TestFetchNhkNews:
    def test_returns_items(self):
        from src.data.news_client._rss import fetch_nhk_news, clear_cache
        clear_cache()

        with patch("src.data.news_client._rss.urlopen",
                   _mock_urlopen_factory({"nhk.or.jp": _NHK_RSS_XML})):
            items = fetch_nhk_news(max_items=5)

        assert len(items) == 2
        assert "日銀" in items[0]["title"]

    def test_fetch_error_returns_empty(self):
        from src.data.news_client._rss import fetch_nhk_news, clear_cache
        clear_cache()

        with patch("src.data.news_client._rss.urlopen", side_effect=ConnectionError("offline")):
            items = fetch_nhk_news()

        assert items == []


# ---------------------------------------------------------------------------
# TestSearchMarketRss
# ---------------------------------------------------------------------------

class TestSearchMarketRss:
    def test_returns_market_schema(self):
        from src.data.news_client._rss import clear_cache
        from src.data.news_client.market_news import search_market_rss
        clear_cache()

        url_map = {
            "news.google.com": _GOOGLE_RSS_XML,
            "nhk.or.jp": _NHK_RSS_XML,
        }
        with patch("src.data.news_client._rss.urlopen", _mock_urlopen_factory(url_map)):
            result = search_market_rss("日本株")

        # Must match EMPTY_MARKET schema
        assert "price_action" in result
        assert "macro_factors" in result
        assert "sentiment" in result
        assert "upcoming_events" in result
        assert "sector_rotation" in result
        assert "raw_response" in result
        assert result["source"] == "rss"

    def test_price_action_contains_headlines(self):
        from src.data.news_client._rss import clear_cache
        from src.data.news_client.market_news import search_market_rss
        clear_cache()

        url_map = {
            "news.google.com": _GOOGLE_RSS_XML,
            "nhk.or.jp": _NHK_RSS_XML,
        }
        with patch("src.data.news_client._rss.urlopen", _mock_urlopen_factory(url_map)):
            result = search_market_rss("日本株")

        assert "日経平均" in result["price_action"]

    def test_macro_factors_from_nhk(self):
        from src.data.news_client._rss import clear_cache
        from src.data.news_client.market_news import search_market_rss
        clear_cache()

        url_map = {
            "news.google.com": _GOOGLE_RSS_XML,
            "nhk.or.jp": _NHK_RSS_XML,
        }
        with patch("src.data.news_client._rss.urlopen", _mock_urlopen_factory(url_map)):
            result = search_market_rss("日本株")

        assert any("日銀" in f for f in result["macro_factors"])

    def test_both_sources_in_raw_response(self):
        from src.data.news_client._rss import clear_cache
        from src.data.news_client.market_news import search_market_rss
        clear_cache()

        url_map = {
            "news.google.com": _GOOGLE_RSS_XML,
            "nhk.or.jp": _NHK_RSS_XML,
        }
        with patch("src.data.news_client._rss.urlopen", _mock_urlopen_factory(url_map)):
            result = search_market_rss("日本株")

        assert "Google News" in result["raw_response"]
        assert "NHK" in result["raw_response"]

    def test_graceful_on_both_failures(self):
        from src.data.news_client._rss import clear_cache
        from src.data.news_client.market_news import search_market_rss
        clear_cache()

        with patch("src.data.news_client._rss.urlopen", side_effect=ConnectionError("offline")):
            result = search_market_rss("日本株")

        assert result["price_action"] == ""
        assert result["macro_factors"] == []
        assert result["source"] == "rss"


# ---------------------------------------------------------------------------
# TestGrokFallback
# ---------------------------------------------------------------------------

class TestGrokFallback:
    def test_uses_rss_when_grok_returns_empty(self, monkeypatch):
        """search_market() が空結果を返した時 RSS にフォールバックする。"""
        from src.data.news_client._rss import clear_cache
        clear_cache()

        # Grok が空結果を返すよう mock
        monkeypatch.setattr(
            "tools.grok._grok_search_market",
            lambda *a, **kw: {"price_action": "", "macro_factors": [], "raw_response": "",
                              "sentiment": {"score": 0.0, "summary": ""}, "upcoming_events": [],
                              "sector_rotation": []},
        )

        url_map = {
            "news.google.com": _GOOGLE_RSS_XML,
            "nhk.or.jp": _NHK_RSS_XML,
        }
        with patch("src.data.news_client._rss.urlopen", _mock_urlopen_factory(url_map)):
            import importlib
            import tools.grok as grok_tool
            result = grok_tool.search_market("日本株")

        assert result["source"] == "rss"
        assert result["price_action"] != ""

    def test_uses_grok_when_available(self, monkeypatch):
        """Grok が正常応答を返した場合は RSS を呼ばない。"""
        grok_response = {
            "price_action": "日経平均反発",
            "macro_factors": ["円安"],
            "raw_response": "some content",
            "sentiment": {"score": 0.3, "summary": "強気"},
            "upcoming_events": [],
            "sector_rotation": [],
        }
        monkeypatch.setattr(
            "tools.grok._grok_search_market",
            lambda *a, **kw: grok_response,
        )

        import tools.grok as grok_tool
        result = grok_tool.search_market("日本株")

        assert result["price_action"] == "日経平均反発"
        assert result.get("source") != "rss"
