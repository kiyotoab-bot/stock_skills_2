"""Save trade records to history (KIK-578 split from save.py)."""

import json
from datetime import date, datetime
from typing import Optional

from src.data.history._helpers import (
    _safe_filename,
    _history_dir,
    _sanitize,
    _dual_write_graph,
    _write_graph,
)


def save_trade(
    symbol: str,
    trade_type: str,
    shares: int,
    price: float,
    currency: str,
    date_str: str,
    memo: str = "",
    base_dir: str = "data/history",
    sell_price: Optional[float] = None,
    realized_pnl: Optional[float] = None,
    pnl_rate: Optional[float] = None,
    hold_days: Optional[int] = None,
    cost_price: Optional[float] = None,
    stock_info: Optional[dict] = None,
) -> str:
    """Save a trade record to JSON.

    Returns the absolute path of the saved file.

    Parameters
    ----------
    sell_price : float, optional
        売却単価（KIK-441）。sell 時のみ。
    realized_pnl : float, optional
        実現損益（KIK-441）。
    pnl_rate : float, optional
        損益率（KIK-441）。
    hold_days : int, optional
        保有日数（KIK-441）。
    cost_price : float, optional
        取得単価（KIK-441）。sell 時に保存。
    """
    today = date.today().isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    identifier = f"{trade_type}_{_safe_filename(symbol)}"
    filename = f"{today}_{identifier}.json"

    payload: dict = {
        "category": "trade",
        "date": date_str,
        "timestamp": now,
        "symbol": symbol,
        "trade_type": trade_type,
        "shares": shares,
        "price": price,
        "currency": currency,
        "memo": memo,
        "_saved_at": now,
    }

    # KIK-441: sell P&L フィールド
    if sell_price is not None:
        payload["sell_price"] = sell_price
    if realized_pnl is not None:
        payload["realized_pnl"] = realized_pnl
    if pnl_rate is not None:
        payload["pnl_rate"] = pnl_rate
    if hold_days is not None:
        payload["hold_days"] = hold_days
    if cost_price is not None:
        payload["cost_price"] = cost_price

    d = _history_dir("trade", base_dir)
    path = d / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_sanitize(payload), f, ensure_ascii=False, indent=2)

    # Neo4j dual-write (KIK-399/420/555) -- graceful degradation
    # Neo4j dual-write -- 変換は graph_writers ひとつ（KIK-741）
    _write_graph("trade", payload)

    return str(path.resolve())
