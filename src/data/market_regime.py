"""Market regime indicators for Japanese equity analysis.

calc_nikkei_usd      : ドル建て日経平均（日経225 ÷ USDJPY）の水準・変化率
calc_jp_us_relative  : ドル建て日経 vs S&P500 の相対強度
calc_nt_ratio        : NT倍率（日経225 ÷ TOPIX）
calc_nikkei_per_signal: 日経225 PER の水準評価
calc_nikkei_fair_value: 日経225 の理論株価バンド（EPS × PER）
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

NIKKEI_USD_THRESHOLDS = {
    "rising":  3.0,   # >= +3% → 上昇（円高 or 日経高でドル建て上昇）
    "falling": -3.0,  # <= -3% → 下落（円安 or 日経安でドル建て下落）
}

NIKKEI_PER_THRESHOLDS = {
    "bubble":     25.0,  # >= 25倍 → バブル警告（CRITICAL）
    "overvalued": 20.0,  # >= 20倍 → 割高注意（INFO）
    "cheap":      13.0,  # <= 13倍 → 割安シグナル（INFO）
    # 13〜20倍: 正常レンジ
}

NT_THRESHOLDS = {
    "nikkei_heavy": 15.5,  # NT >= 15.5 → 日経225過熱（大型・ハイテク集中）
    "topix_heavy": 13.0,   # NT < 13.0  → TOPIX優位（広範株優勢）
}

JP_US_THRESHOLDS = {
    "japan_favorable": 3.0,   # Nikkei_USD outperforms SPX by >= 3% → Japan
    "us_favorable": -3.0,     # SPX outperforms Nikkei_USD by >= 3% → US
}


# ---------------------------------------------------------------------------
# Series alignment (KIK-727)
# ---------------------------------------------------------------------------

def _date_key(value) -> str:
    """Normalise a date-like value to a ``YYYY-MM-DD`` string.

    tz-aware な ``pd.Timestamp`` 同士は、同じ暦日でもタイムゾーンが違うと
    等価にならずハッシュも一致しない。``get_price_history`` は yfinance の
    DataFrame をそのまま返し、その index は取引所ローカルの tz-aware なので、
    最も自然な ``df.index.tolist()`` を渡すと ^N225(Asia/Tokyo) と
    ^GSPC(America/New_York) の積集合が空になり、例外も警告も出さずに
    「データ不足」へ落ちる。暦日で正規化してこれを防ぐ。
    """
    if hasattr(value, "date"):
        try:
            return value.date().isoformat()
        except (TypeError, ValueError):
            pass
    return str(value)[:10]


def align_by_dates(
    series: list[tuple[list, list[float]]],
) -> tuple[list, list[list[float]]]:
    """Align multiple (dates, values) series on their common dates.

    ^N225 / USDJPY=X / ^GSPC はそれぞれ営業日が異なる（日本の祝日、米国の
    祝日、為替はほぼ無休）。旧実装は ``list[-n:]`` で末尾から位置合わせして
    おり、実測で N225↔USDJPY の 92%、N225↔S&P500 の 80% のペアが別々の
    日付を突き合わせていた。米国市場が未終了の日は「最新」同士ですら
    別日（例: N225=7/27 に対し S&P500=7/24）になる。

    Parameters
    ----------
    series : list[tuple[list, list[float]]]
        ``(dates, values)`` のリスト。dates は ``datetime.date`` /
        ``datetime.datetime`` / ``pd.Timestamp``（tz 有無・混在可） /
        ``"YYYY-MM-DD"`` 文字列を受け付ける。内部で暦日に正規化する。
        dates と values の長さが違う場合は **末尾を残して** 揃える
        （本モジュールは全体が latest-last 規約のため）。

    Returns
    -------
    tuple[list, list[list[float]]]
        共通日付（``YYYY-MM-DD`` 文字列、昇順）と、対応する各系列の値。
    """
    if not series:
        return [], []

    maps = []
    for dates, values in series:
        n = min(len(dates), len(values))
        # latest-last: 長さが違うときは古い方ではなく末尾を残す。
        keys = [_date_key(d) for d in dates[-n:]] if n else []
        vals = list(values[-n:]) if n else []
        maps.append(dict(zip(keys, vals)))

    common = set(maps[0])
    for m in maps[1:]:
        common &= set(m)
    ordered = sorted(common)
    return ordered, [[m[d] for d in ordered] for m in maps]


def _resolve(
    closes: list[float],
    dates: list | None,
    others: list[tuple[list[float], list | None]],
) -> tuple[list[float], list[list[float]], list, bool]:
    """Return date-aligned series when every date list is supplied.

    日付が1つでも欠けている（None または空）場合は従来の位置合わせに
    フォールバックする（呼び出し側が日付を渡せない場合の後方互換）。
    第4要素がその可否を示す。
    """
    all_dates = [dates] + [d for _, d in others]
    if any(not d for d in all_dates):
        n = min([len(closes)] + [len(v) for v, _ in others])
        return closes[-n:], [v[-n:] for v, _ in others], [], False

    aligned_dates, vals = align_by_dates(
        [(dates, closes)] + [(d, v) for v, d in others]
    )
    return vals[0], vals[1:], aligned_dates, True


def calc_nikkei_usd(
    nikkei_closes: list[float],
    usdjpy_closes: list[float],
    period: int = 20,
    nikkei_dates: list | None = None,
    usdjpy_dates: list | None = None,
) -> dict:
    """ドル建て日経平均（日経225 ÷ USDJPY）の現在値・変化率・方向シグナルを返す。

    S&P500 との比較を含まない単体指標。円安・円高の影響をドル建てで可視化する。

    Parameters
    ----------
    nikkei_closes : list[float]
        日経225 日次終値（最新が末尾）。ティッカー: ^N225
    usdjpy_closes : list[float]
        USD/JPY 日次終値（JPY/USD レート、例: 157.9）。ティッカー: USDJPY=X
    period : int
        変化率の計算ウィンドウ（営業日数、デフォルト 20 ≈ 4 週間）。
        日付整合時は「共通営業日で20本」の意味になり、暦上の遡り期間は
        20日よりやや長くなる（片方だけの休場日が共通日から落ちるため）。
    nikkei_dates, usdjpy_dates : list | None
        各終値に対応する日付（KIK-727）。**両方を渡すと日付で整合させる。**
        ^N225 と USDJPY=X は営業日が異なり、位置合わせでは別々の日付を
        突き合わせてしまう（実測で 92% のペアが不一致）。省略時は従来の
        位置合わせにフォールバックし、``aligned: False`` を返す。

    Returns
    -------
    dict with keys:
        nikkei_usd_latest  : float | None  — 現在のドル建て日経平均
        nikkei_usd_chg_pct : float | None  — period 期間の変化率（%）
        signal             : "rising" | "falling" | "flat" | "unavailable"
        label              : str           — 人間可読1行ラベル
        aligned            : bool          — 日付で整合させたか
        as_of              : str | None    — 基準となった最新日付
    """
    _na: dict = {
        "nikkei_usd_latest": None,
        "nikkei_usd_chg_pct": None,
        "signal": "unavailable",
        "label": "データ不足",
        "aligned": False,
        "as_of": None,
    }

    min_len = period + 1
    if len(nikkei_closes) < min_len or len(usdjpy_closes) < min_len:
        return _na

    nikkei, (usdjpy,), dates, aligned = _resolve(
        nikkei_closes, nikkei_dates, [(usdjpy_closes, usdjpy_dates)]
    )
    n = len(nikkei)
    if n < min_len:
        # 「日付を渡したが共通日が足りない」と「日付を渡していない」を
        # caller が区別できるよう aligned を保持する（KIK-727 レビュー M4）。
        return {**_na, "aligned": aligned}

    def _to_usd(i: int):
        return nikkei[i] / usdjpy[i] if usdjpy[i] else None

    latest_usd = _to_usd(n - 1)
    base_usd = _to_usd(n - period - 1)

    if latest_usd is None or base_usd is None or base_usd == 0:
        return _na

    chg = (latest_usd - base_usd) / base_usd * 100
    thr = NIKKEI_USD_THRESHOLDS

    if chg >= thr["rising"]:
        signal = "rising"
        label = (
            f"ドル建て日経 {latest_usd:,.1f}USD"
            f"（{period}日: {chg:+.1f}% ↑ 上昇）"
        )
    elif chg <= thr["falling"]:
        signal = "falling"
        label = (
            f"ドル建て日経 {latest_usd:,.1f}USD"
            f"（{period}日: {chg:+.1f}% ↓ 下落）"
        )
    else:
        signal = "flat"
        label = (
            f"ドル建て日経 {latest_usd:,.1f}USD"
            f"（{period}日: {chg:+.1f}% → 横ばい）"
        )

    return {
        "nikkei_usd_latest": round(latest_usd, 2),
        "nikkei_usd_chg_pct": round(chg, 2),
        "signal": signal,
        "label": label,
        "aligned": aligned,
        "as_of": str(dates[-1]) if dates else None,
    }


def calc_jp_us_relative(
    nikkei_closes: list[float],
    usdjpy_closes: list[float],
    spx_closes: list[float],
    period: int = 20,
    nikkei_dates: list | None = None,
    usdjpy_dates: list | None = None,
    spx_dates: list | None = None,
) -> dict:
    """Compare dollar-denominated Nikkei vs S&P500 over a rolling window.

    Parameters
    ----------
    nikkei_closes : list[float]
        Nikkei 225 daily close prices (latest last). Ticker: ^N225.
    usdjpy_closes : list[float]
        USD/JPY daily close prices (JPY per USD, e.g. 150). Ticker: USDJPY=X.
    spx_closes : list[float]
        S&P 500 daily close prices (latest last). Ticker: ^GSPC.
    period : int
        Look-back window in trading days (~20 = 4 weeks).
        日付整合時は「共通営業日で period 本」の意味になる。日米の祝日差で
        年10日程度が共通日から落ちるため、暦上の遡り期間はやや長くなる。
    nikkei_dates, usdjpy_dates, spx_dates : list | None
        各終値に対応する日付（KIK-727）。**3つとも渡すと日付で整合させる。**
        日本と米国では祝日が異なるうえ、日本時間の夕方に実行すると米国市場は
        未終了で S&P500 だけ前営業日の終値になる（実測で 80% のペアが不一致、
        「最新」同士ですら N225=7/27 vs S&P500=7/24 のようにずれる）。
        省略時は従来の位置合わせにフォールバックし ``aligned: False`` を返す。

    Returns
    -------
    dict with keys:
        nikkei_usd_latest   : float | None  — current Nikkei in USD
        nikkei_usd_chg_pct  : float | None  — period % change of Nikkei_USD
        spx_chg_pct         : float | None  — period % change of S&P500
        relative_pct        : float | None  — nikkei_usd_chg - spx_chg
        signal              : "japan" | "us" | "neutral" | "unavailable"
        label               : str           — human-readable one-liner
        aligned             : bool          — 日付で整合させたか
        as_of               : str | None    — 基準となった最新日付
    """
    _na: dict = {
        "nikkei_usd_latest": None,
        "nikkei_usd_chg_pct": None,
        "spx_chg_pct": None,
        "relative_pct": None,
        "signal": "unavailable",
        "label": "データ不足",
        "aligned": False,
        "as_of": None,
    }

    min_len = period + 1
    if (
        len(nikkei_closes) < min_len
        or len(usdjpy_closes) < min_len
        or len(spx_closes) < min_len
    ):
        return _na

    nikkei, (usdjpy, spx), dates, aligned = _resolve(
        nikkei_closes,
        nikkei_dates,
        [(usdjpy_closes, usdjpy_dates), (spx_closes, spx_dates)],
    )
    n = len(nikkei)
    if n < min_len:
        return {**_na, "aligned": aligned}

    # Dollar-denominated Nikkei series
    nikkei_usd = [
        nikkei[i] / usdjpy[i] if usdjpy[i] and usdjpy[i] != 0 else None
        for i in range(n)
    ]

    latest_usd = nikkei_usd[-1]
    base_usd = nikkei_usd[-(period + 1)]

    if latest_usd is None or base_usd is None or base_usd == 0:
        return _na

    spx_latest = spx[-1]
    spx_base = spx[-(period + 1)]

    if spx_base == 0:
        return _na

    nikkei_usd_chg = (latest_usd - base_usd) / base_usd * 100
    spx_chg = (spx_latest - spx_base) / spx_base * 100
    relative = nikkei_usd_chg - spx_chg

    thr = JP_US_THRESHOLDS
    if relative >= thr["japan_favorable"]:
        signal = "japan"
        label = (
            f"日本株優位（ドル建て日経 {nikkei_usd_chg:+.1f}% vs S&P500 {spx_chg:+.1f}%、"
            f"相対 {relative:+.1f}%）"
        )
    elif relative <= thr["us_favorable"]:
        signal = "us"
        label = (
            f"米株優位（S&P500 {spx_chg:+.1f}% vs ドル建て日経 {nikkei_usd_chg:+.1f}%、"
            f"相対 {relative:+.1f}%）"
        )
    else:
        signal = "neutral"
        label = (
            f"中立（ドル建て日経 {nikkei_usd_chg:+.1f}% vs S&P500 {spx_chg:+.1f}%、"
            f"差 {relative:+.1f}%）"
        )

    return {
        "nikkei_usd_latest": round(latest_usd, 2),
        "nikkei_usd_chg_pct": round(nikkei_usd_chg, 2),
        "spx_chg_pct": round(spx_chg, 2),
        "relative_pct": round(relative, 2),
        "signal": signal,
        "label": label,
        "aligned": aligned,
        "as_of": str(dates[-1]) if dates else None,
    }


def calc_nt_ratio(
    nikkei_price: float,
    topix_price: float,
) -> dict:
    """NT倍率（日経225 ÷ TOPIX）を計算し、相場の集中度シグナルを返す。

    Parameters
    ----------
    nikkei_price : float
        日経225 現在値。
    topix_price : float
        TOPIX 現在値。

    Returns
    -------
    dict with keys:
        nt_ratio : float | None  — NT倍率（小数点2桁）
        signal   : "nikkei_heavy" | "topix_heavy" | "neutral" | "unavailable"
        label    : str           — 人間可読1行ラベル
    """
    _na = {"nt_ratio": None, "signal": "unavailable", "label": "データ不足"}

    if not nikkei_price or not topix_price:
        return _na

    nt = nikkei_price / topix_price
    thr = NT_THRESHOLDS

    if nt >= thr["nikkei_heavy"]:
        signal = "nikkei_heavy"
        label = (
            f"NT倍率 {nt:.2f}倍 — 日経225過熱"
            f"（大型・ハイテク集中、≥{thr['nikkei_heavy']}倍）"
        )
    elif nt < thr["topix_heavy"]:
        signal = "topix_heavy"
        label = (
            f"NT倍率 {nt:.2f}倍 — TOPIX優位"
            f"（広範株優勢、<{thr['topix_heavy']}倍）"
        )
    else:
        signal = "neutral"
        label = (
            f"NT倍率 {nt:.2f}倍 — 正常レンジ"
            f"（{thr['topix_heavy']}〜{thr['nikkei_heavy']}倍）"
        )

    return {
        "nt_ratio": round(nt, 2),
        "signal": signal,
        "label": label,
    }


def calc_nikkei_per_signal(per: float) -> dict:
    """日経225 PER の水準を評価する。

    Parameters
    ----------
    per : float
        日経225 の PER 倍率（例: 20.5）。WebSearch で取得する。

    Returns
    -------
    dict with keys:
        per     : float | None  — 入力値をそのまま返す
        signal  : "bubble" | "overvalued" | "cheap" | "normal" | "unavailable"
        label   : str           — 人間可読1行ラベル
    """
    _na = {"per": None, "signal": "unavailable", "label": "データ不足"}

    if per is None or per <= 0:
        return _na

    thr = NIKKEI_PER_THRESHOLDS

    if per >= thr["bubble"]:
        signal = "bubble"
        label = f"日経PER {per:.1f}倍 — バブル警告（≥{thr['bubble']:.0f}倍）"
    elif per >= thr["overvalued"]:
        signal = "overvalued"
        label = f"日経PER {per:.1f}倍 — 割高注意（≥{thr['overvalued']:.0f}倍）"
    elif per <= thr["cheap"]:
        signal = "cheap"
        label = f"日経PER {per:.1f}倍 — 割安シグナル（≤{thr['cheap']:.0f}倍）"
    else:
        signal = "normal"
        label = (
            f"日経PER {per:.1f}倍 — 正常レンジ"
            f"（{thr['cheap']:.0f}〜{thr['overvalued']:.0f}倍）"
        )

    return {"per": per, "signal": signal, "label": label}


def calc_nikkei_fair_value(price: float, per: float) -> dict:
    """日経225 の理論株価バンド（EPS × PER）を算出する。

    EPS は日経平均の実績値を別途取得せず、``price / per`` で導出する。
    Health Checker は日経225終値と日経PERを既に取得しているため、
    新たなデータ取得は不要。

    Parameters
    ----------
    price : float
        日経225 の現在値（例: 42000.0）。get_price_history の終値を使う。
    per : float
        日経225 の PER 倍率（例: 20.5）。calc_nikkei_per_signal と同じ値。

    Returns
    -------
    dict with keys:
        eps              : float | None  — 導出EPS（price / per）
        fair_cheap       : float | None  — 割安圏の株価（EPS × cheap倍）
        fair_overvalued  : float | None  — 割高圏の株価（EPS × overvalued倍）
        fair_bubble      : float | None  — バブル圏の株価（EPS × bubble倍）
        to_cheap_pct     : float | None  — 割安圏までの騰落率%（負なら下落が必要）
        to_overvalued_pct: float | None  — 割高圏までの騰落率%
        position         : "below_cheap" | "in_range" | "above_overvalued"
                           | "above_bubble" | "unavailable"
        label            : str           — 人間可読1行ラベル
    """
    _na = {
        "eps": None,
        "fair_cheap": None,
        "fair_overvalued": None,
        "fair_bubble": None,
        "to_cheap_pct": None,
        "to_overvalued_pct": None,
        "position": "unavailable",
        "label": "データ不足",
    }

    if price is None or per is None or price <= 0 or per <= 0:
        return _na

    thr = NIKKEI_PER_THRESHOLDS
    eps = price / per

    fair_cheap = eps * thr["cheap"]
    fair_overvalued = eps * thr["overvalued"]
    fair_bubble = eps * thr["bubble"]

    if per >= thr["bubble"]:
        position = "above_bubble"
        state = f"バブル圏（¥{fair_bubble:,.0f}超）"
    elif per >= thr["overvalued"]:
        position = "above_overvalued"
        state = f"割高圏（¥{fair_overvalued:,.0f}超）"
    elif per <= thr["cheap"]:
        position = "below_cheap"
        state = f"割安圏（¥{fair_cheap:,.0f}以下）"
    else:
        position = "in_range"
        state = "正常レンジ"

    label = (
        f"理論株価 割安圏 ¥{fair_cheap:,.0f} / 割高圏 ¥{fair_overvalued:,.0f}"
        f" — 現在 ¥{price:,.0f} は{state}"
    )

    return {
        "eps": round(eps, 1),
        "fair_cheap": round(fair_cheap, 1),
        "fair_overvalued": round(fair_overvalued, 1),
        "fair_bubble": round(fair_bubble, 1),
        "to_cheap_pct": round((fair_cheap - price) / price * 100, 1),
        "to_overvalued_pct": round((fair_overvalued - price) / price * 100, 1),
        "position": position,
        "label": label,
    }
