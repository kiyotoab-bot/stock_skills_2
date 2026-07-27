"""個別銘柄の週次信用取引残高取得（J-Quants API）。

J-Quants `/v2/markets/margin-interest` エンドポイントを使用。
Standard プラン以上が必要。

フィールド:
  ShrtVol  = 信用売り残（融資残高ではなく貸株残高）（株数）
  LongVol  = 信用買い残（融資残高）（株数）
  信用倍率 = LongVol / ShrtVol
"""

import sys
from datetime import datetime, timedelta
from typing import Optional

from src.data.jquants_client._client import get_client, is_available

_EMPTY = {
    "code": None,
    "long_vol": None,
    "shrt_vol": None,
    "margin_ratio": None,
    "wow_change_pct": None,
    "date": None,
    "available": False,
    "error": None,
}


def _normalize_code(symbol: str) -> str:
    """'5401.T' → '54010'、'5401' → '54010'（東証プライム）。"""
    code = symbol.upper().replace(".T", "").replace(".JP", "")
    if len(code) == 4 and code.isdigit():
        code = code + "0"
    return code


def get_stock_margin(symbol: str) -> dict:
    """個別銘柄の最新週次信用取引残高を返す。

    Args:
        symbol: ティッカー（例: '5401.T', '7203.T', '54010'）

    Returns:
        {
            code: str,                  # 5桁コード
            long_vol: int | None,       # 信用買い残（株数）
            shrt_vol: int | None,       # 信用売り残（株数）
            margin_ratio: float | None, # 信用倍率 (long/shrt)
            wow_change_pct: float | None, # 前週比（%）
            date: str | None,           # "2026-04-24"
            available: bool,
            error: str | None,
        }
    """
    if not is_available():
        return {**_EMPTY, "error": "JQUANTS_API_REFRESH_TOKEN not set"}

    code = _normalize_code(symbol)

    try:
        client = get_client()
        # 直近3週分を取得して最新と前週を比較
        to_date = datetime.now()
        from_date = to_date - timedelta(days=21)
        df = client.get_mkt_margin_interest(
            code=code,
            from_yyyymmdd=from_date.strftime("%Y%m%d"),
            to_yyyymmdd=to_date.strftime("%Y%m%d"),
        )
    except Exception as e:
        print(f"[jquants_client] margin_interest fetch error: {e}", file=sys.stderr)
        return {**_EMPTY, "code": code, "error": str(e)}

    if df is None or df.empty:
        return {**_EMPTY, "code": code, "error": f"no data for {code}"}

    latest = df.iloc[-1]
    long_vol = int(latest["LongVol"]) if latest["LongVol"] else None
    shrt_vol = int(latest["ShrtVol"]) if latest["ShrtVol"] else None
    date_str = str(latest["Date"])[:10] if latest["Date"] is not None else None

    margin_ratio = None
    if long_vol and shrt_vol and shrt_vol > 0:
        margin_ratio = round(long_vol / shrt_vol, 2)

    wow_change_pct = None
    if len(df) >= 2:
        prev = df.iloc[-2]
        prev_long = prev["LongVol"]
        prev_shrt = prev["ShrtVol"]
        if prev_long and prev_shrt and float(prev_shrt) > 0:
            prev_ratio = float(prev_long) / float(prev_shrt)
            if margin_ratio and prev_ratio > 0:
                wow_change_pct = round((margin_ratio - prev_ratio) / prev_ratio * 100, 1)

    return {
        "code": code,
        "long_vol": long_vol,
        "shrt_vol": shrt_vol,
        "margin_ratio": margin_ratio,
        "wow_change_pct": wow_change_pct,
        "date": date_str,
        "available": True,
        "error": None,
    }
