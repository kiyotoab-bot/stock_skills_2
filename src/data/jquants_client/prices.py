"""J-Quants 日足・決算発表予定の取得（日本株）。

JPX 公式データなので、yfinance で繰り返し起きた次の問題を回避できる:
  ・最新バーが Close=null で返る（2026-08-04 に84銘柄中83銘柄で発生）
  ・next_earnings が推定値で、過去日付を返すことがある
"""

from datetime import date, timedelta
from typing import Optional

from src.data.jquants_client._client import get_client, is_available
from src.data.jquants_client.fin_summary import normalize_code, _num


def get_daily_bars(symbol: str, days: int = 400) -> dict:
    """日足 OHLCV を取得する（latest last）。

    Returns
    -------
    dict
        ``available`` / ``dates`` / ``closes`` / ``opens`` / ``highs`` /
        ``lows`` / ``volumes`` / ``last_date``。
    """
    if not is_available():
        return {"available": False, "reason": "J-Quants API キーが未設定"}
    try:
        df = get_client().get_eq_bars_daily(code=normalize_code(symbol))
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"[:200]}
    if df is None or len(df) == 0:
        return {"available": False, "reason": "日足データなし"}

    df = df.tail(days)

    def series(*names):
        """列名候補を順に試す。株式分割を跨ぐので調整後（Adj*）を優先する。"""
        for n in names:
            if n in df.columns:
                return [_num(v) for v in df[n].tolist()]
        return []

    dates = [str(v)[:10] for v in df["Date"].tolist()]
    closes = series("AdjC", "C")
    opens = series("AdjO", "O")
    highs = series("AdjH", "H")
    lows = series("AdjL", "L")
    volumes = series("AdjVo", "Vo")
    # 終値が欠損した末尾行は落とす（yfinance で踏んだ Close=null と同種の防御）
    while dates and closes and closes[-1] is None:
        dates.pop(); closes.pop()
        for s in (opens, highs, lows, volumes):
            if s:
                s.pop()
    n = len(dates)
    return {
        "available": True,
        "symbol": symbol,
        "dates": dates,
        "closes": closes[:n],
        "opens": opens[:n],
        "highs": highs[:n],
        "lows": lows[:n],
        "volumes": volumes[:n],
        "last_date": dates[-1] if dates else None,
    }


def get_next_earnings(symbol: str) -> Optional[str]:
    """公表済みの決算発表予定日を返す（YYYY-MM-DD）。

    ⚠️ **None は「当面決算がない」を意味しない。**
    J-Quants の発表予定カレンダーは実測で **翌営業日1日分のみ**（2026-08-05 時点で
    2026-08-06 の267社）を公表する仕様だった。したがってこの関数が答えられるのは
    「この銘柄は直近の公表枠に載っているか」だけで、数ヶ月先の予定は分からない。

    載っていれば JPX の確定情報。載っていなければ ``yahoo_client`` 側の
    ``next_earnings``（推定値・``earnings_date_estimated`` フラグ付き）を使う。
    """
    if not is_available():
        return None
    try:
        df = get_client().get_eq_earnings_cal()
    except Exception:  # noqa: BLE001
        return None
    if df is None or len(df) == 0 or "Code" not in df.columns or "Date" not in df.columns:
        return None

    code = normalize_code(symbol)
    today = date.today()
    hits = []
    for _, row in df.iterrows():
        if normalize_code(str(row["Code"])) != code:
            continue
        d = str(row["Date"])[:10]
        try:
            if date.fromisoformat(d) >= today:
                hits.append(d)
        except ValueError:
            continue
    return min(hits) if hits else None


def get_earnings_calendar() -> list[dict]:
    """公表枠にある全銘柄の決算発表予定（翌営業日分）。

    保有銘柄・ウォッチリストとの突合に使う。
    """
    if not is_available():
        return []
    try:
        df = get_client().get_eq_earnings_cal()
    except Exception:  # noqa: BLE001
        return []
    if df is None or len(df) == 0:
        return []
    return [
        {
            "date": str(r.get("Date", ""))[:10],
            "code": normalize_code(str(r.get("Code", ""))),
            "name": r.get("CoName"),
            "quarter": r.get("FQ"),
            "sector": r.get("SectorNm"),
        }
        for _, r in df.iterrows()
    ]
