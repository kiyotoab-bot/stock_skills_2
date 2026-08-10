"""Grok API Tool — Grok (xAI) 検索ファサード.

tools/ 層は API 呼び出しのみを担う。判断ロジックは含めない。
src/data/grok_client/ の純粋な検索関数を re-export する。
XAI_API_KEY 未設定時は graceful degradation（各関数が空値を返す）。
"""

import sys
from typing import Optional
from pathlib import Path

# プロジェクトルートを sys.path に追加
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

try:
    from src.data.grok_client import (  # noqa: E402
        # 可用性チェック
        is_available,
        get_error_status,
        # 銘柄検索
        search_stock_deep,
        search_x_sentiment,
        # マーケット検索
        search_market as _grok_search_market,
        search_trending_stocks,
        get_trending_themes,
        # 業界検索
        search_industry,
        # ビジネスモデル検索
        search_business,
        # テキスト合成
        synthesize_text,
    )
    # KIK-732: bulk search 並列ラッパー (DeepThink Step 3 用)
    from src.data.grok_client.bulk_search import (  # noqa: E402
        bulk_x_search,
        bulk_web_search,
    )
    HAS_GROK = True
except ImportError:
    HAS_GROK = False


def search_market(market_or_index: str, timeout: Optional[int] = None,
                  context: str = "") -> dict:
    """Grok で市況を検索。失敗時は Google News + NHK RSS にフォールバック。

    timeout=None のとき src.data.grok_client の既定（90秒）に従う。ここに
    独自の既定を持たせると、下層を伸ばしてもファサード経由だけ短いままになる。
    """
    if HAS_GROK:
        kwargs = {"context": context}
        if timeout is not None:
            kwargs["timeout"] = timeout
        result = _grok_search_market(market_or_index, **kwargs)
        # Grok が正常に応答した場合はそのまま返す
        if result.get("price_action") or result.get("raw_response"):
            return result
    # Grok 未設定・失敗 → RSS フォールバック
    try:
        from src.data.news_client import search_market_rss
        return search_market_rss(market_or_index)
    except Exception:
        return {
            "price_action": "", "macro_factors": [], "raw_response": "",
            "sentiment": {"score": 0.0, "summary": ""},
            "upcoming_events": [], "sector_rotation": [], "source": "unavailable",
        }

__all__ = [
    # 可用性
    "is_available",
    "get_error_status",
    # 銘柄
    "search_stock_deep",
    "search_x_sentiment",
    # マーケット
    "search_market",
    "search_trending_stocks",
    "get_trending_themes",
    # 業界
    "search_industry",
    # ビジネスモデル
    "search_business",
    # テキスト合成
    "synthesize_text",
    # KIK-732: bulk 並列
    "bulk_x_search",
    "bulk_web_search",
    # フラグ
    "HAS_GROK",
]
