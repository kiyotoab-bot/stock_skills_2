"""J-Quants API クライアント（個別銘柄需給データ）。

Standard プラン以上で利用可能。
- 個別銘柄の週次信用取引残高（信用買い残・売り残・信用倍率）
- 認証: JQUANTS_API_REFRESH_TOKEN 環境変数（V1）または JQUANTS_API_KEY（V2）
"""

from src.data.jquants_client.margin_interest import get_stock_margin  # noqa: F401
from src.data.jquants_client._client import is_available  # noqa: F401

__all__ = [
    "get_stock_margin",
    "is_available",
]
