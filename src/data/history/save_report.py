"""Save report results to history (KIK-578 split from save.py)."""

import json
from datetime import date, datetime

from src.data.history._helpers import (
    _safe_filename,
    _history_dir,
    _sanitize,
    _unique_suffix,
    _write_graph,
)


def save_report(
    symbol: str,
    data: dict,
    score: float,
    verdict: str,
    base_dir: str = "data/history",
) -> str:
    """Save a stock report to JSON.

    Returns the absolute path of the saved file.
    """
    today = date.today().isoformat()
    now_dt = datetime.now()
    now = now_dt.isoformat(timespec="seconds")
    # KIK-744: HHMMSSffffff + uuid hex で完全一意化
    ts_suffix = _unique_suffix(now_dt)
    identifier = _safe_filename(symbol)
    filename = f"{today}_{identifier}_{ts_suffix}.json"

    payload = {
        "category": "report",
        "date": today,
        "timestamp": now,
        "symbol": symbol,
        "name": data.get("name"),
        "sector": data.get("sector"),
        "industry": data.get("industry"),
        "price": data.get("price"),
        "per": data.get("per"),
        "pbr": data.get("pbr"),
        "dividend_yield": data.get("dividend_yield"),
        "roe": data.get("roe"),
        "roa": data.get("roa"),
        "revenue_growth": data.get("revenue_growth"),
        "market_cap": data.get("market_cap"),
        "value_score": score,
        "verdict": verdict,
        "_saved_at": now,
    }

    d = _history_dir("report", base_dir)
    path = d / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_sanitize(payload), f, ensure_ascii=False, indent=2)

    # Neo4j dual-write -- 変換は graph_writers ひとつ（KIK-741）
    _write_graph("report", payload)

    # KIK-434: AI graph linking (graceful degradation)
    try:
        from src.data.graph_store.linker import link_report
        _rid = f"report_{today}_{symbol}"
        link_report(_rid, symbol, data.get("sector", ""), score, verdict)
    except Exception:
        pass

    return str(path.resolve())
