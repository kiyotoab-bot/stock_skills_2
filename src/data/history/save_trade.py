"""Save trade records to history (KIK-578 split from save.py)."""

import json
from datetime import date, datetime
from typing import Optional

from src.data.history._helpers import (
    _safe_filename,
    _history_dir,
    _sanitize,
    _dual_write_graph,
    _unique_suffix,
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
    sleeve: str = "core",
    limit_exempt: bool = False,
    exempt_reason: str = "",
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
    sleeve : str
        枠（KIK-751）。``core``（中長期・既定）か ``tactical``（短期売買）。
        ``tactical`` は中長期の冷却期間・月次上限・集中度判定から外れる。
        既定を core にしてあるので、指定を忘れた取引が短期枠に紛れることはない。
    limit_exempt : bool
        月次上限のカウントから外す（KIK-763）。**ストップ抵触による売却**など、
        裁量で起こしたのではない取引に付ける。2026-08-17 ユーザー判断。

        ⚠️ 外れるのは**月次上限だけ**。実現損益・総資産・配分・集中度には
        通常どおり計上される。ここが ``excluded_dates`` との違いで、
        あちらは枠と実現損益の**両方**から外す（``excluded_pnl`` に回る）。
        ストップ執行の損益は実在するので ``excluded_dates`` を流用してはならない。

        既定 False。付け忘れた取引は通常どおり枠を消費するので、
        「黙って枠が増えている」方向には壊れない。
    exempt_reason : str
        ``limit_exempt=True`` にした理由。後から検証できるように必ず書く
        （例: "stop-loss 4609 triggered"）。
    """
    today = date.today().isoformat()
    now_dt = datetime.now()
    now = now_dt.isoformat(timespec="seconds")
    # KIK-744: HHMMSSffffff + uuid hex で完全一意化（同秒2回呼びでも衝突しない）
    ts_suffix = _unique_suffix(now_dt)
    identifier = f"{trade_type}_{_safe_filename(symbol)}"
    filename = f"{today}_{identifier}_{ts_suffix}.json"

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
        "sleeve": sleeve,
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

    # KIK-763: 月次上限の免除。True のときだけ書く（既存レコードと同じ形を保つ）
    if limit_exempt:
        payload["limit_exempt"] = True
        payload["exempt_reason"] = exempt_reason

    d = _history_dir("trade", base_dir)
    path = d / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_sanitize(payload), f, ensure_ascii=False, indent=2)

    # Neo4j dual-write (KIK-399/420/555) -- graceful degradation
    # Neo4j dual-write -- 変換は graph_writers ひとつ（KIK-741）
    _write_graph("trade", payload)

    return str(path.resolve())
