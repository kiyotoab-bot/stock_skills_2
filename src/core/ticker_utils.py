"""Ticker symbol utilities: currency/country inference from symbol suffixes.

Merged from portfolio_manager.py and scenario_analysis.py to provide
a single source of truth for suffix-based lookups.
"""

from src.core.common import is_cash


# Comprehensive suffix -> country mapping (from portfolio_manager.py)
SUFFIX_TO_COUNTRY = {
    ".T": "Japan",
    ".SI": "Singapore",
    ".BK": "Thailand",
    ".KL": "Malaysia",
    ".JK": "Indonesia",
    ".PS": "Philippines",
    ".HK": "Hong Kong",
    ".KS": "South Korea",
    ".KQ": "South Korea",
    ".TW": "Taiwan",
    ".TWO": "Taiwan",
    ".SS": "China",
    ".SZ": "China",
    ".L": "United Kingdom",
    ".DE": "Germany",
    ".PA": "France",
    ".TO": "Canada",
    ".AX": "Australia",
    ".SA": "Brazil",
    ".NS": "India",
    ".BO": "India",
}

# Comprehensive suffix -> currency mapping (from portfolio_manager.py)
SUFFIX_TO_CURRENCY = {
    ".T": "JPY",
    ".SI": "SGD",
    ".BK": "THB",
    ".KL": "MYR",
    ".JK": "IDR",
    ".PS": "PHP",
    ".HK": "HKD",
    ".KS": "KRW",
    ".KQ": "KRW",
    ".TW": "TWD",
    ".TWO": "TWD",
    ".SS": "CNY",
    ".SZ": "CNY",
    ".L": "GBP",
    ".DE": "EUR",
    ".PA": "EUR",
    ".TO": "CAD",
    ".AX": "AUD",
    ".SA": "BRL",
    ".NS": "INR",
    ".BO": "INR",
}


def cash_currency(symbol: str) -> str:
    """Extract currency from cash symbol (e.g., 'JPY.CASH' -> 'JPY')."""
    return symbol.upper().replace(".CASH", "")


def infer_currency(symbol: str, info: dict | None = None) -> str:
    """Infer the currency from the ticker symbol suffix.

    If *info* is provided and contains a 'currency' key, that value
    is returned directly (used by scenario_analysis).  Otherwise
    falls back to suffix-based lookup.
    """
    if info is not None:
        currency_from_info = info.get("currency")
        if currency_from_info:
            return currency_from_info
    if is_cash(symbol):
        return cash_currency(symbol)
    for suffix, currency in SUFFIX_TO_CURRENCY.items():
        if symbol.upper().endswith(suffix.upper()):
            return currency
    # No suffix typically means USD
    if "." not in symbol:
        return "USD"
    return "USD"


def infer_country(symbol: str, info: dict | None = None) -> str:
    """Infer the country/region from the ticker symbol suffix.

    If *info* is provided and contains 'country' or 'region' key,
    that value is returned directly (used by scenario_analysis).
    Otherwise falls back to suffix-based lookup.
    """
    if info is not None:
        country_from_info = info.get("country") or info.get("region")
        if country_from_info:
            return country_from_info
    if is_cash(symbol):
        cur = cash_currency(symbol)
        # Reverse lookup: find country for this currency
        for suffix, c in SUFFIX_TO_CURRENCY.items():
            if c == cur:
                return SUFFIX_TO_COUNTRY.get(suffix, "Unknown")
        if cur == "USD":
            return "United States"
        if cur == "JPY":
            return "Japan"
        return "Unknown"
    for suffix, country in SUFFIX_TO_COUNTRY.items():
        if symbol.upper().endswith(suffix.upper()):
            return country
    # No suffix typically means US stock
    if "." not in symbol:
        return "United States"
    return "Unknown"
