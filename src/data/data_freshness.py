"""価格データの基準日を検証する（DQ4 のコード化） — KIK-761.

`checklists.yaml` の DQ4 は「データの基準日を確認したか。最新バーが null で
欠けていないか」と定めているが、**コードが無く目視に委ねられていた**。
そして目視されなかった。

2026-08-15 に判明した実害:
  yfinance が 8/14 のバーを行だけ作って Close=NaN で返し、呼び出し側の
  `df["Close"].dropna()` がその行を落とした。保有・計画6銘柄すべてで
  8/13 の終値が「最新」として RSI・SMA・バンドウォーク・半年期日・
  ストップ距離に入っていた。**警告もエラーも出ない。**

独立レビュー（Gemini, 2026-08-16）の指摘:
  「1日古いデータで全計算を行っていたという事実は、これまで出してきた
    全ての分析・意思決定の根底が誤っていた可能性を示す。単なるバグ修正では
    なく、品質保証プロセスそのものが存在していない」

そこで**計算を始める前に通すゲート**にする。個々の計算を直すのではなく、
入力が正しい日付かを最初に確かめる。

check_data_freshness : 銘柄ごとの最新バー日付を期待営業日と突き合わせる
last_trading_day     : 直近の営業日（J-Quants 市場カレンダー）
"""

from __future__ import annotations

import datetime
from typing import Optional, Sequence

# J-Quants 市場カレンダーの HolDiv: "1"=営業日 / "0"=非営業日 / "3"=祝日
_BUSINESS_DAY = "1"

# 何営業日ずれたら警告か
STALE_WARN_DAYS = 1     # 1営業日ずれたら WARN
STALE_FAIL_DAYS = 3     # 3営業日以上ずれたら FAIL

_CALENDAR_CACHE: Optional[list] = None


def _load_calendar() -> list:
    """J-Quants 市場カレンダーを [(date, is_business)] で返す。失敗時は空。"""
    global _CALENDAR_CACHE
    if _CALENDAR_CACHE is not None:
        return _CALENDAR_CACHE

    out = []
    try:
        from src.data.jquants_client._client import get_client

        client = get_client()
        if client is not None:
            df = client.get_mkt_calendar()
            if df is not None and len(df):
                for row in df.to_dict("records"):
                    d = str(row.get("Date") or "")[:10]
                    if d:
                        out.append((d, str(row.get("HolDiv")) == _BUSINESS_DAY))
                out.sort(key=lambda x: x[0])
    except Exception:
        pass

    _CALENDAR_CACHE = out
    return out


def reset_cache() -> None:
    """カレンダーのプロセス内キャッシュを捨てる（テスト用）。"""
    global _CALENDAR_CACHE
    _CALENDAR_CACHE = None


def last_trading_day(today: Optional[datetime.date] = None) -> Optional[str]:
    """``today`` 以前で直近の営業日（ISO文字列）。カレンダーが無ければ None。

    ⚠️ 「今日が営業日なら今日」を返す。日中に呼べば当日のバーはまだ確定
    していないので、呼び出し側は当日と前営業日の**両方**を許容する。
    """
    today = today or datetime.date.today()
    cal = _load_calendar()
    if not cal:
        return None
    iso = today.isoformat()
    for d, is_biz in reversed(cal):
        if d <= iso and is_biz:
            return d
    return None


def _business_days_between(start: str, end: str) -> Optional[int]:
    """start（排他）から end（包含）までの営業日数。カレンダーが無ければ None。"""
    cal = _load_calendar()
    if not cal:
        return None
    return sum(1 for d, is_biz in cal if is_biz and start < d <= end)


def check_data_freshness(
    latest_by_symbol: dict,
    today: Optional[datetime.date] = None,
    nan_tail_by_symbol: Optional[dict] = None,
) -> list[dict]:
    """各銘柄の最新バー日付を期待営業日と突き合わせる。

    Parameters
    ----------
    latest_by_symbol : dict
        ``{symbol: "YYYY-MM-DD"}``。``df["Close"].dropna()`` の最終日を渡す。
        **dropna する前ではなく後**の日付を渡すこと——NaN 行が残ったままだと
        「最新バーはある」と誤判定する。
    nan_tail_by_symbol : dict | None
        ``{symbol: bool}``。末尾が NaN だったかどうか。渡すと補完の有無を
        別立てで報告する（日本株は KIK-759 の _patch_latest_bar が補う）。

    Returns
    -------
    list[dict]
        ``_result`` 形式（id / status / detail）。id は "DQ4"。
    """
    from src.data.checklist_review import FAIL, NA, PASS, WARN, _result

    today = today or datetime.date.today()
    if not latest_by_symbol:
        return [_result("DQ4", NA, "検証対象の銘柄がない")]

    expected = last_trading_day(today)
    if expected is None:
        # カレンダーが無いときは銘柄間の相対比較に落とす。
        # 全銘柄が同じ日付なら、少なくとも「一部だけ古い」状態ではない。
        dates = sorted(set(v for v in latest_by_symbol.values() if v))
        if len(dates) <= 1:
            return [_result("DQ4", NA,
                            f"市場カレンダー未取得。全{len(latest_by_symbol)}銘柄が "
                            f"{dates[0] if dates else '不明'} で揃っている")]
        newest = dates[-1]
        lagging = [s for s, d in latest_by_symbol.items() if d != newest]
        return [_result("DQ4", WARN,
                        f"市場カレンダー未取得。最新 {newest} に対し "
                        f"{len(lagging)}銘柄が古い: {', '.join(sorted(lagging)[:5])}")]

    stale = {}
    for sym, d in latest_by_symbol.items():
        if not d:
            stale[sym] = None
            continue
        if d >= expected:
            continue
        lag = _business_days_between(d, expected)
        stale[sym] = lag

    results = []
    if stale:
        worst = max((v for v in stale.values() if v is not None), default=None)
        status = FAIL if (worst is not None and worst >= STALE_FAIL_DAYS) else WARN
        detail = ", ".join(
            f"{s}({'日付なし' if v is None else str(v) + '営業日'})"
            for s, v in sorted(stale.items())[:6]
        )
        results.append(_result(
            "DQ4", status,
            f"期待 {expected} に対し {len(stale)}/{len(latest_by_symbol)}銘柄が古い: {detail}"
            "  ← この状態で計算すると全指標が過去日のものになる",
        ))
    else:
        results.append(_result(
            "DQ4", PASS,
            f"{len(latest_by_symbol)}銘柄すべて最新営業日 {expected} のバーを保持",
        ))

    if nan_tail_by_symbol:
        patched = sorted(s for s, was_nan in nan_tail_by_symbol.items() if was_nan)
        if patched:
            results.append(_result(
                "DQ4", PASS if not stale else WARN,
                f"末尾 NaN を検出し補完: {', '.join(patched[:6])}"
                "（yfinance が最新バーを Close=null で返す既知の挙動）",
            ))
    return results
