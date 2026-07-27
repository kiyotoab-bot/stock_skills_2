"""JPX公開データクライアント。

需給動向（信用取引残高・投資主体別売買・空売り出来高）を取得する。
データはJPX公式ページからスクレイピングして取得。
取得失敗時は graceful degradation（available=False）。
"""

import requests  # noqa: F401  テストパッチ用

from src.data.jpx_client._common import (  # noqa: F401
    get_error_status,
    is_available,
    reset_error_state,
)
from src.data.jpx_client._cache import (  # noqa: F401
    CACHE_DIR,
    date_key,
    read_cache,
    week_key,
    write_cache,
)
from src.data.jpx_client.investor_type import get_investor_type  # noqa: F401
from src.data.jpx_client.margin import get_margin  # noqa: F401
from src.data.jpx_client.short_selling import get_short_selling  # noqa: F401


def get_demand_supply() -> dict:
    """需給動向の全指標をまとめて返す。

    各サブモジュールを呼び出し、結果を統合する。
    いずれかが失敗しても available=True を維持し、失敗部分のみ None を設定する。

    Returns:
        {
            margin: {...},         # 信用取引残高
            investor_type: {...},  # 投資主体別売買動向
            short_selling: {...},  # 空売り出来高
            available: bool,
            error: str | None,     # 全て成功時 None、1件でも失敗時は最初のエラーメッセージ
        }
    """
    margin = get_margin()
    investor = get_investor_type()
    short = get_short_selling()

    errors = [
        x.get("error") for x in [margin, investor, short] if x.get("error")
    ]
    first_error = errors[0] if errors else None

    def _strip_meta(d: dict) -> dict:
        return {k: v for k, v in d.items() if k not in ("available", "error")}

    return {
        "margin": _strip_meta(margin),
        "investor_type": _strip_meta(investor),
        "short_selling": _strip_meta(short),
        "available": True,
        "error": first_error,
    }


__all__ = [
    "get_demand_supply",
    "get_margin",
    "get_investor_type",
    "get_short_selling",
    "is_available",
    "get_error_status",
    "reset_error_state",
    "CACHE_DIR",
    "week_key",
    "date_key",
    "read_cache",
    "write_cache",
]
