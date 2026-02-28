"""Market data port interfaces for yahoo_client abstraction (KIK-513).

These Protocols match the function signatures in src.data.yahoo_client.
Existing yahoo_client module satisfies them structurally.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class StockInfoProvider(Protocol):
    """Provider for fundamental stock data.

    Matches the public API of src.data.yahoo_client for info retrieval.
    """

    def get_stock_info(self, symbol: str) -> dict | None:
        """Return fundamental data dict for *symbol*, or None on failure."""
        ...

    def get_stock_news(self, symbol: str) -> list[dict]:
        """Return recent news articles for *symbol*."""
        ...


@runtime_checkable
class PriceHistoryProvider(Protocol):
    """Provider for price history data.

    Matches the public API of src.data.yahoo_client for history retrieval.
    """

    def get_price_history(
        self,
        symbol: str,
        period: str = "1y",
    ) -> pd.DataFrame:
        """Return OHLCV price history DataFrame for *symbol*."""
        ...


@runtime_checkable
class ScreeningProvider(Protocol):
    """Provider for bulk equity screening.

    Matches the public API of src.data.yahoo_client for screening.
    """

    def get_macro_indicators(self) -> list[dict]:
        """Return current macro indicator snapshots."""
        ...
