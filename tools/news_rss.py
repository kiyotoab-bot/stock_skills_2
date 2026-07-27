"""News RSS Tool — Google News + NHK経済ニュース ファサード。

認証不要の無料RSSソース。Grok API の代替として使用。
tools/ 層は取得のみを担う。判断ロジックは含めない。
"""

import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

try:
    from src.data.news_client import (  # noqa: E402
        fetch_google_news,
        fetch_nhk_news,
        search_market_rss,
        clear_cache,
    )
    HAS_NEWS_RSS = True
except ImportError:
    HAS_NEWS_RSS = False

    def fetch_google_news(query: str, max_items: int = 10) -> list:
        return []

    def fetch_nhk_news(max_items: int = 8) -> list:
        return []

    def search_market_rss(query: str, **kwargs) -> dict:
        return {"price_action": "", "macro_factors": [], "sentiment": {"score": 0.0, "summary": ""},
                "upcoming_events": [], "sector_rotation": [], "raw_response": "", "source": "rss"}

    def clear_cache() -> None:
        pass


__all__ = [
    "fetch_google_news",
    "fetch_nhk_news",
    "search_market_rss",
    "clear_cache",
    "HAS_NEWS_RSS",
]
