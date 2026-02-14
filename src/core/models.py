"""Core data models for portfolio management (KIK-365 Phase 2).

Dataclasses providing type safety for the main domain objects.
External interfaces remain dict-based for backward compatibility;
these classes are used internally and provide to_dict() for conversion.
"""

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Position:
    """A single portfolio position."""

    symbol: str
    shares: int
    cost_price: float
    cost_currency: str
    current_price: float = 0.0
    value_jpy: float = 0.0
    sector: str = ""
    country: str = ""
    market_currency: str = ""
    name: str = ""
    purchase_date: str = ""
    memo: str = ""

    @property
    def is_cash(self) -> bool:
        from src.core.common import is_cash
        return is_cash(self.symbol)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Position":
        return cls(
            symbol=d.get("symbol", ""),
            shares=int(d.get("shares", 0)),
            cost_price=float(d.get("cost_price", 0.0)),
            cost_currency=d.get("cost_currency", "JPY"),
            current_price=float(d.get("current_price", 0.0)),
            value_jpy=float(d.get("value_jpy") or d.get("evaluation_jpy") or 0.0),
            sector=d.get("sector") or "",
            country=d.get("country") or "",
            market_currency=d.get("market_currency") or "",
            name=d.get("name") or "",
            purchase_date=d.get("purchase_date") or "",
            memo=d.get("memo") or "",
        )


@dataclass
class ForecastResult:
    """Return estimate for a single stock."""

    symbol: str
    method: str  # "analyst" | "historical" | "no_data" | "cash"
    base: Optional[float] = None
    optimistic: Optional[float] = None
    pessimistic: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ForecastResult":
        return cls(
            symbol=d.get("symbol", ""),
            method=d.get("method", "no_data"),
            base=d.get("base"),
            optimistic=d.get("optimistic"),
            pessimistic=d.get("pessimistic"),
        )


@dataclass
class HealthResult:
    """Health check result for a single holding."""

    symbol: str
    trend: str = ""  # "上昇" | "横ばい" | "下降"
    quality_label: str = ""
    alert_level: str = ""  # "" | "early_warning" | "caution" | "exit"
    reasons: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "HealthResult":
        alert = d.get("alert", {})
        return cls(
            symbol=d.get("symbol", ""),
            trend=d.get("trend_health", {}).get("trend", ""),
            quality_label=d.get("change_quality", {}).get("quality_label", ""),
            alert_level=alert.get("level", ""),
            reasons=alert.get("reasons", []),
        )


@dataclass
class RebalanceAction:
    """A single rebalancing action proposal."""

    action: str  # "sell" | "reduce" | "increase" | "buy"
    symbol: str
    name: str = ""
    ratio: float = 0.0
    amount_jpy: float = 0.0
    reason: str = ""
    priority: int = 99

    def to_dict(self) -> dict:
        return asdict(self)
