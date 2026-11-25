"""最新の流通株数を J-Quants から取り、yfinance の株数と照合する材料を足す（KIK-787）.

なぜ要るか: yfinance の ``marketCap`` / ``sharesOutstanding`` は増資の後も古いままのことがある。
2026-11-23 に 5408.T 中山製鋼所が資産バリューの screener で1位になったが、
10/02 の第三者割当（新株 + 自己株処分）の後でも yfinance は 59.9M 株のままで、
正しい流通株 67.3M より 11% 少なく、時価総額が小さく（＝割安に）出ていた。

⚠️ J-Quants の値も**期末時点**（短信の ShOutFY − TrShFY）なので、期末より後の増資は
どちらの出所にも出てこない。ここでやるのは「2つの出所が食い違ったら気づく」ための材料集めで、
正しい株数を保証するものではない。照合と判定は ``value_formulas.reconcile_shares`` /
``value_types.check_share_count``（DQ9）。人が適時開示で確認した値は detail の
``shares_override`` に入れる。

取れないときはキーを足さない（「未照合」として WARN に回る。0 や推定で埋めない）。
"""

from __future__ import annotations

from typing import Any, Optional

from src.data.dilution import POST_PERIOD_DEFAULT_SOURCE, get_share_count_history, iter_share_rows
from src.data.value_formulas import JQ_SHARES_DATE_KEY, JQ_SHARES_KEY  # noqa: F401  (re-export)


def _num(value: Any) -> Optional[float]:
    """float 化。NaN・文字列は None."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def get_latest_share_count(symbol: str) -> Optional[dict]:
    """最新の開示の流通株数（発行済 − 自己株）.

    Returns
    -------
    dict | None
        ``{outstanding, issued, treasury, disclosed, period_type}``。
        取れなければ None。自己株（TrShFY）が取れない行は ``outstanding=None``
        （発行済＝自己株込みで代用すると、自己株の多い会社で株数が過大になる）。
        古い行に自己株があっても遡らない（期がずれた値で照合済にしない）。結果は「未照合」の WARN
    """
    from src.data.jquants_client._client import get_client, is_available
    from src.data.jquants_client.fin_summary import normalize_code

    if not is_available():
        return None
    try:
        df = get_client().get_fin_summary(code=normalize_code(symbol))
    except Exception:  # noqa: BLE001 - API 側の例外は種類が多い
        return None
    if df is None or len(df) == 0:
        return None

    by_date: dict = {}
    for date, row in iter_share_rows(df):
        by_date[date] = row  # 同日重複は後の行（訂正）で上書き（dilution と同じ仮定）
    if not by_date:
        return None

    date = max(by_date)
    row = by_date[date]
    issued = _num(row.get("ShOutFY"))
    treasury = _num(row.get("TrShFY"))
    outstanding = None
    if issued is not None and treasury is not None and 0 <= treasury < issued:
        outstanding = issued - treasury
    period = row.get("CurPerType")
    return {
        "outstanding": outstanding,
        "issued": issued,
        "treasury": treasury,
        "disclosed": date,
        "period_type": str(period) if period is not None else None,
    }


def _is_japanese(symbol: str) -> bool:
    return str(symbol).upper().endswith(".T")


def attach_share_counts(details: dict[str, dict], fetch=get_latest_share_count) -> dict[str, dict]:
    """日本株の detail に J-Quants の流通株数と開示日を足す（その場で更新して返す）.

    value_types の check（AV/EV/CY・DQ9）の**前に**呼ぶ。呼ばなくても判定は動くが、
    全銘柄が「株数未照合」で WARN になる。
    """
    for sym, d in (details or {}).items():
        if d is None or not _is_japanese(sym):
            continue
        # 付け直しで取得に失敗したとき、前回の値を「今の値」として残さない
        d.pop(JQ_SHARES_KEY, None)
        d.pop(JQ_SHARES_DATE_KEY, None)
        rec = fetch(sym)
        if not rec or not rec.get("outstanding"):
            continue
        d[JQ_SHARES_KEY] = rec["outstanding"]
        d[JQ_SHARES_DATE_KEY] = rec.get("disclosed")
    return details


def get_post_period_shares(symbol: str, latest_fn=get_latest_share_count, info_fn=None) -> Optional[dict]:
    """最新短信の流通株数（期末時点）と現在の株数を並べる（EC6 の期末後の比較・KIK-788）.

    現在の株数は yfinance（``value_formulas.shares_outstanding``＝時価総額÷株価）。
    5408.T では 10/02 の第三者割当の新株分が 10/07 に反映されていた（J-Quants は 9/30 期末のまま）。

    Returns
    -------
    dict | None
        ``{base, base_disclosed, latest, latest_source}``。どちらかが取れなければ None
        （EC6 側で「期末より後は未確認」の WARN になる）。
    """
    from src.data.value_formulas import shares_outstanding

    if info_fn is None:
        from src.data.yahoo_client import get_stock_info as info_fn
    try:
        rec = latest_fn(symbol)
    except Exception:  # noqa: BLE001
        rec = None
    if not isinstance(rec, dict):
        return None
    base = _num(rec.get("outstanding"))
    if not base or base <= 0:
        return None
    try:
        info = info_fn(symbol)
    except Exception:  # noqa: BLE001 - 取れなければ未確認に回す
        info = None
    latest = shares_outstanding(info) if isinstance(info, dict) else None
    if not latest or latest <= 0:
        return None
    return {"base": base, "base_disclosed": rec.get("disclosed"), "latest": latest,
            "latest_source": POST_PERIOD_DEFAULT_SOURCE}


def collect_dilution_inputs(symbols, history_fn=get_share_count_history,
                            post_fn=get_post_period_shares) -> tuple[dict, dict]:
    """EC6 の入力をまとめて取る: ``check_dilution(*collect_dilution_inputs(syms))``.

    Returns ``(share_series, post_period)``。日本株以外は期末後の比較の対象外で None を入れる
    （「期末より後は未確認」として WARN に出る。J-Quants が無い以上、黙って PASS にしない）。
    """
    series, post = {}, {}
    for sym in symbols or ():
        series[sym] = history_fn(sym)
        post[sym] = post_fn(sym) if _is_japanese(sym) else None
    return series, post
