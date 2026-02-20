"""Shared private helpers for portfolio formatter modules (KIK-447)."""

from typing import Optional


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


def _fmt_k(value: Optional[float]) -> str:
    """Format a value in K (thousands) notation, e.g. 10000000 -> '¥10,000K'."""
    if value is None:
        return "-"
    k = value / 1000
    if k < 0:
        return f"-\u00a5{abs(k):,.0f}K"
    return f"\u00a5{k:,.0f}K"
