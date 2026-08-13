"""J-Quants API クライアント（JPX 公式データ・日本株）。

- 決算短信の会社予想（予想EPS・予想配当・予想利益）: fin_summary
- 日足 OHLCV / 決算発表予定日: prices
- 個別銘柄の週次信用取引残高: margin_interest（Standard プラン以上）

認証: JQUANTS_API_KEY（V2）または JQUANTS_API_REFRESH_TOKEN（V1）。
`.env` は _client._ensure_env() が自前で読むため、エントリポイントに依存しない。

⚠️ 日本株専用。米国株・指数・為替・商品は yahoo_client を使うこと。
"""

from src.data.jquants_client._client import is_available, reset_client  # noqa: F401
from src.data.jquants_client.fin_summary import (  # noqa: F401
    analyze_revisions,
    get_company_forecast,
    get_forecast_history,
    normalize_code,
)
from src.data.jquants_client.listed import (  # noqa: F401
    get_company_name,
    get_company_names,
    get_listed_info,
)
from src.data.jquants_client.margin_interest import get_stock_margin  # noqa: F401
from src.data.jquants_client.prices import (  # noqa: F401
    get_daily_bars,
    get_earnings_calendar,
    get_next_earnings,
)

__all__ = [
    "is_available",
    "reset_client",
    "get_company_forecast",
    "get_forecast_history",
    "analyze_revisions",
    "get_daily_bars",
    "get_earnings_calendar",
    "get_next_earnings",
    "get_stock_margin",
    "get_company_name",
    "get_company_names",
    "get_listed_info",
    "normalize_code",
]
