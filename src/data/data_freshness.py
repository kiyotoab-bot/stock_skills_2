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


# ---------------------------------------------------------------------------
# DQ8: 系列の途中の欠落 (KIK-773)
# ---------------------------------------------------------------------------

# 何本欠けたら何を出すか
GAP_WARN_BARS = 1     # 1本でも欠けたら WARN
GAP_FAIL_BARS = 3     # 3本以上欠けたら FAIL

# 既定の検査窓（営業日）
GAP_LOOKBACK = 30


def check_series_gaps(
    dates_by_symbol: dict,
    today: Optional[datetime.date] = None,
    lookback: int = GAP_LOOKBACK,
) -> list[dict]:
    """DQ8: 価格系列の**途中**に欠落した営業日が無いかを見る（KIK-773）.

    ⚠️ **DQ4 では捕まらない。** DQ4 は最新バーの日付しか見ないので、
    系列の途中が抜けていても最新日が正しければ PASS を返す。

    2026-08-31 に判明した実害:
      yfinance の ``^N225`` は **2026-08-28 のバーが丸ごと欠落**していた。
      最新バーは 2026-08-31 で正しいため DQ4 は PASS。しかし「前日比」が
      8/27 との比較になり、**+0.27% と報告した（正しくは -0.14%）**。
      Grok の報道値 -93.63円 と食い違って初めて気づいた。
      J-Quants の TOPIX には 8/28 があり、そちらは正しかった。

    前日比だけの問題ではない。欠落は RSI・SMA・σ・バンドウォーク・
    ストップ距離のすべてに静かに入り込む。**警告もエラーも出ない。**

    Parameters
    ----------
    dates_by_symbol : dict
        ``{symbol: [ISO日付, ...]}``。``df["Close"].dropna().index`` を
        ISO文字列にして渡す。**dropna した後**を渡すこと——NaN 行が
        残ったままだと「バーはある」と誤判定する（DQ4 と同じ理由）。
    lookback : int
        直近何営業日を検査するか。既定 30。古い期間の歯抜けは
        銘柄の上場時期や取引停止など正当な理由があるので見ない。

    Returns
    -------
    list[dict]
        ``_result`` 形式（id / status / detail）。id は "DQ8"。
        カレンダーが取れないときは NA（銘柄間の相対比較はしない——
        全銘柄が同じ日を落としている可能性があり、検知にならない）。
    """
    from src.data.checklist_review import FAIL, NA, PASS, WARN, _result

    today = today or datetime.date.today()
    if not dates_by_symbol:
        return [_result("DQ8", NA, "検証対象の銘柄がない")]

    cal = _load_calendar()
    if not cal:
        return [_result("DQ8", NA, "市場カレンダー未取得。系列の欠落は検証できない")]

    iso = today.isoformat()
    business = [d for d, is_biz in cal if is_biz and d <= iso]
    if not business:
        return [_result("DQ8", NA, "市場カレンダーに営業日がない")]
    window = business[-lookback:]

    gaps: dict[str, list[str]] = {}
    checked = 0
    for sym, dates in dates_by_symbol.items():
        have = {str(d)[:10] for d in (dates or [])}
        if not have:
            continue
        # 系列が始まる前・終わったあとは欠落ではない。重なる範囲だけを見る。
        first, last = min(have), max(have)
        target = [d for d in window if first <= d <= last]
        if not target:
            continue
        checked += 1
        missing = [d for d in target if d not in have]
        if missing:
            gaps[sym] = missing

    if not checked:
        return [_result("DQ8", NA, "検査窓に重なる系列がない")]

    if not gaps:
        return [_result("DQ8", PASS,
                        f"{checked}銘柄すべて直近{len(window)}営業日に欠落なし")]

    worst = max(len(v) for v in gaps.values())
    status = FAIL if worst >= GAP_FAIL_BARS else WARN
    detail = " / ".join(
        f"{s} {len(v)}本欠落 ({', '.join(v[:3])}{'...' if len(v) > 3 else ''})"
        for s, v in sorted(gaps.items())[:6]
    )
    return [_result(
        "DQ8", status,
        f"系列の途中に欠落: {detail}"
        "  ← 前日比・RSI・SMA・σ が静かにずれる。DQ4 は最新バーしか見ないので通る",
    )]
