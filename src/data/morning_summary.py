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
    "stop_noise_sigma": 1.0,        # WARN: ストップまで日次σの何倍以内ならノイズ圏か
    "stop_near_sigma": 2.0,         # INFO: ストップ接近とみなす日次σ倍
    "margin_ratio_heavy": 15.0,     # INFO: 信用倍率がこれ以上なら買い残が厚い
    "margin_ratio_extreme": 30.0,   # WARN: 上値の重石として明確な水準
    "margin_surge_pct": 50.0,       # INFO: 信用買い残の前週比 急増ライン
}

# 前日と同じ内容でも毎回報告するアラート種別（KIK-727）。
# ポジション単位の致命的アラートは、状態が続く限り毎日出す。
_ALWAYS_REPORT_TYPES = frozenset(
    {"hard_stop", "exit_rule", "stop_hit", "stop_noise_zone", "stop_unparsed"}
)


def _daily_sigma(closes: list[float], window: int = 60) -> float | None:
    """Daily log-return standard deviation over the trailing ``window`` days."""
    if not closes or len(closes) < 21:
        return None
    arr = np.asarray(closes[-(window + 1):], dtype=float)
    if np.any(arr <= 0):
        return None
    rets = np.diff(np.log(arr))
    if len(rets) < 20:
        return None
    sd = float(np.std(rets, ddof=1))
    return sd if sd > 0 else None


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
    stop_levels: dict[str, dict] | None = None,
    margins: dict[str, dict] | None = None,
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
    stop_levels : dict[str, dict] | None
        ``{symbol: {"stop": float|None, "raw": str, "conviction": bool}}`` from
        ``note_manager.get_stop_levels()``. Until KIK-728 this function ignored
        the stops recorded in notes entirely, so stop monitoring was fully
        manual — the gap that let the 2026-08-04 mis-order go undetected.
    margins : dict[str, dict] | None
        ``{symbol: tools.jquants.get_stock_margin() の戻り値}``。信用倍率（需給）。
        値動きとバリュエーションだけ見ていると完全に抜ける軸。2026-08-06 まで一度も
        見ておらず、保有の 8031.T が信用倍率 38.5倍だったことに気づいていなかった。

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

        # 1b. Stop-loss level recorded in notes (KIK-728)
        # 距離は % ではなく日次σ倍で測る。同じ -3% でも σ1.6% の銘柄では
        # 1.9σ（テーゼ崩壊の水準）、σ3.1% の銘柄では 1.0σ（ただのノイズ）であり、
        # % で並べると高ボラ銘柄のストップが常に「近い」と誤検知されるため。
        closes = histories.get(sym, [])
        entry = (stop_levels or {}).get(sym)
        if entry is not None and not entry.get("conviction"):
            stop = entry.get("stop")
            if stop is None:
                alerts.append({
                    "symbol": sym, "type": "stop_unparsed",
                    "severity": "WARN",
                    "message": (
                        f"ストップ値を数値として解釈できません（{entry.get('raw', '')!r}）"
                        " → 自動監視できないため手動確認が必要"
                    ),
                    "value": None,
                })
            elif price > 0:
                gap = (stop / price - 1) * 100
                sd = _daily_sigma(closes)
                sigma_mult = abs(stop / price - 1) / sd if sd else None
                unit = f"{sigma_mult:.2f}日σ" if sigma_mult is not None else "σ不明"
                if price <= stop:
                    alerts.append({
                        "symbol": sym, "type": "stop_hit",
                        "severity": "CRITICAL",
                        "message": f"終値¥{price:,.0f} ≤ ストップ¥{stop:,.0f} → 抵触",
                        "value": gap,
                    })
                elif sigma_mult is not None and sigma_mult <= thr["stop_noise_sigma"]:
                    alerts.append({
                        "symbol": sym, "type": "stop_noise_zone",
                        "severity": "WARN",
                        "message": (
                            f"ストップ¥{stop:,.0f}まで{gap:.2f}%（{unit}）"
                            " → ノイズで発火する距離。幅の見直しを検討"
                        ),
                        "value": gap,
                    })
                elif sigma_mult is not None and sigma_mult <= thr["stop_near_sigma"]:
                    alerts.append({
                        "symbol": sym, "type": "stop_near",
                        "severity": "INFO",
                        "message": f"ストップ¥{stop:,.0f}まで{gap:.2f}%（{unit}）",
                        "value": gap,
                    })

        # 1c. Margin ratio (信用倍率) — 需給の重石 (KIK-732)
        # 買い残 ÷ 売り残。大きいほど上値で戻り売りに押される。
        # バリュエーションと値動きだけを見ていると完全に見落とす軸で、実際
        # 2026-08-06 まで一度も見ておらず、8031.T 三井物産が 38.5倍 だったことに
        # 気づいていなかった（週次ルーティンに定義はあったが実行していなかった）。
        mg = (margins or {}).get(sym)
        if mg and mg.get("available"):
            ratio = safe_float(mg.get("margin_ratio"))
            wow = safe_float(mg.get("wow_change_pct"))
            if ratio > 0:
                if ratio >= thr["margin_ratio_extreme"]:
                    alerts.append({
                        "symbol": sym, "type": "margin_extreme",
                        "severity": "WARN",
                        "message": (
                            f"信用倍率 {ratio:.1f}倍 → 買い残が厚く上値の重石"
                            f"（{mg.get('date', '')}）"
                        ),
                        "value": ratio,
                    })
                elif ratio >= thr["margin_ratio_heavy"]:
                    alerts.append({
                        "symbol": sym, "type": "margin_heavy",
                        "severity": "INFO",
                        "message": f"信用倍率 {ratio:.1f}倍 → やや買い残が厚い（{mg.get('date', '')}）",
                        "value": ratio,
                    })
            if wow >= thr["margin_surge_pct"]:
                alerts.append({
                    "symbol": sym, "type": "margin_surge",
                    "severity": "INFO",
                    "message": f"信用買い残が前週比 {wow:+.1f}% と急増",
                    "value": wow,
                })

        # 2. RSI extremes
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
            except (ValueError, TypeError):
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
    # KIK-727: ポジション単位の CRITICAL は除外しない。exit-rule 抵触や
    # 損切りライン到達が継続している状態で2日目に消えるのは危険なため。
    # 一方 vix_high / nikkei_per_bubble は市場状態で数週間〜数ヶ月続き得るので
    # 「変化だけ知らせる」という state-change フィルタ本来の目的に従わせる。
    if prev_alerts:
        alerts = [
            a for a in alerts
            if a.get("type") in _ALWAYS_REPORT_TYPES
            or (a["symbol"], a["type"]) not in prev_symbols_types
        ]

    # Sort by severity (CRITICAL first)
    # KIK-727: WARN が抜けており、生成されても INFO の後ろに回っていた。
    severity_order = {"CRITICAL": 0, "WARN": 1, "INFO": 2}
    alerts.sort(key=lambda a: severity_order.get(a.get("severity"), 3))

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
    warn = [a for a in alerts if a["severity"] == "WARN"]
    info = [a for a in alerts if a["severity"] == "INFO"]

    total_count = len(alerts)
    lines.append(f"⚠️ {total_count}件の注意")
    lines.append("")

    # KIK-727: WARN 層を CRITICAL と INFO の間に表示する。
    # 表示件数は実際に出した数から数える（総数固定で引くと、層ごとの
    # 上限で落ちた分が「...他N件」に反映されず件数表示と食い違う）。
    shown = 0
    for a in critical[:3]:
        lines.append(f"🔴 {a['symbol']}: {a['message']}")
        shown += 1

    for a in warn[:3]:
        lines.append(f"🟠 {a['symbol']}: {a['message']}")
        shown += 1

    for a in info[:5]:
        lines.append(f"🟡 {a['symbol']}: {a['message']}")
        shown += 1

    if total_count > shown:
        lines.append(f"  ...他{total_count - shown}件")

    # Suggest deepdive for most critical
    if critical:
        first = critical[0]
        if first["type"] in ("hard_stop", "exit_rule"):
            lines.append(f"\n→「{first['symbol']}を売るべきか」で詳細分析")
        elif first["type"] == "vix_high":
            lines.append(f"\n→「リスク判定して」で市況確認")
    elif warn:
        first = warn[0]
        if first["type"] == "exit_approaching":
            lines.append(f"\n→「{first['symbol']}を売るべきか」で詳細分析")
    elif info:
        first = info[0]
        if first["type"] == "earnings_soon":
            lines.append(f"\n→「{first['symbol']}の決算前チェック」で確認")
        elif first["type"] == "profit_take":
            lines.append(f"\n→「{first['symbol']}を利確すべきか」で詳細分析")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ルーティンの鮮度チェック (KIK-733)
# ---------------------------------------------------------------------------

ROUTINE_STALE_DAYS = {
    "weekly": {"warn": 7, "critical": 14},
    "daily": {"warn": 3, "critical": 7},
}

_ROUTINE_LABEL = {"weekly": "週次レビュー", "daily": "日次チェック"}


def latest_routine_dates(reports_dir: str = "data/reports") -> dict[str, str | None]:
    """``data/reports/`` から日次・週次の最終実行日を拾う。

    ファイル名は ``daily_YYYYMMDD.md`` / ``weekly_YYYYMMDD.md``。
    """
    from pathlib import Path

    out: dict[str, str | None] = {"daily": None, "weekly": None}
    d = Path(reports_dir)
    if not d.is_dir():
        return out
    for kind in out:
        dates = []
        for p in d.glob(f"{kind}_*.md"):
            stem = p.stem.split("_", 1)[-1]
            if len(stem) == 8 and stem.isdigit():
                dates.append(f"{stem[:4]}-{stem[4:6]}-{stem[6:]}")
        if dates:
            out[kind] = max(dates)
    return out


def check_routine_freshness(
    last_dates: dict[str, str | None],
    today: date | None = None,
) -> list[dict]:
    """定常業務が放置されていないかを検知する。

    週次レビューにしか含まれない項目（リスク判定・アクションプラン・レビュー・需給）は、
    週次を回さないと**誰も気づかないまま抜け続ける**。実際 2026-07-27 から 08-06 まで
    10日間、週次が一度も実行されず、その間にリスク判定・Reviewer・需給がすべて
    抜けていた（需給はユーザーの指摘で発覚）。日次の側から検知できるようにする。
    """
    today = today or date.today()
    alerts: list[dict] = []
    for kind, thr in ROUTINE_STALE_DAYS.items():
        last = last_dates.get(kind)
        label = _ROUTINE_LABEL[kind]
        if not last:
            alerts.append({
                "symbol": "ROUTINE", "type": f"{kind}_never_run",
                "severity": "WARN",
                "message": f"{label} の実行記録がありません",
                "value": None,
            })
            continue
        try:
            elapsed = (today - date.fromisoformat(last)).days
        except ValueError:
            continue
        if elapsed >= thr["critical"]:
            sev = "CRITICAL"
        elif elapsed >= thr["warn"]:
            sev = "WARN"
        else:
            continue
        extra = ""
        if kind == "weekly":
            extra = "（リスク判定・アクションプラン・レビュー・需給が抜けたままです）"
        alerts.append({
            "symbol": "ROUTINE", "type": f"{kind}_stale",
            "severity": sev,
            "message": f"{label} が {elapsed}日 未実行（最終 {last}）{extra}",
            "value": elapsed,
        })
    return alerts


def save_routine_report(
    kind: str,
    markdown: str,
    data: dict | None = None,
    day: date | None = None,
    reports_dir: str = "data/reports",
    logs_dir: str = "data/session_logs/routine",
) -> dict[str, str]:
    """日次／週次レポートを Markdown と JSON の両方に保存する。

    ``kind`` は ``"daily"`` / ``"weekly"``。

    2026-08-06 に日次チェックを3回実行しながら保存を怠った。SKILL.md は保存を
    義務付けているが、**Markdown と JSON を別々に書く手順**だったため
    「実行したが記録していない」が起きた。``check_routine_freshness()`` は
    保存されたレポートの日付を見るので、この抜けは最大3日間検知されない。
    ここで1呼び出しにまとめ、書き忘れの余地を減らす。
    """
    import json as _json
    from pathlib import Path

    if kind not in ("daily", "weekly"):
        raise ValueError(f"kind must be 'daily' or 'weekly', got {kind!r}")
    day = day or date.today()
    stamp = day.strftime("%Y%m%d")

    Path(reports_dir).mkdir(parents=True, exist_ok=True)
    md_path = Path(reports_dir) / f"{kind}_{stamp}.md"
    md_path.write_text(markdown, encoding="utf-8")

    out = {"markdown": str(md_path)}
    if data is not None:
        Path(logs_dir).mkdir(parents=True, exist_ok=True)
        js_path = Path(logs_dir) / f"{kind}_{stamp}.json"
        payload = {"date": day.isoformat(), "mode": f"routine-{kind}", **data}
        js_path.write_text(
            _json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        out["json"] = str(js_path)
    return out
