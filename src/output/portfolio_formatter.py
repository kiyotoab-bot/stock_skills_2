"""Output formatters for portfolio management (KIK-342).

This module retains the core formatters (snapshot, position list, trade result)
and re-exports the feature-specific formatters from their dedicated modules
for backward compatibility (KIK-447).
"""

from datetime import datetime
from typing import Optional

from src.output._format_helpers import fmt_pct as _fmt_pct
from src.output._format_helpers import fmt_pct_sign as _fmt_pct_sign
from src.output._format_helpers import fmt_float as _fmt_float
from src.output._format_helpers import hhi_bar as _hhi_bar
from src.output._portfolio_utils import (
    _fmt_jpy,
    _fmt_usd,
    _fmt_currency_value,
    _pnl_indicator,
    _classify_hhi,
    _fmt_k,
)

# Re-export feature-specific formatters for backward compatibility
from src.output.health_formatter import format_health_check
from src.output.forecast_formatter import format_return_estimate
from src.output.analyze_formatter import (
    format_structure_analysis,
    format_shareholder_return_analysis,
)
from src.output.rebalance_formatter import format_rebalance_report
from src.output.simulate_formatter import format_simulation, format_what_if
from src.output.review_formatter import format_performance_review

__all__ = [
    "format_snapshot",
    "format_position_list",
    "format_trade_result",
    "format_health_check",
    "format_return_estimate",
    "format_structure_analysis",
    "format_shareholder_return_analysis",
    "format_rebalance_report",
    "format_simulation",
    "format_what_if",
    "format_performance_review",
]


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

    # KIK-441: sell 時に P&L がある場合は追加表示
    if action_lower in ("sell", "\u58f2\u5374", "\u58f2\u308a"):
        realized_pnl = result.get("realized_pnl")
        pnl_rate = result.get("pnl_rate")
        hold_days = result.get("hold_days")
        sell_price_val = result.get("sell_price")
        cost_price_val = result.get("cost_price")

        if realized_pnl is not None:
            lines.append("")
            lines.append("### \u5b9f\u73fe\u640d\u76ca")
            if cost_price_val is not None:
                lines.append(
                    f"- \u53d6\u5f97\u5358\u4fa1: {_fmt_currency_value(cost_price_val, currency)}"
                )
            if sell_price_val is not None:
                lines.append(
                    f"- 売却単価: {_fmt_currency_value(sell_price_val, currency)}"
                )
            if hold_days is not None:
                lines.append(f"- \u4fdd\u6709\u671f\u9593: {hold_days}\u65e5")
            sign = "+" if realized_pnl >= 0 else ""
            rate_str = (
                f" ({sign}{pnl_rate * 100:.2f}%)" if pnl_rate is not None else ""
            )
            lines.append(
                f"- \u5b9f\u73fe\u640d\u76ca: **{sign}{_fmt_currency_value(realized_pnl, currency)}**{rate_str}"
            )
            # 税引後概算（20%課税）
            after_tax = realized_pnl * 0.80
            sign2 = "+" if after_tax >= 0 else ""
            lines.append(
                f"- \u7a0e\u5f15\u5f8c\u6982\u7b97: {sign2}{_fmt_currency_value(after_tax, currency)}\uff0820%\u8ab2\u7a0e\u60f3\u5b9a\uff09"
            )

    lines.append("")
    return "\n".join(lines)
