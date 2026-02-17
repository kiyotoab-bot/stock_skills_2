"""Graph query helpers for enriching skill output (KIK-406).

All functions return empty/None when Neo4j is unavailable (graceful degradation).
"""

import json
from typing import Optional


def _get_driver():
    """Reuse graph_store's driver."""
    from src.data.graph_store import _get_driver as _gs_driver
    return _gs_driver()


# ---------------------------------------------------------------------------
# 1. Prior report lookup
# ---------------------------------------------------------------------------

def get_prior_report(symbol: str) -> Optional[dict]:
    """Get the most recent Report for a symbol.

    Returns dict with keys: date, score, verdict. None if not found.
    """
    driver = _get_driver()
    if driver is None:
        return None
    try:
        with driver.session() as session:
            result = session.run(
                "MATCH (r:Report)-[:ANALYZED]->(s:Stock {symbol: $symbol}) "
                "RETURN r.date AS date, r.score AS score, r.verdict AS verdict "
                "ORDER BY r.date DESC LIMIT 1",
                symbol=symbol,
            )
            record = result.single()
            if record is None:
                return None
            return dict(record)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 2. Screening frequency
# ---------------------------------------------------------------------------

def get_screening_frequency(symbols: list[str]) -> dict[str, int]:
    """Count how many times each symbol appeared in past Screen results.

    Returns {symbol: count} for symbols with count >= 1.
    """
    driver = _get_driver()
    if driver is None:
        return {}
    try:
        with driver.session() as session:
            result = session.run(
                "MATCH (sc:Screen)-[:SURFACED]->(s:Stock) "
                "WHERE s.symbol IN $symbols "
                "RETURN s.symbol AS symbol, count(sc) AS cnt",
                symbols=symbols,
            )
            return {r["symbol"]: r["cnt"] for r in result if r["cnt"] >= 1}
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# 3. Research chain (SUPERSEDES)
# ---------------------------------------------------------------------------

def get_research_chain(
    research_type: str, target: str, limit: int = 5,
) -> list[dict]:
    """Get the SUPERSEDES chain for a research type+target, newest first.

    Returns list of {date, summary}.
    """
    driver = _get_driver()
    if driver is None:
        return []
    try:
        with driver.session() as session:
            result = session.run(
                "MATCH (r:Research {research_type: $rtype, target: $target}) "
                "RETURN r.date AS date, r.summary AS summary "
                "ORDER BY r.date DESC LIMIT $limit",
                rtype=research_type, target=target, limit=limit,
            )
            return [dict(r) for r in result]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 4. Recent market context
# ---------------------------------------------------------------------------

def get_recent_market_context() -> Optional[dict]:
    """Get the most recent MarketContext node.

    Returns dict with keys: date, indices (parsed from JSON).
    None if not found.
    """
    driver = _get_driver()
    if driver is None:
        return None
    try:
        with driver.session() as session:
            result = session.run(
                "MATCH (m:MarketContext) "
                "RETURN m.date AS date, m.indices AS indices "
                "ORDER BY m.date DESC LIMIT 1",
            )
            record = result.single()
            if record is None:
                return None
            indices_raw = record["indices"]
            try:
                indices = json.loads(indices_raw) if indices_raw else []
            except (json.JSONDecodeError, TypeError):
                indices = []
            return {"date": record["date"], "indices": indices}
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 5. Trade context (trades + notes for a symbol)
# ---------------------------------------------------------------------------

def get_trade_context(symbol: str) -> dict:
    """Get trade history and notes for a symbol.

    Returns {trades: [{date, type, shares, price}], notes: [{date, type, content}]}.
    """
    empty = {"trades": [], "notes": []}
    driver = _get_driver()
    if driver is None:
        return empty
    try:
        with driver.session() as session:
            trades = session.run(
                "MATCH (t:Trade)-[:BOUGHT|SOLD]->(s:Stock {symbol: $symbol}) "
                "RETURN t.date AS date, t.type AS type, "
                "t.shares AS shares, t.price AS price "
                "ORDER BY t.date DESC",
                symbol=symbol,
            )
            notes = session.run(
                "MATCH (n:Note)-[:ABOUT]->(s:Stock {symbol: $symbol}) "
                "RETURN n.date AS date, n.type AS type, n.content AS content "
                "ORDER BY n.date DESC",
                symbol=symbol,
            )
            return {
                "trades": [dict(r) for r in trades],
                "notes": [dict(r) for r in notes],
            }
    except Exception:
        return empty


# ---------------------------------------------------------------------------
# 6. Recurring picks (frequently screened but not bought)
# ---------------------------------------------------------------------------

def get_recurring_picks(min_count: int = 2) -> list[dict]:
    """Find stocks that appear in multiple screens but have no BOUGHT trade.

    Returns list of {symbol, count, last_date}.
    """
    driver = _get_driver()
    if driver is None:
        return []
    try:
        with driver.session() as session:
            result = session.run(
                "MATCH (sc:Screen)-[:SURFACED]->(s:Stock) "
                "WHERE NOT exists { MATCH (:Trade)-[:BOUGHT]->(s) } "
                "WITH s.symbol AS symbol, count(sc) AS cnt, "
                "max(sc.date) AS last_date "
                "WHERE cnt >= $min_count "
                "RETURN symbol, cnt AS count, last_date "
                "ORDER BY cnt DESC, last_date DESC",
                min_count=min_count,
            )
            return [dict(r) for r in result]
    except Exception:
        return []
