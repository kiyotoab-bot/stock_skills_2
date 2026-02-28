"""Research port interface for Grok API abstraction (KIK-513).

ResearchClient matches the public API of src.data.grok_client.
Existing grok_client module satisfies this protocol structurally.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ResearchClient(Protocol):
    """Client for qualitative stock/market/industry research via external APIs.

    Matches the public API of src.data.grok_client.
    """

    def is_available(self) -> bool:
        """Return True if the client is configured and ready to use."""
        ...

    def get_error_status(self) -> dict:
        """Return the current API error status dict."""
        ...

    def search_stock_deep(
        self,
        symbol: str,
        company_name: str,
        *,
        context: str = "",
    ) -> dict | None:
        """Run deep research for a single stock.

        Returns a dict with recent_news, catalysts, analyst_views, etc.,
        or None on failure.
        """
        ...

    def search_x_sentiment(
        self,
        symbol: str,
        company_name: str,
        *,
        context: str = "",
    ) -> dict | None:
        """Fetch X (Twitter) sentiment for *symbol*.

        Returns a dict with positive, negative, sentiment_score, or None.
        """
        ...

    def search_industry(
        self,
        theme: str,
        *,
        context: str = "",
    ) -> dict | None:
        """Run industry/theme research.

        Returns a dict with trends, key_players, growth_drivers, etc., or None.
        """
        ...

    def search_market(
        self,
        market: str,
        *,
        context: str = "",
    ) -> dict | None:
        """Run market overview research.

        Returns a dict with price_action, macro_factors, sentiment, etc., or None.
        """
        ...

    def search_business(
        self,
        symbol: str,
        company_name: str,
        *,
        context: str = "",
    ) -> dict | None:
        """Run business model research for *symbol*.

        Returns a dict with overview, segments, revenue_model, etc., or None.
        """
        ...
