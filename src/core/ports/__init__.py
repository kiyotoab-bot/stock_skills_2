"""Port interfaces for Dependency Inversion Principle compliance (KIK-513).

These typing.Protocol definitions decouple Core from Data layer.
Existing modules satisfy these protocols structurally — no modification needed.

Usage:
    from src.core.ports import GraphReader, GraphWriter, ResearchClient
    from src.core.ports import StockInfoProvider, HistoryStore
"""

from src.core.ports.graph import GraphReader, GraphWriter
from src.core.ports.research import ResearchClient
from src.core.ports.market_data import StockInfoProvider, ScreeningProvider, PriceHistoryProvider
from src.core.ports.storage import HistoryStore, NoteStore

__all__ = [
    "GraphReader",
    "GraphWriter",
    "ResearchClient",
    "StockInfoProvider",
    "ScreeningProvider",
    "PriceHistoryProvider",
    "HistoryStore",
    "NoteStore",
]
