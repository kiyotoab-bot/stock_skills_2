"""Output formatters for portfolio management (KIK-342)."""

from datetime import datetime
from typing import Optional

from src.output._format_helpers import fmt_pct as _fmt_pct
from src.output._format_helpers import fmt_pct_sign as _fmt_pct_sign
from src.output._format_helpers import fmt_float as _fmt_float
from src.output._format_helpers import hhi_bar as _hhi_bar


def _fmt_jpy(value: Optional[float]) -> str:
    """Format a value as Japanese Yen with comma separators."""
    if value is None:
        return "-"
    if value < 0:
        return f"-\u00a5{abs(value):,.0f}"
    return f"\u00a5{value:,.0f}"


def _fmt_usd(value: Optional[float]) -> str:
    """Format a value as US Dollar."""
    if value is None:
        return "-"
    if value < 0:
        return f"-${abs(value):,.2f}"
    return f"${value:,.2f}"


def _fmt_currency_value(value: Optional[float], currency: str = "JPY") -> str:
    """Format a value in the appropriate currency format."""
    if value is None:
        return "-"
    currency = (currency or "JPY").upper()
    if currency == "JPY":
        return _fmt_jpy(value)
    elif currency == "USD":
        return _fmt_usd(value)
    else:
        return f"{value:,.2f} {currency}"


def _pnl_indicator(value: Optional[float]) -> str:
    """Return gain/loss indicator: triangle-up for positive, triangle-down for negative."""
    if value is None:
        return ""
    if value > 0:
        return "\u25b2"  # ▲
    elif value < 0:
        return "\u25bc"  # ▼
    return ""


def _classify_hhi(hhi: float) -> str:
    """Classify HHI into a risk label."""
    if hhi < 0.25:
        return "\u5206\u6563"  # 分散
    if hhi < 0.50:
        return "\u3084\u3084\u96c6\u4e2d"  # やや集中
    return "\u5371\u967a\u306a\u96c6\u4e2d"  # 危険な集中


# ---------------------------------------------------------------------------
# format_snapshot
# ---------------------------------------------------------------------------

def format_snapshot(snapshot: dict) -> str:
    """Format a portfolio snapshot as a Markdown report.

    Parameters
    ----------
    snapshot : dict
        Expected keys:
        - "timestamp": str (ISO format or display string)
        - "positions": list[dict] with keys:
            symbol, memo, shares, cost_price, current_price,
            market_value_jpy, pnl_jpy, pnl_pct, currency
        - "total_market_value_jpy": float
        - "total_cost_jpy": float
        - "total_pnl_jpy": float
        - "total_pnl_pct": float
        - "fx_rates": dict (e.g. {"USD/JPY": 150.0, "SGD/JPY": 110.0})

    Returns
    -------
    str
        Markdown-formatted snapshot report.
    """
    lines: list[str] = []

    # Header with timestamp
    ts = snapshot.get("timestamp")
    if ts:
        try:
            dt = datetime.fromisoformat(ts)
            ts_display = dt.strftime("%Y/%m/%d %H:%M")
        except (ValueError, TypeError):
            ts_display = str(ts)
    else:
        ts_display = datetime.now().strftime("%Y/%m/%d %H:%M")

    lines.append(f"## \u30dd\u30fc\u30c8\u30d5\u30a9\u30ea\u30aa \u30b9\u30ca\u30c3\u30d7\u30b7\u30e7\u30c3\u30c8 ({ts_display})")
    lines.append("")

    # Positions table
    positions = snapshot.get("positions", [])
    if not positions:
        lines.append("\u4fdd\u6709\u9298\u67c4\u304c\u3042\u308a\u307e\u305b\u3093\u3002")
        return "\n".join(lines)

    lines.append("| \u9298\u67c4 | \u30e1\u30e2 | \u682a\u6570 | \u53d6\u5f97\u5358\u4fa1 | \u73fe\u5728\u4fa1\u683c | \u8a55\u4fa1\u984d | \u640d\u76ca | \u640d\u76ca\u7387 |")
    lines.append("|:-----|:-----|-----:|-------:|-------:|------:|-----:|-----:|")

    for pos in positions:
        symbol = pos.get("symbol", "-")
        memo = pos.get("memo") or ""
        shares = pos.get("shares", 0)
        cost_price = pos.get("cost_price")
        current_price = pos.get("current_price")
        market_value = pos.get("market_value_jpy")
        pnl = pos.get("pnl_jpy")
        pnl_pct = pos.get("pnl_pct")
        currency = pos.get("currency", "JPY")

        cost_str = _fmt_currency_value(cost_price, currency)
        price_str = _fmt_currency_value(current_price, currency)
        mv_str = _fmt_jpy(market_value)

        # PnL with indicator
        indicator = _pnl_indicator(pnl)
        pnl_str = f"{indicator} {_fmt_jpy(pnl)}" if pnl is not None else "-"
        pnl_pct_str = f"{indicator} {_fmt_pct(pnl_pct)}" if pnl_pct is not None else "-"

        lines.append(
            f"| {symbol} | {memo} | {shares:,} | {cost_str} | {price_str} "
            f"| {mv_str} | {pnl_str} | {pnl_pct_str} |"
        )

    lines.append("")

    # Summary
    lines.append("### \u30b5\u30de\u30ea\u30fc")

    total_mv = snapshot.get("total_market_value_jpy")
    total_cost = snapshot.get("total_cost_jpy")
    total_pnl = snapshot.get("total_pnl_jpy")
    total_pnl_pct = snapshot.get("total_pnl_pct")

    lines.append(f"- \u7dcf\u8a55\u4fa1\u984d\uff08\u5186\uff09: {_fmt_jpy(total_mv)}")
    lines.append(f"- \u7dcf\u6295\u8cc7\u984d\uff08\u5186\uff09: {_fmt_jpy(total_cost)}")

    if total_pnl is not None and total_pnl_pct is not None:
        indicator = _pnl_indicator(total_pnl)
        lines.append(
            f"- \u7dcf\u640d\u76ca\uff08\u5186\uff09: {indicator} {_fmt_jpy(total_pnl)} "
            f"({_fmt_pct_sign(total_pnl_pct)})"
        )
    elif total_pnl is not None:
        indicator = _pnl_indicator(total_pnl)
        lines.append(f"- \u7dcf\u640d\u76ca\uff08\u5186\uff09: {indicator} {_fmt_jpy(total_pnl)}")

    lines.append("")

    # FX Rates
    fx_rates = snapshot.get("fx_rates", {})
    if fx_rates:
        lines.append("### \u70ba\u66ff\u30ec\u30fc\u30c8")
        for pair, rate in fx_rates.items():
            lines.append(f"- {pair}: {_fmt_float(rate, decimals=2)}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# format_position_list
# ---------------------------------------------------------------------------

def format_position_list(portfolio: list[dict]) -> str:
    """Format a list of portfolio positions as a Markdown table.

    Parameters
    ----------
    portfolio : list[dict]
        Each dict should contain: symbol, shares, cost_price,
        cost_currency, purchase_date, memo.

    Returns
    -------
    str
        Markdown-formatted table of positions.
    """
    lines: list[str] = []
    lines.append("## \u4fdd\u6709\u9298\u67c4\u4e00\u89a7")
    lines.append("")

    if not portfolio:
        lines.append("\u4fdd\u6709\u9298\u67c4\u304c\u3042\u308a\u307e\u305b\u3093\u3002")
        return "\n".join(lines)

    lines.append("| \u9298\u67c4 | \u682a\u6570 | \u53d6\u5f97\u5358\u4fa1 | \u901a\u8ca8 | \u53d6\u5f97\u65e5 | \u30e1\u30e2 |")
    lines.append("|:-----|-----:|-------:|:-----|:---------|:-----|")

    for pos in portfolio:
        symbol = pos.get("symbol", "-")
        shares = pos.get("shares", 0)
        cost_price = pos.get("cost_price")
        currency = pos.get("cost_currency") or pos.get("currency", "JPY")
        purchase_date = pos.get("purchase_date") or "-"
        memo = pos.get("memo") or ""

        cost_str = _fmt_currency_value(cost_price, currency)

        lines.append(
            f"| {symbol} | {shares:,} | {cost_str} | {currency} "
            f"| {purchase_date} | {memo} |"
        )

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# format_structure_analysis
# ---------------------------------------------------------------------------

def format_structure_analysis(analysis: dict) -> str:
    """Format a portfolio structure analysis as a Markdown report.

    Parameters
    ----------
    analysis : dict
        Expected keys (from concentration.analyze_concentration()):
        - "region_hhi", "region_breakdown"
        - "sector_hhi", "sector_breakdown"
        - "currency_hhi", "currency_breakdown"
        - "max_hhi", "max_hhi_axis"
        - "concentration_multiplier"
        - "risk_level"

    Returns
    -------
    str
        Markdown-formatted structure analysis report.
    """
    lines: list[str] = []
    lines.append("## \u30dd\u30fc\u30c8\u30d5\u30a9\u30ea\u30aa\u69cb\u9020\u5206\u6790")
    lines.append("")

    # --- Region breakdown ---
    lines.append("### \u5730\u57df\u5225\u914d\u5206")
    region_hhi = analysis.get("region_hhi", 0.0)
    region_breakdown = analysis.get("region_breakdown", {})

    lines.append("")
    lines.append("| \u5730\u57df | \u6bd4\u7387 | \u30d0\u30fc |")
    lines.append("|:-----|-----:|:-----|")
    for region, weight in sorted(region_breakdown.items(), key=lambda x: -x[1]):
        bar_len = int(round(weight * 20))
        bar = "\u2588" * bar_len
        lines.append(f"| {region} | {_fmt_pct(weight)} | {bar} |")
    lines.append("")
    lines.append(f"HHI: {_fmt_float(region_hhi, 4)} {_hhi_bar(region_hhi)} ({_classify_hhi(region_hhi)})")
    lines.append("")

    # --- Sector breakdown ---
    lines.append("### \u30bb\u30af\u30bf\u30fc\u5225\u914d\u5206")
    sector_hhi = analysis.get("sector_hhi", 0.0)
    sector_breakdown = analysis.get("sector_breakdown", {})

    lines.append("")
    lines.append("| \u30bb\u30af\u30bf\u30fc | \u6bd4\u7387 | \u30d0\u30fc |")
    lines.append("|:---------|-----:|:-----|")
    for sector, weight in sorted(sector_breakdown.items(), key=lambda x: -x[1]):
        bar_len = int(round(weight * 20))
        bar = "\u2588" * bar_len
        lines.append(f"| {sector} | {_fmt_pct(weight)} | {bar} |")
    lines.append("")
    lines.append(f"HHI: {_fmt_float(sector_hhi, 4)} {_hhi_bar(sector_hhi)} ({_classify_hhi(sector_hhi)})")
    lines.append("")

    # --- Currency breakdown ---
    lines.append("### \u901a\u8ca8\u5225\u914d\u5206")
    currency_hhi = analysis.get("currency_hhi", 0.0)
    currency_breakdown = analysis.get("currency_breakdown", {})

    lines.append("")
    lines.append("| \u901a\u8ca8 | \u6bd4\u7387 | \u30d0\u30fc |")
    lines.append("|:-----|-----:|:-----|")
    for currency, weight in sorted(currency_breakdown.items(), key=lambda x: -x[1]):
        bar_len = int(round(weight * 20))
        bar = "\u2588" * bar_len
        lines.append(f"| {currency} | {_fmt_pct(weight)} | {bar} |")
    lines.append("")
    lines.append(f"HHI: {_fmt_float(currency_hhi, 4)} {_hhi_bar(currency_hhi)} ({_classify_hhi(currency_hhi)})")
    lines.append("")

    # --- Overall judgment ---
    lines.append("### \u7dcf\u5408\u5224\u5b9a")
    max_hhi = analysis.get("max_hhi", 0.0)
    max_axis = analysis.get("max_hhi_axis", "-")
    multiplier = analysis.get("concentration_multiplier", 1.0)
    risk_level = analysis.get("risk_level", "-")

    axis_labels = {
        "sector": "\u30bb\u30af\u30bf\u30fc",
        "region": "\u5730\u57df",
        "currency": "\u901a\u8ca8",
    }
    axis_display = axis_labels.get(max_axis, max_axis)

    lines.append(f"- \u96c6\u4e2d\u5ea6\u500d\u7387: x{_fmt_float(multiplier, 2)}")
    lines.append(f"- \u30ea\u30b9\u30af\u30ec\u30d9\u30eb: **{risk_level}**")
    lines.append(f"- \u6700\u5927\u96c6\u4e2d\u8ef8: {axis_display} (HHI: {_fmt_float(max_hhi, 4)})")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# format_trade_result
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# format_health_check (KIK-356)
# ---------------------------------------------------------------------------

def format_health_check(health_data: dict) -> str:
    """Format portfolio health check results as a Markdown report.

    Parameters
    ----------
    health_data : dict
        Output from health_check.run_health_check().

    Returns
    -------
    str
        Markdown-formatted health check report.
    """
    lines: list[str] = []

    positions = health_data.get("positions", [])
    alerts = health_data.get("alerts", [])
    summary = health_data.get("summary", {})

    if not positions:
        lines.append("## \u4fdd\u6709\u9298\u67c4\u30d8\u30eb\u30b9\u30c1\u30a7\u30c3\u30af")
        lines.append("")
        lines.append("\u4fdd\u6709\u9298\u67c4\u304c\u3042\u308a\u307e\u305b\u3093\u3002")
        return "\n".join(lines)

    lines.append("## \u4fdd\u6709\u9298\u67c4\u30d8\u30eb\u30b9\u30c1\u30a7\u30c3\u30af")
    lines.append("")

    # Summary table
    lines.append(
        "| \u9298\u67c4 | \u640d\u76ca | \u30c8\u30ec\u30f3\u30c9 "
        "| \u5909\u5316\u306e\u8cea | \u30a2\u30e9\u30fc\u30c8 "
        "| \u9577\u671f\u9069\u6027 |"
    )
    lines.append("|:-----|-----:|:-------|:--------|:------------|:--------|")

    for pos in positions:
        symbol = pos.get("symbol", "-")
        pnl_pct = pos.get("pnl_pct", 0)
        pnl_str = _fmt_pct_sign(pnl_pct) if pnl_pct is not None else "-"

        trend = pos.get("trend_health", {}).get("trend", "不明")
        quality = pos.get("change_quality", {}).get("quality_label", "-")
        alert = pos.get("alert", {})
        alert_emoji = alert.get("emoji", "")
        alert_label = alert.get("label", "なし")

        if alert_emoji:
            alert_str = f"{alert_emoji} {alert_label}"
        else:
            alert_str = "なし"

        # Value trap indicator (KIK-381)
        vt = pos.get("value_trap", {})
        if vt.get("is_trap"):
            alert_str += " \U0001fa64"

        # Long-term suitability (KIK-371)
        lt = pos.get("long_term", {})
        lt_label = lt.get("label", "-")

        lines.append(
            f"| {symbol} | {pnl_str} | {trend} | {quality} | {alert_str} | {lt_label} |"
        )

    lines.append("")

    # Summary counts
    total = summary.get("total", 0)
    healthy = summary.get("healthy", 0)
    early = summary.get("early_warning", 0)
    caution = summary.get("caution", 0)
    exit_count = summary.get("exit", 0)
    lines.append(
        f"**{total}\u9298\u67c4**: "
        f"\u5065\u5168 {healthy} / "
        f"\u26a1\u65e9\u671f\u8b66\u544a {early} / "
        f"\u26a0\u6ce8\u610f {caution} / "
        f"\U0001f6a8\u64a4\u9000 {exit_count}"
    )
    lines.append("")

    # Alert details
    if alerts:
        lines.append("## \u30a2\u30e9\u30fc\u30c8\u8a73\u7d30")
        lines.append("")

        for pos in alerts:
            symbol = pos.get("symbol", "-")
            alert = pos.get("alert", {})
            emoji = alert.get("emoji", "")
            label = alert.get("label", "")
            reasons = alert.get("reasons", [])
            trend_h = pos.get("trend_health", {})
            change_q = pos.get("change_quality", {})
            change_score = change_q.get("change_score", 0)

            lines.append(f"### {emoji} {symbol}（{label}）")
            lines.append("")

            for reason in reasons:
                lines.append(f"- {reason}")

            # Additional context
            trend = trend_h.get("trend", "不明")
            rsi = trend_h.get("rsi", float("nan"))
            sma50 = trend_h.get("sma50", float("nan"))
            sma200 = trend_h.get("sma200", float("nan"))
            quality_label = change_q.get("quality_label", "-")

            lines.append(
                f"- \u30c8\u30ec\u30f3\u30c9: {trend}"
                f"\uff08SMA50={_fmt_float(sma50)}, "
                f"SMA200={_fmt_float(sma200)}, "
                f"RSI={_fmt_float(rsi)}\uff09"
            )
            lines.append(
                f"- \u5909\u5316\u306e\u8cea: {quality_label}"
                f"\uff08\u5909\u5316\u30b9\u30b3\u30a2 {change_score:.0f}/100\uff09"
            )

            # Long-term suitability context (KIK-371)
            lt = pos.get("long_term", {})
            lt_label = lt.get("label", "-")
            lt_summary = lt.get("summary", "")
            if lt_label not in ("対象外", "-"):
                lines.append(
                    f"- \u9577\u671f\u9069\u6027: {lt_label}"
                    f"\uff08{lt_summary}\uff09"
                )

            # Value trap warning (KIK-381)
            vt = pos.get("value_trap")
            if vt and vt.get("is_trap"):
                lines.append(
                    f"- \U0001fa64 **\u30d0\u30ea\u30e5\u30fc\u30c8\u30e9\u30c3\u30d7\u5146\u5019**: "
                    f"{', '.join(vt['reasons'])}"
                )

            # Action suggestion based on alert level
            level = alert.get("level", "none")
            if level == "early_warning":
                lines.append(
                    "\u2192 \u4e00\u6642\u7684\u306a\u8abf\u6574\u306e"
                    "\u53ef\u80fd\u6027\u3002\u30a6\u30a9\u30c3\u30c1\u5f37\u5316"
                )
            elif level == "caution":
                lines.append(
                    "\u2192 \u30dd\u30b8\u30b7\u30e7\u30f3\u7e2e\u5c0f"
                    "\u3092\u691c\u8a0e"
                )
            elif level == "exit":
                lines.append(
                    "\u2192 \u6295\u8cc7\u4eee\u8aac\u304c\u5d29\u58ca\u3002"
                    "exit\u3092\u691c\u8a0e"
                )

            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# format_trade_result
# ---------------------------------------------------------------------------

def format_trade_result(result: dict, action: str) -> str:
    """Format a buy/sell trade result as Markdown.

    Parameters
    ----------
    result : dict
        Expected keys:
        - "symbol": str
        - "shares": int (traded quantity)
        - "price": float (trade price)
        - "currency": str
        - "total_shares": int (updated holding)
        - "avg_cost": float (updated average cost)
        - "memo": str (optional)
    action : str
        "buy" or "sell" (or Japanese equivalents).

    Returns
    -------
    str
        Markdown-formatted trade result.
    """
    lines: list[str] = []

    # Normalize action label
    action_lower = action.lower()
    if action_lower in ("buy", "\u8cfc\u5165", "\u8cb7\u3044"):
        action_label = "\u8cfc\u5165"
    elif action_lower in ("sell", "\u58f2\u5374", "\u58f2\u308a"):
        action_label = "\u58f2\u5374"
    else:
        action_label = action

    symbol = result.get("symbol", "-")
    shares = result.get("shares", 0)
    price = result.get("price")
    currency = result.get("currency", "JPY")
    total_shares = result.get("total_shares")
    avg_cost = result.get("avg_cost")
    memo = result.get("memo") or ""

    lines.append("## \u58f2\u8cb7\u8a18\u9332")
    lines.append("")
    lines.append(f"- \u30a2\u30af\u30b7\u30e7\u30f3: **{action_label}**")
    lines.append(f"- \u9298\u67c4: {symbol}")
    if memo:
        lines.append(f"- \u30e1\u30e2: {memo}")
    lines.append(f"- \u682a\u6570: {shares:,}")
    if price is not None:
        lines.append(f"- \u5358\u4fa1: {_fmt_currency_value(price, currency)}")

    if total_shares is not None:
        avg_cost_str = _fmt_currency_value(avg_cost, currency) if avg_cost is not None else "-"
        lines.append(
            f"- \u66f4\u65b0\u5f8c\u306e\u4fdd\u6709: {total_shares:,}\u682a "
            f"(\u5e73\u5747\u53d6\u5f97\u5358\u4fa1: {avg_cost_str})"
        )

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# format_return_estimate (KIK-359)
# ---------------------------------------------------------------------------

def format_return_estimate(estimate: dict) -> str:
    """Format portfolio return estimation as a Markdown report.

    Parameters
    ----------
    estimate : dict
        Output from return_estimate.estimate_portfolio_return().
        Expected keys:
        - "positions": list[dict] with per-stock estimates
        - "portfolio": {"optimistic": float, "base": float, "pessimistic": float}
        - "total_value_jpy": float
        - "fx_rates": dict

    Returns
    -------
    str
        Markdown-formatted return estimation report.
    """
    lines: list[str] = []

    portfolio = estimate.get("portfolio", {})
    positions = estimate.get("positions", [])
    total_value = estimate.get("total_value_jpy", 0)

    if not positions:
        lines.append("## \u63a8\u5b9a\u5229\u56de\u308a\uff0812\u30f6\u6708\uff09")
        lines.append("")
        lines.append("\u4fdd\u6709\u9298\u67c4\u304c\u3042\u308a\u307e\u305b\u3093\u3002")
        return "\n".join(lines)

    # --- Portfolio summary ---
    lines.append("## \u63a8\u5b9a\u5229\u56de\u308a\uff0812\u30f6\u6708\uff09")
    lines.append("")

    lines.append("| \u30b7\u30ca\u30ea\u30aa | \u5229\u56de\u308a | \u640d\u76ca\u984d |")
    lines.append("|:---------|------:|------:|")

    for label, key in [
        ("\u697d\u89b3", "optimistic"),
        ("\u30d9\u30fc\u30b9", "base"),
        ("\u60b2\u89b3", "pessimistic"),
    ]:
        ret = portfolio.get(key)
        if ret is not None:
            pnl_amount = ret * total_value if total_value else 0
            lines.append(
                f"| {label} | {_fmt_pct_sign(ret)} | {_fmt_jpy(pnl_amount)} |"
            )
        else:
            lines.append(f"| {label} | - | - |")

    lines.append("")
    lines.append(f"\u7dcf\u8a55\u4fa1\u984d: {_fmt_jpy(total_value)}")
    lines.append("")

    # --- Warning summary (KIK-390) ---
    warnings = [
        p for p in positions if p.get("value_trap_warning")
    ]
    if warnings:
        lines.append("### \u26a0\ufe0f \u6ce8\u610f\u9298\u67c4")
        lines.append("")
        for w in warnings:
            lines.append(f"- **{w['symbol']}**: {w['value_trap_warning']}")
        lines.append("")

    # --- TOP 3 / BOTTOM 3 (KIK-390) ---
    ranked = [
        p for p in positions
        if p.get("base") is not None and p.get("method") != "no_data"
    ]
    ranked.sort(key=lambda p: p["base"], reverse=True)

    if len(ranked) >= 2:
        top_n = ranked[:3]
        bottom_n = ranked[-3:] if len(ranked) >= 6 else ranked[-min(3, len(ranked)):]
        # Deduplicate if overlap (small portfolios)
        bottom_symbols = {p["symbol"] for p in bottom_n}
        top_symbols = {p["symbol"] for p in top_n}

        lines.append("### \U0001f51d \u671f\u5f85\u30ea\u30bf\u30fc\u30f3 TOP")
        lines.append("")
        for i, p in enumerate(top_n, 1):
            count = p.get("analyst_count")
            count_str = f" ({count}\u540d)" if count else ""
            lines.append(
                f"{i}. **{p['symbol']}** {_fmt_pct_sign(p['base'])}{count_str}"
            )
        lines.append("")

        # Only show BOTTOM if there are stocks not already in TOP
        bottom_only = [p for p in bottom_n if p["symbol"] not in top_symbols]
        if bottom_only:
            lines.append("### \U0001f4c9 \u671f\u5f85\u30ea\u30bf\u30fc\u30f3 BOTTOM")
            lines.append("")
            for i, p in enumerate(bottom_only, 1):
                count = p.get("analyst_count")
                count_str = f" ({count}\u540d)" if count else ""
                lines.append(
                    f"{i}. **{p['symbol']}** {_fmt_pct_sign(p['base'])}{count_str}"
                )
            lines.append("")

    # --- Per-stock details ---
    for pos in positions:
        symbol = pos.get("symbol", "-")
        base_ret = pos.get("base")
        method = pos.get("method", "")
        currency = pos.get("currency", "USD")

        # Header
        base_str = _fmt_pct_sign(base_ret) if base_ret is not None else "-"
        lines.append(f"### {symbol} \u671f\u5f85\u30ea\u30bf\u30fc\u30f3: {base_str}\uff08\u30d9\u30fc\u30b9\uff09")
        lines.append("")

        # Quantitative section
        if method == "no_data":
            lines.append("\u3010\u5b9a\u91cf\u3011\u30c7\u30fc\u30bf\u53d6\u5f97\u5931\u6557")
            lines.append("  \u2192 \u60b2\u89b3 - / \u30d9\u30fc\u30b9 - / \u697d\u89b3 -")
        elif method == "analyst":
            target_mean = pos.get("target_mean")
            analyst_count = pos.get("analyst_count")
            forward_per = pos.get("forward_per")

            target_str = _fmt_currency_value(target_mean, currency) if target_mean else "-"
            count_str = f"{analyst_count}\u540d" if analyst_count else "-"
            fpe_str = f"{forward_per:.1f}x" if forward_per else "-"
            confidence = "\u53c2\u8003\u5024" if (analyst_count or 0) < 5 else ""
            confidence_suffix = f" \u203b{confidence}" if confidence else ""

            lines.append(
                f"\u3010\u5b9a\u91cf\u3011\u30a2\u30ca\u30ea\u30b9\u30c8\u76ee\u6a19 {target_str}"
                f"\uff08{count_str}\uff09"
                f"\u3001Forward PER {fpe_str}"
                f"{confidence_suffix}"
            )
        else:
            data_months = pos.get("data_months", 0)
            lines.append(
                f"\u3010\u5b9a\u91cf\u3011\u904e\u53bb\u30ea\u30bf\u30fc\u30f3\u5206\u5e03"
                f"\uff08{data_months}\u30f6\u6708\u5206\uff09"
            )

        # News and sentiment sections (skip for no_data)
        if method != "no_data":
            # News section - count only (KIK-390)
            news = pos.get("news", [])
            if news:
                lines.append(f"\u3010\u30cb\u30e5\u30fc\u30b9\u3011{len(news)}\u4ef6")

            # X Sentiment section
            x_sentiment = pos.get("x_sentiment")
            if x_sentiment and (x_sentiment.get("positive") or x_sentiment.get("negative")):
                lines.append("\u3010X \u30bb\u30f3\u30c1\u30e1\u30f3\u30c8\u3011")
                for factor in (x_sentiment.get("positive") or [])[:3]:
                    lines.append(f"  \u25b2 {factor}")
                for factor in (x_sentiment.get("negative") or [])[:3]:
                    lines.append(f"  \u25bc {factor}")

            # 3-scenario summary
            opt = pos.get("optimistic")
            base_r = pos.get("base")
            pess = pos.get("pessimistic")
            if opt is not None and base_r is not None and pess is not None:
                lines.append(
                    f"  \u2192 \u60b2\u89b3 {_fmt_pct_sign(pess)} / "
                    f"\u30d9\u30fc\u30b9 {_fmt_pct_sign(base_r)} / "
                    f"\u697d\u89b3 {_fmt_pct_sign(opt)}"
                )

            # Value trap warning (KIK-385)
            vt_warning = pos.get("value_trap_warning")
            if vt_warning:
                lines.append(f"  \U0001fa64 **\u30d0\u30ea\u30e5\u30fc\u30c8\u30e9\u30c3\u30d7\u5146\u5019**: {vt_warning}")

        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rebalance proposal (KIK-363)
# ---------------------------------------------------------------------------

def _fmt_k(value: Optional[float]) -> str:
    """Format a value in K (thousands) notation, e.g. 10000000 -> '¥10,000K'."""
    if value is None:
        return "-"
    k = value / 1000
    if k < 0:
        return f"-\u00a5{abs(k):,.0f}K"
    return f"\u00a5{k:,.0f}K"


# ---------------------------------------------------------------------------
# format_simulation (KIK-366)
# ---------------------------------------------------------------------------

def format_simulation(result) -> str:
    """Format compound interest simulation results as Markdown.

    Parameters
    ----------
    result : SimulationResult or dict
        Output from simulator.simulate_portfolio().

    Returns
    -------
    str
        Markdown-formatted simulation report.
    """
    # Support both SimulationResult and dict
    if hasattr(result, "to_dict"):
        d = result.to_dict()
    else:
        d = result

    scenarios = d.get("scenarios", {})
    years = d.get("years", 0)
    monthly_add = d.get("monthly_add", 0.0)
    reinvest_dividends = d.get("reinvest_dividends", True)
    target = d.get("target")

    lines: list[str] = []

    # Empty scenarios
    if not scenarios:
        lines.append("## \u8907\u5229\u30b7\u30df\u30e5\u30ec\u30fc\u30b7\u30e7\u30f3")
        lines.append("")
        lines.append(
            "\u63a8\u5b9a\u30ea\u30bf\u30fc\u30f3\u304c\u53d6\u5f97\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002"
            "\u5148\u306b /stock-portfolio forecast \u3092\u5b9f\u884c\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
        )
        return "\n".join(lines)

    # Header
    if monthly_add > 0:
        add_str = f"\u6708{monthly_add:,.0f}\u5186\u7a4d\u7acb"
    else:
        add_str = "\u7a4d\u7acb\u306a\u3057"
    lines.append(f"## {years}\u5e74\u30b7\u30df\u30e5\u30ec\u30fc\u30b7\u30e7\u30f3\uff08{add_str}\uff09")
    lines.append("")

    # Base scenario table
    base_snapshots = scenarios.get("base", [])
    if base_snapshots:
        base_return = d.get("portfolio_return_base")
        if base_return is not None:
            ret_str = f"{base_return * 100:+.2f}%"
        else:
            ret_str = "-"
        lines.append(f"### \u30d9\u30fc\u30b9\u30b7\u30ca\u30ea\u30aa\uff08\u5e74\u5229 {ret_str}\uff09")
        lines.append("")
        lines.append("| \u5e74 | \u8a55\u4fa1\u984d | \u7d2f\u8a08\u6295\u5165 | \u904b\u7528\u76ca | \u914d\u5f53\u7d2f\u8a08 |")
        lines.append("|----|--------|----------|--------|----------|")

        for snap in base_snapshots:
            yr = snap.get("year", 0) if isinstance(snap, dict) else snap.year
            value = snap.get("value", 0) if isinstance(snap, dict) else snap.value
            cum_input = snap.get("cumulative_input", 0) if isinstance(snap, dict) else snap.cumulative_input
            cap_gain = snap.get("capital_gain", 0) if isinstance(snap, dict) else snap.capital_gain
            cum_div = snap.get("cumulative_dividends", 0) if isinstance(snap, dict) else snap.cumulative_dividends

            if yr == 0:
                lines.append(
                    f"| {yr} | {_fmt_k(value)} | {_fmt_k(cum_input)} | - | - |"
                )
            else:
                lines.append(
                    f"| {yr} | {_fmt_k(value)} | {_fmt_k(cum_input)} "
                    f"| {_fmt_k(cap_gain)} | {_fmt_k(cum_div)} |"
                )

        lines.append("")

    # Scenario comparison (final year)
    scenario_labels = {
        "optimistic": "\u697d\u89b3",
        "base": "\u30d9\u30fc\u30b9",
        "pessimistic": "\u60b2\u89b3",
    }
    returns_map = d.get("scenarios", {})
    portfolio_return_base = d.get("portfolio_return_base")

    # Get return rates from the original returns dict if available
    # We infer from the data we have
    has_comparison = len(scenarios) > 1 or (len(scenarios) == 1 and "base" in scenarios)
    if has_comparison:
        lines.append(
            "### \u30b7\u30ca\u30ea\u30aa\u6bd4\u8f03\uff08\u6700\u7d42\u5e74\uff09"
        )
        lines.append("")
        lines.append("| \u30b7\u30ca\u30ea\u30aa | \u6700\u7d42\u8a55\u4fa1\u984d | \u904b\u7528\u76ca |")
        lines.append("|:---------|----------:|-------:|")

        for key in ["optimistic", "base", "pessimistic"]:
            snaps = scenarios.get(key)
            if not snaps:
                continue
            last = snaps[-1]
            value = last.get("value", 0) if isinstance(last, dict) else last.value
            cap_gain = last.get("capital_gain", 0) if isinstance(last, dict) else last.capital_gain
            label = scenario_labels.get(key, key)
            lines.append(
                f"| {label} | {_fmt_k(value)} | {_fmt_k(cap_gain)} |"
            )

        lines.append("")

    # Target analysis
    if target is not None:
        lines.append("### \u76ee\u6a19\u9054\u6210\u5206\u6790")
        lines.append("")
        lines.append(f"- \u76ee\u6a19\u984d: {_fmt_k(target)}")

        target_year_base = d.get("target_year_base")
        target_year_opt = d.get("target_year_optimistic")
        target_year_pess = d.get("target_year_pessimistic")

        if target_year_base is not None:
            lines.append(
                f"- \u30d9\u30fc\u30b9\u30b7\u30ca\u30ea\u30aa: "
                f"**{target_year_base:.1f}\u5e74\u3067\u9054\u6210\u898b\u8fbc\u307f**"
            )
        else:
            lines.append(
                "- \u30d9\u30fc\u30b9\u30b7\u30ca\u30ea\u30aa: \u671f\u9593\u5185\u672a\u9054"
            )

        if target_year_opt is not None:
            lines.append(
                f"- \u697d\u89b3\u30b7\u30ca\u30ea\u30aa: "
                f"{target_year_opt:.1f}\u5e74\u3067\u9054\u6210\u898b\u8fbc\u307f"
            )
        elif "optimistic" in scenarios:
            lines.append(
                "- \u697d\u89b3\u30b7\u30ca\u30ea\u30aa: \u671f\u9593\u5185\u672a\u9054"
            )

        if target_year_pess is not None:
            lines.append(
                f"- \u60b2\u89b3\u30b7\u30ca\u30ea\u30aa: "
                f"{target_year_pess:.1f}\u5e74\u3067\u9054\u6210\u898b\u8fbc\u307f"
            )
        elif "pessimistic" in scenarios:
            lines.append(
                "- \u60b2\u89b3\u30b7\u30ca\u30ea\u30aa: \u671f\u9593\u5185\u672a\u9054"
            )

        required_monthly = d.get("required_monthly")
        if required_monthly is not None and required_monthly > 0:
            lines.append("")
            lines.append(
                f"- \u76ee\u6a19\u9054\u6210\u306b\u5fc5\u8981\u306a\u6708\u984d\u7a4d\u7acb: "
                f"\u00a5{required_monthly:,.0f}"
            )

        lines.append("")

    # Dividend reinvestment effect
    dividend_effect = d.get("dividend_effect", 0)
    dividend_effect_pct = d.get("dividend_effect_pct", 0)

    lines.append(
        "### \u914d\u5f53\u518d\u6295\u8cc7\u306e\u52b9\u679c"
    )
    lines.append("")

    if not reinvest_dividends:
        lines.append("- \u914d\u5f53\u518d\u6295\u8cc7: OFF")
    else:
        lines.append(
            f"- \u914d\u5f53\u518d\u6295\u8cc7\u306b\u3088\u308b\u8907\u5229\u52b9\u679c: "
            f"+{_fmt_k(dividend_effect)}"
        )
        lines.append(
            f"- \u914d\u5f53\u306a\u3057\u6bd4: "
            f"+{dividend_effect_pct * 100:.1f}%"
        )

    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# format_what_if (KIK-376)
# ---------------------------------------------------------------------------

_JUDGMENT_EMOJI = {
    "recommend": "\u2705",       # ✅
    "caution": "\u26a0\ufe0f",   # ⚠️
    "not_recommended": "\U0001f6a8",  # 🚨
}

_JUDGMENT_LABEL = {
    "recommend": "この追加は推奨",
    "caution": "注意して検討",
    "not_recommended": "この追加は非推奨",
}


def format_what_if(result: dict) -> str:
    """Format What-If simulation result as Markdown.

    Parameters
    ----------
    result : dict
        Output from portfolio_simulation.run_what_if_simulation().

    Returns
    -------
    str
        Markdown-formatted What-If report.
    """
    lines: list[str] = []

    proposed = result.get("proposed", [])
    before = result.get("before", {})
    after = result.get("after", {})
    proposed_health = result.get("proposed_health", [])
    required_cash = result.get("required_cash_jpy", 0)
    judgment = result.get("judgment", {})

    lines.append("## What-If \u30b7\u30df\u30e5\u30ec\u30fc\u30b7\u30e7\u30f3")
    lines.append("")

    # --- Proposed stocks ---
    lines.append("### \u8ffd\u52a0\u9298\u67c4")
    lines.append("")
    lines.append(
        "| \u9298\u67c4 | \u682a\u6570 | \u5358\u4fa1 | \u901a\u8ca8 "
        "| \u91d1\u984d |"
    )
    lines.append("|:-----|-----:|------:|:-----|------:|")

    for prop in proposed:
        symbol = prop.get("symbol", "-")
        shares = prop.get("shares", 0)
        price = prop.get("cost_price", 0)
        currency = prop.get("cost_currency", "JPY")
        amount = shares * price
        price_str = _fmt_currency_value(price, currency)
        amount_str = _fmt_currency_value(amount, currency)
        lines.append(
            f"| {symbol} | {shares:,} | {price_str} "
            f"| {currency} | {amount_str} |"
        )

    lines.append("")
    lines.append(
        f"\u5fc5\u8981\u8cc7\u91d1\u5408\u8a08: {_fmt_jpy(required_cash)}"
    )
    lines.append("")

    # --- Portfolio change comparison ---
    lines.append("### \u30dd\u30fc\u30c8\u30d5\u30a9\u30ea\u30aa\u5909\u5316")
    lines.append("")
    lines.append(
        "| \u6307\u6a19 | \u73fe\u5728 | \u8ffd\u52a0\u5f8c | \u5909\u5316 |"
    )
    lines.append("|:-----|------:|------:|:------|")

    # Total value
    bv = before.get("total_value_jpy", 0)
    av = after.get("total_value_jpy", 0)
    if bv > 0:
        change_pct = (av - bv) / bv
        change_str = _fmt_pct_sign(change_pct)
    else:
        change_str = "-"
    lines.append(
        f"| \u7dcf\u8a55\u4fa1\u984d | {_fmt_jpy(bv)} "
        f"| {_fmt_jpy(av)} | {change_str} |"
    )

    # Sector HHI
    b_shhi = before.get("sector_hhi", 0)
    a_shhi = after.get("sector_hhi", 0)
    hhi_indicator = (
        "\u2705 \u6539\u5584" if a_shhi < b_shhi
        else "\u26a0\ufe0f \u60aa\u5316" if a_shhi > b_shhi
        else "\u2194\ufe0f \u5909\u5316\u306a\u3057"
    )
    lines.append(
        f"| \u30bb\u30af\u30bf\u30fcHHI | {_fmt_float(b_shhi, 2)} "
        f"| {_fmt_float(a_shhi, 2)} | {hhi_indicator} |"
    )

    # Region HHI
    b_rhhi = before.get("region_hhi", 0)
    a_rhhi = after.get("region_hhi", 0)
    rhhi_indicator = (
        "\u2705 \u6539\u5584" if a_rhhi < b_rhhi
        else "\u26a0\ufe0f \u60aa\u5316" if a_rhhi > b_rhhi
        else "\u2194\ufe0f \u5909\u5316\u306a\u3057"
    )
    lines.append(
        f"| \u5730\u57dfHHI | {_fmt_float(b_rhhi, 2)} "
        f"| {_fmt_float(a_rhhi, 2)} | {rhhi_indicator} |"
    )

    # Forecast base return
    b_ret = before.get("forecast_base")
    a_ret = after.get("forecast_base")
    if b_ret is not None and a_ret is not None:
        diff_pp = (a_ret - b_ret) * 100
        ret_indicator = (
            f"\u2705 +{diff_pp:.1f}pp" if diff_pp > 0
            else f"\u26a0\ufe0f {diff_pp:.1f}pp" if diff_pp < 0
            else "\u2194\ufe0f 0pp"
        )
        lines.append(
            f"| \u671f\u5f85\u30ea\u30bf\u30fc\u30f3(\u30d9\u30fc\u30b9) "
            f"| {_fmt_pct_sign(b_ret)} "
            f"| {_fmt_pct_sign(a_ret)} | {ret_indicator} |"
        )
    lines.append("")

    # --- Proposed stock health ---
    if proposed_health:
        lines.append(
            "### \u63d0\u6848\u9298\u67c4\u30d8\u30eb\u30b9\u30c1\u30a7\u30c3\u30af"
        )
        lines.append("")
        for ph in proposed_health:
            symbol = ph.get("symbol", "-")
            alert = ph.get("alert", {})
            level = alert.get("level", "none")
            label = alert.get("label", "\u306a\u3057")
            if level == "none":
                lines.append(f"\u2705 {symbol}: OK")
            elif level == "early_warning":
                lines.append(f"\u26a1 {symbol}: {label}")
            elif level == "caution":
                lines.append(f"\u26a0\ufe0f {symbol}: {label}")
            elif level == "exit":
                lines.append(f"\U0001f6a8 {symbol}: {label}")
        lines.append("")

    # --- Judgment ---
    lines.append("### \u7dcf\u5408\u5224\u5b9a")
    lines.append("")
    rec = judgment.get("recommendation", "caution")
    emoji = _JUDGMENT_EMOJI.get(rec, "")
    label = _JUDGMENT_LABEL.get(rec, rec)
    lines.append(f"{emoji} **{label}**")
    for reason in judgment.get("reasons", []):
        lines.append(f"- {reason}")
    lines.append("")

    return "\n".join(lines)


_ACTION_LABELS = {
    "sell": "売り",
    "reduce": "減らす",
    "increase": "増やす",
}

_ACTION_EMOJI = {
    "sell": "\U0001f534",      # red circle
    "reduce": "\U0001f7e1",    # yellow circle
    "increase": "\U0001f7e2",  # green circle
}


def format_rebalance_report(proposal: dict) -> str:
    """Format a rebalance proposal as markdown.

    Parameters
    ----------
    proposal : dict
        Output of rebalancer.generate_rebalance_proposal().

    Returns
    -------
    str
        Markdown-formatted report.
    """
    lines: list[str] = []

    strategy = proposal.get("strategy", "balanced")
    strategy_label = {
        "defensive": "ディフェンシブ",
        "balanced": "バランス",
        "aggressive": "アグレッシブ",
    }.get(strategy, strategy)
    lines.append(f"## リバランス提案 ({strategy_label})")
    lines.append("")

    # --- Before / After ---
    before = proposal.get("before", {})
    after = proposal.get("after", {})

    lines.append("### 現在 → 提案後")
    lines.append("")
    lines.append("| 指標 | 現在 | 提案後 |")
    lines.append("|:-----|-----:|------:|")
    lines.append(
        f"| ベース期待値 | {_fmt_pct_sign(before.get('base_return'))} "
        f"| {_fmt_pct_sign(after.get('base_return'))} |"
    )
    lines.append(
        f"| セクターHHI | {_fmt_float(before.get('sector_hhi'), 4)} "
        f"| {_fmt_float(after.get('sector_hhi'), 4)} |"
    )
    lines.append(
        f"| 地域HHI | {_fmt_float(before.get('region_hhi'), 4)} "
        f"| {_fmt_float(after.get('region_hhi'), 4)} |"
    )
    lines.append("")

    # --- Cash summary ---
    freed = proposal.get("freed_cash_jpy", 0)
    additional = proposal.get("additional_cash_jpy", 0)
    if freed > 0 or additional > 0:
        lines.append("### 資金")
        lines.append("")
        if freed > 0:
            lines.append(f"- **売却・削減による確保資金:** {freed:,.0f}円")
        if additional > 0:
            lines.append(f"- **追加投入資金:** {additional:,.0f}円")
        lines.append(f"- **合計利用可能資金:** {freed + additional:,.0f}円")
        lines.append("")

    # --- Actions ---
    actions = proposal.get("actions", [])
    if not actions:
        lines.append("### アクション")
        lines.append("")
        lines.append("現在のポートフォリオは制約範囲内です。リバランス不要。")
        lines.append("")
        return "\n".join(lines)

    lines.append("### アクション")
    lines.append("")

    for i, action in enumerate(actions, 1):
        act_type = action.get("action", "")
        emoji = _ACTION_EMOJI.get(act_type, "")
        label = _ACTION_LABELS.get(act_type, act_type)
        symbol = action.get("symbol", "")
        name = action.get("name", "")
        name_str = f" {name}" if name else ""
        reason = action.get("reason", "")

        if act_type == "sell":
            value = action.get("value_jpy", 0)
            lines.append(
                f"{i}. {emoji} **{label}**: {symbol}{name_str} 全株"
                f" → {reason}"
            )
            if value > 0:
                lines.append(f"   確保資金: {value:,.0f}円")
        elif act_type == "reduce":
            ratio = action.get("ratio", 0)
            value = action.get("value_jpy", 0)
            lines.append(
                f"{i}. {emoji} **{label}**: {symbol}{name_str}"
                f" {ratio*100:.0f}%削減 → {reason}"
            )
            if value > 0:
                lines.append(f"   確保資金: {value:,.0f}円")
        elif act_type == "increase":
            amount = action.get("amount_jpy", 0)
            lines.append(
                f"{i}. {emoji} **{label}**: {symbol}{name_str}"
                f" +{amount:,.0f}円 → {reason}"
            )

        lines.append("")

    # --- Constraints ---
    constraints = proposal.get("constraints", {})
    if constraints:
        lines.append("### 適用制約")
        lines.append("")
        lines.append(
            f"- 1銘柄上限: {constraints.get('max_single_ratio', 0)*100:.0f}%"
        )
        lines.append(
            f"- セクターHHI上限: {constraints.get('max_sector_hhi', 0):.2f}"
        )
        lines.append(
            f"- 地域HHI上限: {constraints.get('max_region_hhi', 0):.2f}"
        )
        lines.append(
            f"- 相関ペア合計上限:"
            f" {constraints.get('max_corr_pair_ratio', 0)*100:.0f}%"
        )
        lines.append("")

    return "\n".join(lines)
