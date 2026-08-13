"""J-Quants Tool — JPX 公式データ（日本株）のファサード。

tools/ 層は外部 API 接続のみを担う。判断ロジックは含めない。
src/data/jquants_client/ の純粋なデータ取得関数を re-export する。

■ 何に使うか
  get_company_forecast : 決算短信の会社予想（予想EPS・予想配当・予想利益）
                         **日本株の予想値はこれを一次情報とする。**
  get_forecast_history : 会社予想の改訂履歴（上方/下方修正の追跡）
  get_daily_bars       : 日足 OHLCV（JPX公式。yfinance の Close=null 問題を回避）
  get_next_earnings    : 公表済みの決算発表予定日
  get_earnings_calendar: 翌営業日に決算発表する全銘柄
  get_stock_margin     : 週次信用取引残高

■ なぜ yfinance より優先するか（2026-08-05 の実測）
  yfinance の予想値は第三者推定で、検証5銘柄のうち2件（40%）が誤りだった。
    6436.T アマノ  dividendRate 250円（会社予想180円）→ 利回りを 6.44% と誤認し推奨に載せた
    6701.T 日本電気 forwardEps 718.96（会社予想の約3.3倍）→ 予想PER 6.4 と誤認
  J-Quants は決算短信そのものなので、取得できる限りこちらが正しい。

■ 制約
  ・**日本株のみ**。米国株・指数・為替・商品は tools/yahoo_finance.py を使う
  ・IFRS/Non-GAAP 開示だと予想EPS/純利益が空になることがある
    （実測: 6701 日本電気 / 4568 第一三共 / 9364 上組）。その場合は yfinance にフォールバックする
  ・決算発表予定カレンダーは**翌営業日1日分のみ**の公表。数ヶ月先は分からない
  ・決算詳細 API・配当専用 API は現行プランでは 403

■ 認証
  JQUANTS_API_KEY または JQUANTS_API_REFRESH_TOKEN。
  `.env` は src/data/jquants_client/_client._ensure_env() が自前で読むため、
  どの経路から import しても有効（2026-08-05 まではこのファイル経由でしか
  読まれず、src/data/ から直接使うと常に無効化されていた）。
"""

import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

try:
    from src.data.jquants_client import (  # noqa: E402
        analyze_revisions,
        get_company_forecast,
        get_daily_bars,
        get_earnings_calendar,
        get_forecast_history,
        get_next_earnings,
        get_stock_margin,
        get_company_name,
        get_company_names,
        get_listed_info,
        is_available,
        normalize_code,
    )
    HAS_JQUANTS = True
except ImportError:
    HAS_JQUANTS = False

    def _unavailable(*_args, **_kwargs) -> dict:
        return {"available": False, "error": "jquants-api-client not installed"}

    get_company_forecast = _unavailable
    get_daily_bars = _unavailable
    get_stock_margin = _unavailable

    def get_forecast_history(*_args, **_kwargs) -> list:
        return []

    def analyze_revisions(*_args, **_kwargs) -> dict:
        return {"revision_in_fy": None, "yoy_guidance": None}

    def get_earnings_calendar(*_args, **_kwargs) -> list:
        return []

    def get_next_earnings(*_args, **_kwargs):
        return None

    def is_available() -> bool:
        return False

    def normalize_code(symbol: str) -> str:
        return str(symbol).split(".")[0]


__all__ = [
    "get_company_forecast",
    "get_forecast_history",
    "analyze_revisions",
    "get_daily_bars",
    "get_next_earnings",
    "get_earnings_calendar",
    "get_stock_margin",
    "is_available",
    "normalize_code",
    "HAS_JQUANTS",
]
