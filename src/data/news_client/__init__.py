"""ニュースクライアント（RSS ベース、認証不要）。

Google News RSS + NHK経済ニュース RSS。
Grok API 障害時のフォールバック用。
"""

from src.data.news_client._rss import (  # noqa: F401
    fetch_google_news,
    fetch_nhk_news,
    clear_cache,
)
from src.data.news_client.market_news import search_market_rss  # noqa: F401

__all__ = [
    "fetch_google_news",
    "fetch_nhk_news",
    "search_market_rss",
    "clear_cache",
]
