"""半年期日（6ヶ月ルール）の判定 — KIK-756.

制度信用取引の返済期限は最大6ヶ月。高値で信用買いした投資家は、その期限までに
決済しなければならない。含み損が解消されていなければ投げ売りが出るため、
天井から6ヶ月間は戻り売りに押される展開が続きやすい。

出典は Sho's投資情報局。2026-08-11 に実装時に1回だけ引いて定着させたもので、
実行時に NotebookLM は参照しない（#160 大底圏・バンドウォークと同じ扱い）。

⚠️ **現値が天井を下回っている場合にだけ重石になる。** 高値を更新している間は
   信用買いの含み損が無いので投げ売りの動機が生じない。この条件を落とすと、
   直近6ヶ月に高値があるほぼ全銘柄が「重石あり」になって警告が死ぬ。

check_margin_deadline : 天井日・期日・局面を返すメイン関数
"""

from __future__ import annotations

import datetime
from typing import Optional, Sequence

# 制度信用の返済期限
DEADLINE_MONTHS = 6

# 期日の何日前から「フライング」（需給整理が先行して底打ちする）とみなすか。
# 出典は「2週間〜1ヶ月前」。日数に直して 14〜30日。
FLYING_START_DAYS = 30
FLYING_END_DAYS = 14

# 天井とみなす下落率の下限。現値がこれ以上下にないと「含み損が解消されていない」
# 状態とは言えず、期日の重石も実質無い。
MIN_DRAWDOWN_PCT = 3.0


def _add_months(d: datetime.date, n: int) -> datetime.date:
    """月末日を吸収しつつ n ヶ月進める。"""
    y, m = divmod((d.year * 12 + d.month - 1) + n, 12)
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m])
    return datetime.date(y, m + 1, day)


def _to_date(value) -> Optional[datetime.date]:
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.datetime):
        return value.date()
    if hasattr(value, "date") and callable(value.date):   # pandas Timestamp
        try:
            return value.date()
        except Exception:
            return None
    s = str(value)[:10]
    try:
        return datetime.date.fromisoformat(s)
    except ValueError:
        return None


def check_margin_deadline(
    closes: Sequence[float],
    dates: Sequence,
    today: Optional[datetime.date] = None,
    lookback_months: int = 12,
) -> dict:
    """半年期日の局面を返す。

    Parameters
    ----------
    closes, dates
        終値と対応する日付（古い順・同じ長さ）。``get_price_history`` の
        ``df['Close']`` と ``df.index`` をそのまま渡せる。
    today
        基準日。省略時はローカル日付。
    lookback_months
        天井を探す範囲。既定12ヶ月（期日6ヶ月＋その手前を見るため）。

    Returns
    -------
    dict with keys:
        peak_date     : str | None  — 天井をつけた日
        peak_price    : float | None
        current_price : float | None
        drawdown_pct  : float | None — 天井からの下落率（負値）
        deadline      : str | None   — 天井 + 6ヶ月
        days_to_deadline : int | None — 負なら経過済み
        phase   : "pressure" | "flying" | "cleared" | "no_overhang" | "unavailable"
        label   : str
    """
    _na = {
        "peak_date": None, "peak_price": None, "current_price": None,
        "drawdown_pct": None, "deadline": None, "days_to_deadline": None,
        "phase": "unavailable", "label": "データ不足",
    }

    if not closes or not dates or len(closes) != len(dates):
        return _na

    today = today or datetime.date.today()
    start = _add_months(today, -lookback_months)

    pairs = []
    for c, d in zip(closes, dates):
        dd = _to_date(d)
        if dd is None or c is None:
            continue
        try:
            price = float(c)
        except (TypeError, ValueError):
            continue
        if price > 0 and start <= dd <= today:
            pairs.append((dd, price))

    if not pairs:
        return _na

    current_price = pairs[-1][1]
    peak_date, peak_price = max(pairs, key=lambda x: x[1])
    drawdown = (current_price - peak_price) / peak_price * 100

    # 高値更新中、または下落がごく浅い場合は重石にならない。
    # 信用買いの含み損が無ければ投げ売りの動機も無い。
    if drawdown > -MIN_DRAWDOWN_PCT:
        return {
            "peak_date": peak_date.isoformat(), "peak_price": peak_price,
            "current_price": current_price, "drawdown_pct": round(drawdown, 1),
            "deadline": None, "days_to_deadline": None,
            "phase": "no_overhang",
            "label": (f"半年期日の重石なし（天井 {peak_date.isoformat()} から "
                      f"{drawdown:+.1f}%。含み損が浅く投げ売りの動機が乏しい）"),
        }

    deadline = _add_months(peak_date, DEADLINE_MONTHS)
    days = (deadline - today).days

    if days < 0:
        phase = "cleared"
        label = (f"半年期日 通過済み（{deadline.isoformat()} / {-days}日経過）"
                 f" — 天井 {peak_date.isoformat()} 分の期日売りは一巡")
    elif FLYING_END_DAYS <= days <= FLYING_START_DAYS:
        phase = "flying"
        label = (f"半年期日まで{days}日（{deadline.isoformat()}）"
                 f" — フライング圏。需給整理が先行して底打ちしやすい")
    else:
        phase = "pressure"
        label = (f"半年期日まで{days}日（{deadline.isoformat()}）"
                 f" — 天井 {peak_date.isoformat()}（{drawdown:+.1f}%）の"
                 f"信用買いが重石。戻り売りに押されやすい")

    return {
        "peak_date": peak_date.isoformat(), "peak_price": peak_price,
        "current_price": current_price, "drawdown_pct": round(drawdown, 1),
        "deadline": deadline.isoformat(), "days_to_deadline": days,
        "phase": phase, "label": label,
    }
