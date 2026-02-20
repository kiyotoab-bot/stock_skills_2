"""Internal normalization and sanitization utilities (KIK-449)."""

from typing import Any, Optional


def _safe_get(info: dict, key: str) -> Any:
    """Safely retrieve a value from the info dict, returning None on failure."""
    try:
        value = info.get(key)
        if value is None:
            return None
        # yfinance occasionally returns 'Infinity' or NaN
        if isinstance(value, float) and (value != value or abs(value) == float("inf")):
            return None
        return value
    except Exception:
        return None


def _normalize_ratio(value: Any) -> Optional[float]:
    """Convert yfinance percentage value to ratio.

    yfinance returns dividendYield as a percentage (e.g. 3.87 for 3.87%,
    0.41 for 0.41%).  Always divide by 100 to get ratio form.
    """
    if value is None:
        return None
    return value / 100.0


def _sanitize_anomalies(data: dict) -> dict:
    """Sanitize anomalous financial data values to None.

    Yahoo Finance occasionally returns extreme values (e.g. 78% dividend yield
    from special dividends, PBR 0.01 from accounting anomalies) that would
    distort screening results.
    """
    # dividend_yield: max 15%
    dy = data.get("dividend_yield")
    if dy is not None and dy > 0.15:
        data["dividend_yield"] = None

    # dividend_yield_trailing: max 15%
    dy_t = data.get("dividend_yield_trailing")
    if dy_t is not None and dy_t > 0.15:
        data["dividend_yield_trailing"] = None

    # pbr: min 0.05
    pbr = data.get("pbr")
    if pbr is not None and pbr < 0.05:
        data["pbr"] = None

    # per: min 1.0 (negative/zero already handled by scorers)
    per = data.get("per")
    if per is not None and 0 < per < 1.0:
        data["per"] = None

    # roe: -100% to 200%
    roe = data.get("roe")
    if roe is not None and (roe < -1.0 or roe > 2.0):
        data["roe"] = None

    return data
