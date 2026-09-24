"""個別銘柄の信用取引残高取得（J-Quants API）。

J-Quants `/v2/markets/margin-interest` エンドポイントを使用。
Standard プラン以上が必要。

⚠️ **2026-09-28 に同じエンドポイントが週次 → 日次に変わった**（KIK-776）。
  - 2026-09-25 申込分以降: 毎営業日の残高（Date = 申込日、翌営業日に公表）。
    公表日 ``PubDate`` と金額6項目（``ShrtVal`` / ``LongVal`` 等）が追加。
  - それ以前: 週末（金曜）残高のまま。履歴を遡ると週次行と日次行が混在する。

このため「前週比」を **隣接2行の比較で出してはいけない**。日次化後は隣接行が
前日になり、週次で較正した閾値（PO7 / SD1 の +50%）が事実上効かなくなる。
前週比は Date で「7日以上前の最も近い行」を探して出す（週次・日次どちらでも同じ
意味になる）。前日比は別キー ``dod_change_pct`` に分ける。

フィールド:
  ShrtVol  = 信用売り残（貸株残高）（株数）
  LongVol  = 信用買い残（融資残高）（株数）
  ShrtVal / LongVal = 同・金額（2026-09-25 申込分以降のみ）
  信用倍率 = LongVol / ShrtVol
"""

import sys
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from src.data.jquants_client._client import get_client, is_available

#: 取得窓（暦日）。前週比の基準行（7日以上前）を週次・日次どちらでも確実に含める。
FETCH_WINDOW_DAYS = 35
#: ``history`` に入れる行数（最新から遡る）。
HISTORY_ROWS = 5
#: 行間隔（暦日）の中央値がこれ以下なら日次データとみなす（週次は 5〜7 日）。
#: 連休明けの1本だけ 5〜6 日空く日次行で週次と誤判定しないよう、最新2行ではなく
#: 直近数行の中央値で見る（レビュー M1 / m1）。
_DAILY_GAP_MAX_DAYS = 4
#: frequency 判定に使う行数（最新から）。
_FREQ_SAMPLE_ROWS = 4
#: 前週比の基準（日次データのとき）: 最新 Date からこの日数以上前で最も近い行。
_WOW_MIN_GAP_DAYS = 7
#: 前日比の基準: 直前行がこの日数以内なら営業日ベースで隣接とみなす（連休明けも拾う）。
_DOD_GAP_MAX_DAYS = 6

_EMPTY = {
    "code": None,
    "long_vol": None,
    "shrt_vol": None,
    "margin_ratio": None,
    "wow_change_pct": None,
    "wow_basis_date": None,
    "dod_change_pct": None,
    "long_val": None,
    "shrt_val": None,
    "date": None,
    "pub_date": None,
    "frequency": None,
    "history": [],
    "available": False,
    "error": None,
}


def _normalize_code(symbol: str) -> str:
    """'5401.T' → '54010'、'5401' → '54010'（東証プライム）。"""
    code = symbol.upper().replace(".T", "").replace(".JP", "")
    if len(code) == 4 and code.isdigit():
        code = code + "0"
    return code


def _num(value) -> Optional[float]:
    """NaN / None / 空文字を None に、それ以外を float に。"""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value) -> Optional[int]:
    f = _num(value)
    return int(f) if f is not None else None


def _ratio(long_vol, shrt_vol) -> Optional[float]:
    """信用倍率 = 買い残 / 売り残。売り残が 0 か欠損なら None。"""
    lv, sv = _num(long_vol), _num(shrt_vol)
    if lv is None or sv is None or sv <= 0:
        return None
    return lv / sv


def _pct_change(curr: Optional[float], prev: Optional[float]) -> Optional[float]:
    if curr is None or prev is None or prev <= 0:
        return None
    return round((curr - prev) / prev * 100, 1)


def _empty(code: Optional[str] = None, error: Optional[str] = None) -> dict:
    """エラー戻り値。``history`` のリストを呼び出しごとに切る（共有しない）。"""
    return {**_EMPTY, "history": [], "code": code, "error": error}


def _date_str(value) -> Optional[str]:
    """日付らしい値を "YYYY-MM-DD" に正規化する。"20260925" / datetime / 文字列いずれも可。"""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    ts = pd.to_datetime(value, errors="coerce")
    if ts is pd.NaT or ts is None:
        return None
    return ts.strftime("%Y-%m-%d")


def _row_dict(row: pd.Series) -> dict:
    """1行を出力用 dict に。金額・公表日は日次化前の行では null なので欠損を許す。"""
    ratio = _ratio(row.get("LongVol"), row.get("ShrtVol"))
    return {
        "date": row["_dt"].strftime("%Y-%m-%d"),
        "pub_date": _date_str(row.get("PubDate")),
        "long_vol": _int_or_none(row.get("LongVol")),
        "shrt_vol": _int_or_none(row.get("ShrtVol")),
        "long_val": _num(row.get("LongVal")),
        "shrt_val": _num(row.get("ShrtVal")),
        # 買い残 0 は「買い残ゼロ」として 0.0 を返す（旧実装は None にしていた）。
        "margin_ratio": round(ratio, 2) if ratio is not None else None,
    }


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Date 昇順に並べ、日付を datetime にして重複行を落とす。

    ``Date`` 列が無いフレームは呼び出し側で弾く（``summarize_margin_frame``）。
    """
    out = df.copy()
    out["_dt"] = pd.to_datetime(out["Date"], errors="coerce")
    out = out.dropna(subset=["_dt"]).sort_values("_dt", kind="stable")
    out = out.drop_duplicates(subset=["_dt"], keep="last").reset_index(drop=True)
    return out


def _detect_frequency(df: pd.DataFrame) -> Optional[str]:
    """直近数行の行間隔の中央値で日次 / 週次を判定する。1行しか無ければ None。

    最新2行だけで見ると、連休明けの日次行（5〜6日空く）を週次と誤判定し、
    逆に金曜休場で申込日がずれた週次行（5〜6日間隔）を日次と誤判定する。
    中央値なら1本の外れ値に引きずられない。
    """
    if len(df) < 2:
        return None
    tail = df["_dt"].tail(_FREQ_SAMPLE_ROWS)
    gaps = tail.diff().dropna().dt.days
    return "daily" if float(gaps.median()) <= _DAILY_GAP_MAX_DAYS else "weekly"


def _wow_basis(df: pd.DataFrame, frequency: Optional[str]) -> Optional[pd.Series]:
    """前週比の基準行。

    - 週次データ: 隣接行（前週の申込日）。金曜休場で申込日が木曜にずれた週でも
      「7日以上前」ルールだと前々週を拾ってしまうので隣接行を使う（レビュー M1）。
    - 日次データ: 最新 Date から 7 日以上前で最も近い行（先週の同じ曜日、休日なら手前）。
      週次行と日次行が混在していても同じ規則で引ける。
    """
    if len(df) < 2:
        return None
    if frequency == "weekly":
        return df.iloc[-2]
    latest_dt = df["_dt"].iloc[-1]
    cutoff = latest_dt - timedelta(days=_WOW_MIN_GAP_DAYS)
    older = df[df["_dt"] <= cutoff]
    if older.empty:
        return None
    return older.iloc[-1]


def _dod_basis(df: pd.DataFrame, frequency: Optional[str]) -> Optional[pd.Series]:
    """前日比の基準行: 日次データで、直前の行が営業日ベースで隣接しているときだけ。"""
    if frequency != "daily" or len(df) < 2:
        return None
    gap = (df["_dt"].iloc[-1] - df["_dt"].iloc[-2]).days
    if gap > _DOD_GAP_MAX_DAYS:
        return None
    return df.iloc[-2]


def summarize_margin_frame(df: pd.DataFrame, code: Optional[str] = None,
                           history_rows: int = HISTORY_ROWS) -> dict:
    """J-Quants の margin-interest DataFrame を集約する（純粋関数・テスト用入口）。

    障害はすべて ``available=False`` + ``error`` で返し、例外を外に出さない
    （呼び出し側の ``_margin_result`` / ``detect_alerts`` は ``available`` で縮退する）。
    """
    if df is None or df.empty:
        return _empty(code, f"no data for {code}")
    if "Date" not in df.columns:
        return _empty(code, f"Date column missing for {code} (columns={list(df.columns)})")

    d = _prepare(df)
    if d.empty:
        return _empty(code, f"no dated rows for {code}")
    dropped = len(df) - len(d)

    latest = d.iloc[-1]
    latest_ratio = _ratio(latest.get("LongVol"), latest.get("ShrtVol"))
    frequency = _detect_frequency(d)

    wow_row = _wow_basis(d, frequency)
    wow_ratio = _ratio(wow_row.get("LongVol"), wow_row.get("ShrtVol")) if wow_row is not None else None
    dod_row = _dod_basis(d, frequency)
    dod_ratio = _ratio(dod_row.get("LongVol"), dod_row.get("ShrtVol")) if dod_row is not None else None

    head = _row_dict(latest)
    return {
        "code": code if code is not None else str(latest.get("Code") or "") or None,
        "long_vol": head["long_vol"],
        "shrt_vol": head["shrt_vol"],
        "margin_ratio": head["margin_ratio"],
        "wow_change_pct": _pct_change(latest_ratio, wow_ratio),
        "wow_basis_date": wow_row["_dt"].strftime("%Y-%m-%d") if wow_row is not None else None,
        "dod_change_pct": _pct_change(latest_ratio, dod_ratio),
        "long_val": head["long_val"],
        "shrt_val": head["shrt_val"],
        "date": head["date"],
        "pub_date": head["pub_date"],
        "frequency": frequency,
        "history": [_row_dict(r) for _, r in d.tail(history_rows).iterrows()],
        "available": True,
        # 日付が読めず落とした行があれば残す（書式混在の診断用）。無ければ None。
        "error": f"{dropped} rows dropped (unparseable Date)" if dropped else None,
    }


def get_stock_margin(symbol: str) -> dict:
    """個別銘柄の最新の信用取引残高を返す（日次化対応・KIK-776）。

    Args:
        symbol: ティッカー（例: '5401.T', '7203.T', '54010'）

    Returns:
        {
            code: str,                    # 5桁コード
            long_vol: int | None,         # 信用買い残（株数）
            shrt_vol: int | None,         # 信用売り残（株数）
            margin_ratio: float | None,   # 信用倍率 (long/shrt)
            wow_change_pct: float | None, # 前週比（%）。基準は 7 日以上前の最も近い行
            wow_basis_date: str | None,   # 前週比の基準行の Date
            dod_change_pct: float | None, # 前日比（%）。日次データのときだけ入る
            long_val: float | None,       # 信用買い残（金額・円）。2026-09-25 以降のみ
            shrt_val: float | None,       # 信用売り残（金額・円）。同上
            date: str | None,             # 申込日 "2026-09-25"
            pub_date: str | None,         # 公表日。2026-09-25 以降のみ
            frequency: "daily" | "weekly" | None,
            history: list[dict],          # 直近 HISTORY_ROWS 行（古い順）
            available: bool,
            error: str | None,
        }

    ⚠️ ``wow_change_pct`` の意味は日次化の前後で変えない。PO7 / SD1 の
    「前週比 +50% 超」と detect_alerts の margin_surge はこの値を見る。
    """
    if not is_available():
        return _empty(None, "JQUANTS_API_REFRESH_TOKEN not set")

    code = _normalize_code(symbol)

    try:
        client = get_client()
        to_date = datetime.now()
        from_date = to_date - timedelta(days=FETCH_WINDOW_DAYS)
        df = client.get_mkt_margin_interest(
            code=code,
            from_yyyymmdd=from_date.strftime("%Y%m%d"),
            to_yyyymmdd=to_date.strftime("%Y%m%d"),
        )
    except Exception as e:
        print(f"[jquants_client] margin_interest fetch error: {e}", file=sys.stderr)
        return _empty(code, str(e))

    return summarize_margin_frame(df, code=code)
