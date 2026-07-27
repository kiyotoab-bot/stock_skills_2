"""Morning summary: anomaly detection for portfolio (KIK-717).

Detects exit-rule hits, RSI extremes, upcoming earnings, and VIX spikes.
Pure data functions — no judgment, no recommendations.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np

from src.data.common import safe_float


# ---------------------------------------------------------------------------
# Alert types and thresholds
# ---------------------------------------------------------------------------

ALERT_THRESHOLDS = {
    "exit_rule_pct": -15.0,       # exit-rule default (%)
    "hard_stop_pct": -20.0,       # hard stop loss (%)
    "rsi_overbought": 70,
    "rsi_oversold": 30,
    "earnings_days": 7,           # days before earnings to alert
    "vix_elevated": 25,
    "nikkei_per_overvalued": 20.0,  # 割高注意
    "nikkei_per_bubble": 25.0,      # 過熱警告（強制risk-off考慮水準）
    "nikkei_per_cheap": 13.0,       # 割安シグナル
    "profit_take_gain": 30.0,       # 利確検討: 含み益 >= 30%
    "profit_take_rsi": 65.0,        # 利確検討: RSI >= 65（上昇圏）
    "exit_warn_pct": -10.0,         # WARN: exit-rule(-15%) 手前の警戒ライン
}


def _calc_rsi(closes: list[float], period: int = 14) -> float | None:
    """Calculate RSI(14) using Wilder's smoothing (KIK-727).

    旧実装は直近 period+1 本の単純平均（Cutler's RSI）だった。閾値 30/70 は
    Wilder 平滑を前提に定まった値であり、算出方式が噛み合っていなかった。
    実測では保有＋WL 46銘柄で平均 6.2pt・最大 20.8pt 乖離し、5銘柄(11%)で
    買われすぎ/売られすぎの判定が食い違っていた。

    Wilder は系列全体を平滑するため、渡す ``closes`` が長いほど値が安定する。
    """
    if len(closes) < period + 1:
        return None

    deltas = np.diff(np.asarray(closes, dtype=float))
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    # Seed with the simple average of the first `period` deltas, then smooth.
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def detect_alerts(
    positions: list[dict],
    infos: dict[str, dict],
    histories: dict[str, list[float]],
    vix_price: float | None = None,
    prev_alerts: list[dict] | None = None,
    nikkei_per: float | None = None,
) -> list[dict]:
    """Detect anomalies across portfolio holdings.

    Parameters
    ----------
    positions : list[dict]
        Portfolio from load_portfolio().
    infos : dict[str, dict]
        {symbol: get_stock_info() result}.
    histories : dict[str, list[float]]
        {symbol: list of close prices (latest last)}.
    vix_price : float | None
        Current VIX value.
    prev_alerts : list[dict] | None
        Previous day's alerts for state-change filtering.
    nikkei_per : float | None
        Nikkei 225 PER (Price-to-Earnings Ratio). Alerts when overvalued or cheap.

    Returns
    -------
    list[dict]
        List of alert dicts with keys: symbol, type, severity, message, value.
    """
    alerts = []
    thr = ALERT_THRESHOLDS
    prev_symbols_types = set()
    if prev_alerts:
        prev_symbols_types = {(a["symbol"], a["type"]) for a in prev_alerts}

    for pos in positions:
        sym = pos["symbol"]
        info = infos.get(sym)
        if not info:
            continue

        price = safe_float(info.get("price"))
        cost = safe_float(pos.get("cost_price"))

        # P&L calculation (shared between exit-rule and profit-take checks)
        pnl_pct: float | None = None
        if price > 0 and cost > 0:
            pnl_pct = (price - cost) / cost * 100

        # 1. Exit-rule: loss threshold
        if pnl_pct is not None:
            if pnl_pct <= thr["hard_stop_pct"]:
                alerts.append({
                    "symbol": sym, "type": "hard_stop",
                    "severity": "CRITICAL",
                    "message": f"損益{pnl_pct:+.1f}% → 損切りライン(-20%)到達",
                    "value": pnl_pct,
                })
            elif pnl_pct <= thr["exit_rule_pct"]:
                alerts.append({
                    "symbol": sym, "type": "exit_rule",
                    "severity": "CRITICAL",
                    "message": f"損益{pnl_pct:+.1f}% → exit-rule(-15%)到達",
                    "value": pnl_pct,
                })
            elif pnl_pct <= thr["exit_warn_pct"]:
                # KIK-727: WARN 層。従来 WARN は一度も生成されず、レポートの
                # 「WARN 0件」が無内容だった。exit-rule 到達手前をここで拾う。
                alerts.append({
                    "symbol": sym, "type": "exit_approaching",
                    "severity": "WARN",
                    "message": (
                        f"損益{pnl_pct:+.1f}% → exit-rule(-15%)まで"
                        f"あと{pnl_pct - thr['exit_rule_pct']:.1f}pt"
                    ),
                    "value": pnl_pct,
                })

        # 2. RSI extremes
        closes = histories.get(sym, [])
        rsi = _calc_rsi(closes)
        if rsi is not None:
            if rsi >= thr["rsi_overbought"]:
                alerts.append({
                    "symbol": sym, "type": "rsi_high",
                    "severity": "INFO",
                    "message": f"RSI {rsi:.1f} → 買われすぎ圏",
                    "value": rsi,
                })
            elif rsi <= thr["rsi_oversold"]:
                alerts.append({
                    "symbol": sym, "type": "rsi_low",
                    "severity": "INFO",
                    "message": f"RSI {rsi:.1f} → 売られすぎ圏",
                    "value": rsi,
                })

        # 2b. Profit-take: large gain + RSI elevated
        if (pnl_pct is not None and rsi is not None
                and pnl_pct >= thr["profit_take_gain"]
                and rsi >= thr["profit_take_rsi"]):
            alerts.append({
                "symbol": sym, "type": "profit_take",
                "severity": "INFO",
                "message": f"損益{pnl_pct:+.1f}% RSI{rsi:.0f} → 利確検討ゾーン",
                "value": pnl_pct,
            })

        # 3. Upcoming earnings
        # KIK-727: portfolio.csv の next_earnings 列は手動更新前提で常に空欄のため、
        # このアラートは一度も発火していなかった。get_stock_info が自動取得する
        # next_earnings にフォールバックする。CSV に明示値があればそちらを優先。
        next_earnings = pos.get("next_earnings") or ""
        if not next_earnings and info:
            next_earnings = info.get("next_earnings") or ""
        if next_earnings:
            try:
                earn_date = datetime.strptime(next_earnings, "%Y-%m-%d").date()
                days_until = (earn_date - date.today()).days
                if 0 <= days_until <= thr["earnings_days"]:
                    alerts.append({
                        "symbol": sym, "type": "earnings_soon",
                        "severity": "INFO",
                        "message": f"決算{next_earnings}（残{days_until}日）",
                        "value": days_until,
                    })
            except ValueError:
                pass

    # 4. VIX
    if vix_price is not None and vix_price >= thr["vix_elevated"]:
        alerts.append({
            "symbol": "^VIX", "type": "vix_high",
            "severity": "CRITICAL" if vix_price >= 30 else "INFO",
            "message": f"VIX {vix_price:.1f} → {'急騰' if vix_price >= 30 else '警戒水準'}",
            "value": vix_price,
        })

    # 5. Nikkei 225 PER
    if nikkei_per is not None:
        if nikkei_per >= thr["nikkei_per_bubble"]:
            alerts.append({
                "symbol": "^N225", "type": "nikkei_per_bubble",
                "severity": "CRITICAL",
                "message": f"日経PER {nikkei_per:.1f}倍 → 過熱警告（>={thr['nikkei_per_bubble']:.0f}倍）",
                "value": nikkei_per,
            })
        elif nikkei_per >= thr["nikkei_per_overvalued"]:
            alerts.append({
                "symbol": "^N225", "type": "nikkei_per_overvalued",
                "severity": "INFO",
                "message": f"日経PER {nikkei_per:.1f}倍 → 割高注意（>={thr['nikkei_per_overvalued']:.0f}倍）",
                "value": nikkei_per,
            })
        elif nikkei_per <= thr["nikkei_per_cheap"]:
            alerts.append({
                "symbol": "^N225", "type": "nikkei_per_cheap",
                "severity": "INFO",
                "message": f"日経PER {nikkei_per:.1f}倍 → 割安シグナル（<={thr['nikkei_per_cheap']:.0f}倍）",
                "value": nikkei_per,
            })

    # 6. State-change filter: remove alerts that existed yesterday with same symbol+type
    # KIK-727: CRITICAL は除外しない。exit-rule 抵触や損切りライン到達が継続して
    # いる状態で2日目に消えるのは危険なため、抑制対象は WARN / INFO のみとする。
    if prev_alerts:
        alerts = [
            a for a in alerts
            if a.get("severity") == "CRITICAL"
            or (a["symbol"], a["type"]) not in prev_symbols_types
        ]

    # Sort by severity (CRITICAL first)
    # KIK-727: WARN が抜けており、生成されても INFO の後ろに回っていた。
    severity_order = {"CRITICAL": 0, "WARN": 1, "INFO": 2}
    alerts.sort(key=lambda a: severity_order.get(a["severity"], 2))

    return alerts


def format_morning_summary(alerts: list[dict], pf_total: float | None = None) -> str:
    """Format alerts into a human-readable morning summary.

    Parameters
    ----------
    alerts : list[dict]
        Output of detect_alerts().
    pf_total : float | None
        PF total value for context.

    Returns
    -------
    str
        Formatted summary string.
    """
    today_str = date.today().strftime("%m/%d")
    weekday = ["月", "火", "水", "木", "金", "土", "日"][date.today().weekday()]

    if not alerts:
        return f"■ 朝サマリー（{today_str} {weekday}）\n☀️ 異常なし"

    lines = [f"■ 朝サマリー（{today_str} {weekday}）"]

    critical = [a for a in alerts if a["severity"] == "CRITICAL"]
    info = [a for a in alerts if a["severity"] == "INFO"]

    total_count = len(alerts)
    lines.append(f"⚠️ {total_count}件の注意")
    lines.append("")

    for a in critical[:3]:
        sym_display = a["symbol"]
        lines.append(f"🔴 {sym_display}: {a['message']}")

    for a in info[:5]:
        sym_display = a["symbol"]
        lines.append(f"🟡 {sym_display}: {a['message']}")

    if len(alerts) > 8:
        lines.append(f"  ...他{len(alerts) - 8}件")

    # Suggest deepdive for most critical
    if critical:
        first = critical[0]
        if first["type"] in ("hard_stop", "exit_rule"):
            lines.append(f"\n→「{first['symbol']}を売るべきか」で詳細分析")
        elif first["type"] == "vix_high":
            lines.append(f"\n→「リスク判定して」で市況確認")
    elif info:
        first = info[0]
        if first["type"] == "earnings_soon":
            lines.append(f"\n→「{first['symbol']}の決算前チェック」で確認")
        elif first["type"] == "profit_take":
            lines.append(f"\n→「{first['symbol']}を利確すべきか」で詳細分析")

    return "\n".join(lines)
