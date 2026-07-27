"""RSS ベースの市況ニュース取得（Grok API 代替）。

Grok の search_market() と同じスキーマを返す:
  price_action: str
  macro_factors: list[str]
  sentiment: {score: float, summary: str}
  upcoming_events: list[str]
  sector_rotation: list[str]
  raw_response: str
  source: "rss"  （Grok 結果と区別するための追加フィールド）
"""

from src.data.news_client._rss import fetch_google_news, fetch_nhk_news


def search_market_rss(query: str, max_google: int = 10, max_nhk: int = 6) -> dict:
    """Google News + NHK 経済ニュースから市況サマリーを構築する。

    Args:
        query: 検索クエリ（例: '日本株 相場', '5401.T 日本製鉄', 'S&P500'）

    Returns:
        Grok の EMPTY_MARKET と同スキーマの dict。
    """
    google_items = fetch_google_news(query, max_items=max_google)
    nhk_items = fetch_nhk_news(max_items=max_nhk)

    # price_action: Google News 上位5件のタイトルを改行連結
    top_headlines = [
        f"・{item['title']}" + (f"（{item['source']}）" if item["source"] else "")
        for item in google_items[:5]
    ]
    price_action = "\n".join(top_headlines) if top_headlines else ""

    # macro_factors: NHK 経済ニュースのタイトル
    macro_factors = [item["title"] for item in nhk_items if item["title"]]

    # raw_response: 全取得ヘッドライン（エージェントが参照できるよう全文）
    lines = [f"=== Google News: {query} ==="]
    for item in google_items:
        source_tag = f" [{item['source']}]" if item["source"] else ""
        lines.append(f"{item['title']}{source_tag}")

    if nhk_items:
        lines.append("=== NHK経済ニュース ===")
        for item in nhk_items:
            lines.append(item["title"])

    raw_response = "\n".join(lines)

    return {
        "price_action": price_action,
        "macro_factors": macro_factors,
        "sentiment": {"score": 0.0, "summary": "RSS取得（Grok代替）"},
        "upcoming_events": [],
        "sector_rotation": [],
        "raw_response": raw_response,
        "source": "rss",
    }
