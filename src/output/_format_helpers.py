"""Shared formatting helpers used across all output formatters (KIK-394)."""

from typing import Optional


def fmt_pct(value: Optional[float]) -> str:
    """Format a decimal ratio as a percentage string (e.g. 0.035 -> '3.50%')."""
    if value is None:
        return "-"
    return f"{value * 100:.2f}%"


def fmt_float(value: Optional[float], decimals: int = 2) -> str:
    """Format a float with the given decimal places, or '-' if None."""
    if value is None:
        return "-"
    return f"{value:.{decimals}f}"


def fmt_pct_sign(value: Optional[float]) -> str:
    """Format a decimal ratio as a signed percentage (e.g. -0.12 -> '-12.00%')."""
    if value is None:
        return "-"
    return f"{value * 100:+.2f}%"


def fmt_float_sign(value: Optional[float], decimals: int = 2) -> str:
    """Format a float with sign and given decimal places."""
    if value is None:
        return "-"
    return f"{value:+.{decimals}f}"


def build_label(row: dict) -> str:
    """Build stock label with annotation markers (KIK-418/419).

    Combines symbol + name + any note markers from screen_annotator.
    """
    symbol = row.get("symbol", "-")
    name = row.get("name") or ""
    label = f"{symbol} {name}".strip() if name else symbol
    markers = row.get("_note_markers", "")
    if markers:
        label = f"{label} {markers}"
    return label


def hhi_bar(hhi: float, width: int = 10) -> str:
    """Render a simple text bar for HHI value (0-1 scale)."""
    filled = int(round(hhi * width))
    filled = max(0, min(filled, width))
    return "[" + "#" * filled + "." * (width - filled) + "]"
