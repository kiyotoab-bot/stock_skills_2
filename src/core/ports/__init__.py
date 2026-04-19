"""Port interfaces for SOLID compliance (KIK-513 DIP, KIK-516 ISP).

Protocol-based interfaces that decouple Core from Data layer.

Market data (yahoo_client) — ISP-split (KIK-516):
  StockInfoProvider     — get_stock_info, get_stock_detail, get_multiple_stocks
  ScreeningProvider     — screen_stocks
  PriceHistoryProvider  — get_price_history, get_stock_news
  MacroDataProvider     — get_macro_indicators
"""

from src.core.ports.market_data import (
    MacroDataProvider,
    PriceHistoryProvider,
    ScreeningProvider,
    StockInfoProvider,
)

__all__ = [
    # Yahoo-client protocols — ISP (KIK-516)
    "StockInfoProvider",
    "ScreeningProvider",
    "PriceHistoryProvider",
    "MacroDataProvider",
]
