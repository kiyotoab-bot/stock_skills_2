"""Google News RSS + NHK経済ニュース RSS 取得モジュール。

無料・認証不要。Grok API 障害時のフォールバック用。

キャッシュ: インメモリ TTL 60分（同一セッション内の重複取得を防ぐ）。
"""

import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Optional
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; stock-skills-news/1.0)"}
_TIMEOUT = 10
_CACHE_TTL = 3600  # 1時間

_NHK_ECONOMY_RSS = "https://www3.nhk.or.jp/rss/news/cat5.xml"
_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=ja&gl=JP&ceid=JP:ja"

# インメモリキャッシュ: key → (timestamp, data)
_cache: dict = {}


def _is_fresh(key: str) -> bool:
    entry = _cache.get(key)
    return entry is not None and (time.time() - entry[0]) < _CACHE_TTL


def _get_cached(key: str):
    return _cache[key][1] if key in _cache else None


def _set_cache(key: str, data) -> None:
    _cache[key] = (time.time(), data)


def _fetch_rss(url: str) -> Optional[ET.Element]:
    try:
        req = Request(url, headers=_HEADERS)
        with urlopen(req, timeout=_TIMEOUT) as resp:
            content = resp.read()
        return ET.fromstring(content)
    except (URLError, ET.ParseError, Exception) as e:
        print(f"[news_client] RSS fetch error ({url[:60]}): {e}", file=sys.stderr)
        return None


def _parse_items(root: ET.Element, max_items: int) -> list[dict]:
    items = []
    for item in root.findall(".//item")[:max_items]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        source_el = item.find("{https://news.google.com/rss}source")
        source = source_el.text.strip() if source_el is not None and source_el.text else ""
        if title:
            items.append({"title": title, "source": source, "link": link, "published": pub})
    return items


def fetch_google_news(query: str, max_items: int = 10) -> list[dict]:
    """Google News RSS でキーワード検索。returns list of {title, source, link, published}."""
    key = f"google:{query}:{max_items}"
    if _is_fresh(key):
        return _get_cached(key)

    url = _GOOGLE_NEWS_RSS.format(query=quote(query))
    root = _fetch_rss(url)
    result = _parse_items(root, max_items) if root is not None else []
    _set_cache(key, result)
    return result


def fetch_nhk_news(max_items: int = 8) -> list[dict]:
    """NHK経済ニュース RSS を取得。returns list of {title, link, published}."""
    key = f"nhk:{max_items}"
    if _is_fresh(key):
        return _get_cached(key)

    root = _fetch_rss(_NHK_ECONOMY_RSS)
    result = _parse_items(root, max_items) if root is not None else []
    _set_cache(key, result)
    return result


def clear_cache() -> None:
    """テスト用: キャッシュをクリア。"""
    _cache.clear()
