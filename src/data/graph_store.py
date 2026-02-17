"""Neo4j graph store for investment knowledge graph (KIK-397/398/413).

Provides schema initialization and CRUD operations for the knowledge graph.
All writes use MERGE for idempotent operations.
Graceful degradation: if Neo4j is unavailable, operations are silently skipped.

NEO4J_MODE environment variable controls write depth (KIK-413):
  - "off"     : No Neo4j writes (JSON only)
  - "summary" : Current behavior -- score/verdict/summary only (backward compat)
  - "full"    : Semantic sub-nodes (News, Sentiment, Catalyst, etc.) with relationships
  Default: "full" if Neo4j reachable, "off" otherwise.
"""

import os
import re
import time
from datetime import date, datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

_NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
_NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
_NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")

_driver = None


# ---------------------------------------------------------------------------
# Write mode (KIK-413)
# ---------------------------------------------------------------------------

_mode_cache: tuple[str, float] = ("", 0.0)
_MODE_TTL = 30.0


def _get_mode() -> str:
    """Return Neo4j write mode: 'off', 'summary', or 'full'.

    Env var ``NEO4J_MODE`` overrides auto-detection.
    Default: 'full' if Neo4j is reachable, 'off' otherwise.
    Result is cached for ``_MODE_TTL`` seconds to avoid repeated connectivity checks.
    """
    global _mode_cache
    env_mode = os.environ.get("NEO4J_MODE", "").lower()
    if env_mode in ("off", "summary", "full"):
        return env_mode
    now = time.time()
    if _mode_cache[0] and (now - _mode_cache[1]) < _MODE_TTL:
        return _mode_cache[0]
    mode = "full" if is_available() else "off"
    _mode_cache = (mode, now)
    return mode


def get_mode() -> str:
    """Public accessor for current Neo4j write mode."""
    return _get_mode()


def _get_driver():
    """Lazy-init Neo4j driver. Returns None if neo4j package not installed."""
    global _driver
    if _driver is not None:
        return _driver
    try:
        from neo4j import GraphDatabase
        _driver = GraphDatabase.driver(_NEO4J_URI, auth=(_NEO4J_USER, _NEO4J_PASSWORD))
        return _driver
    except Exception:
        return None


def is_available() -> bool:
    """Check if Neo4j is reachable."""
    driver = _get_driver()
    if driver is None:
        return False
    try:
        driver.verify_connectivity()
        return True
    except Exception:
        return False


def close():
    """Close the Neo4j driver."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


# ---------------------------------------------------------------------------
# Schema initialization
# ---------------------------------------------------------------------------

_SCHEMA_CONSTRAINTS = [
    "CREATE CONSTRAINT stock_symbol IF NOT EXISTS FOR (s:Stock) REQUIRE s.symbol IS UNIQUE",
    "CREATE CONSTRAINT screen_id IF NOT EXISTS FOR (s:Screen) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT report_id IF NOT EXISTS FOR (r:Report) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT trade_id IF NOT EXISTS FOR (t:Trade) REQUIRE t.id IS UNIQUE",
    "CREATE CONSTRAINT health_id IF NOT EXISTS FOR (h:HealthCheck) REQUIRE h.id IS UNIQUE",
    "CREATE CONSTRAINT note_id IF NOT EXISTS FOR (n:Note) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT theme_name IF NOT EXISTS FOR (t:Theme) REQUIRE t.name IS UNIQUE",
    "CREATE CONSTRAINT sector_name IF NOT EXISTS FOR (s:Sector) REQUIRE s.name IS UNIQUE",
    "CREATE CONSTRAINT research_id IF NOT EXISTS FOR (r:Research) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT watchlist_name IF NOT EXISTS FOR (w:Watchlist) REQUIRE w.name IS UNIQUE",
    "CREATE CONSTRAINT market_context_id IF NOT EXISTS FOR (m:MarketContext) REQUIRE m.id IS UNIQUE",
    # KIK-413 full-mode nodes
    "CREATE CONSTRAINT news_id IF NOT EXISTS FOR (n:News) REQUIRE n.id IS UNIQUE",
    "CREATE CONSTRAINT sentiment_id IF NOT EXISTS FOR (s:Sentiment) REQUIRE s.id IS UNIQUE",
    "CREATE CONSTRAINT catalyst_id IF NOT EXISTS FOR (c:Catalyst) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT analyst_view_id IF NOT EXISTS FOR (a:AnalystView) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT indicator_id IF NOT EXISTS FOR (i:Indicator) REQUIRE i.id IS UNIQUE",
    "CREATE CONSTRAINT upcoming_event_id IF NOT EXISTS FOR (e:UpcomingEvent) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT sector_rotation_id IF NOT EXISTS FOR (r:SectorRotation) REQUIRE r.id IS UNIQUE",
]

_SCHEMA_INDEXES = [
    "CREATE INDEX stock_sector IF NOT EXISTS FOR (s:Stock) ON (s.sector)",
    "CREATE INDEX screen_date IF NOT EXISTS FOR (s:Screen) ON (s.date)",
    "CREATE INDEX report_date IF NOT EXISTS FOR (r:Report) ON (r.date)",
    "CREATE INDEX trade_date IF NOT EXISTS FOR (t:Trade) ON (t.date)",
    "CREATE INDEX note_type IF NOT EXISTS FOR (n:Note) ON (n.type)",
    "CREATE INDEX research_date IF NOT EXISTS FOR (r:Research) ON (r.date)",
    "CREATE INDEX research_type IF NOT EXISTS FOR (r:Research) ON (r.research_type)",
    "CREATE INDEX market_context_date IF NOT EXISTS FOR (m:MarketContext) ON (m.date)",
    # KIK-413 full-mode indexes
    "CREATE INDEX news_date IF NOT EXISTS FOR (n:News) ON (n.date)",
    "CREATE INDEX sentiment_source IF NOT EXISTS FOR (s:Sentiment) ON (s.source)",
    "CREATE INDEX catalyst_type IF NOT EXISTS FOR (c:Catalyst) ON (c.type)",
    "CREATE INDEX indicator_date IF NOT EXISTS FOR (i:Indicator) ON (i.date)",
]


def init_schema() -> bool:
    """Create constraints and indexes. Returns True on success."""
    driver = _get_driver()
    if driver is None:
        return False
    try:
        with driver.session() as session:
            for stmt in _SCHEMA_CONSTRAINTS + _SCHEMA_INDEXES:
                session.run(stmt)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Stock node
# ---------------------------------------------------------------------------

def merge_stock(symbol: str, name: str = "", sector: str = "", country: str = "") -> bool:
    """Create or update a Stock node."""
    if _get_mode() == "off":
        return False
    driver = _get_driver()
    if driver is None:
        return False
    try:
        with driver.session() as session:
            session.run(
                "MERGE (s:Stock {symbol: $symbol}) "
                "SET s.name = $name, s.sector = $sector, s.country = $country",
                symbol=symbol, name=name, sector=sector, country=country,
            )
            if sector:
                session.run(
                    "MERGE (sec:Sector {name: $sector}) "
                    "WITH sec "
                    "MATCH (s:Stock {symbol: $symbol}) "
                    "MERGE (s)-[:IN_SECTOR]->(sec)",
                    sector=sector, symbol=symbol,
                )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Screen node
# ---------------------------------------------------------------------------

def merge_screen(
    screen_date: str, preset: str, region: str, count: int,
    symbols: list[str],
) -> bool:
    """Create a Screen node and SURFACED relationships to stocks."""
    if _get_mode() == "off":
        return False
    driver = _get_driver()
    if driver is None:
        return False
    screen_id = f"screen_{screen_date}_{region}_{preset}"
    try:
        with driver.session() as session:
            session.run(
                "MERGE (sc:Screen {id: $id}) "
                "SET sc.date = $date, sc.preset = $preset, "
                "sc.region = $region, sc.count = $count",
                id=screen_id, date=screen_date, preset=preset,
                region=region, count=count,
            )
            for sym in symbols:
                session.run(
                    "MATCH (sc:Screen {id: $screen_id}) "
                    "MERGE (s:Stock {symbol: $symbol}) "
                    "MERGE (sc)-[:SURFACED]->(s)",
                    screen_id=screen_id, symbol=sym,
                )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Report node
# ---------------------------------------------------------------------------

def merge_report(
    report_date: str, symbol: str, score: float, verdict: str,
) -> bool:
    """Create a Report node and ANALYZED relationship."""
    if _get_mode() == "off":
        return False
    driver = _get_driver()
    if driver is None:
        return False
    report_id = f"report_{report_date}_{symbol}"
    try:
        with driver.session() as session:
            session.run(
                "MERGE (r:Report {id: $id}) "
                "SET r.date = $date, r.symbol = $symbol, "
                "r.score = $score, r.verdict = $verdict",
                id=report_id, date=report_date, symbol=symbol,
                score=score, verdict=verdict,
            )
            session.run(
                "MATCH (r:Report {id: $report_id}) "
                "MERGE (s:Stock {symbol: $symbol}) "
                "MERGE (r)-[:ANALYZED]->(s)",
                report_id=report_id, symbol=symbol,
            )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Trade node
# ---------------------------------------------------------------------------

def merge_trade(
    trade_date: str, trade_type: str, symbol: str,
    shares: int, price: float, currency: str, memo: str = "",
) -> bool:
    """Create a Trade node and BOUGHT/SOLD relationship."""
    if _get_mode() == "off":
        return False
    driver = _get_driver()
    if driver is None:
        return False
    trade_id = f"trade_{trade_date}_{trade_type}_{symbol}"
    rel_type = "BOUGHT" if trade_type == "buy" else "SOLD"
    try:
        with driver.session() as session:
            session.run(
                "MERGE (t:Trade {id: $id}) "
                "SET t.date = $date, t.type = $type, t.symbol = $symbol, "
                "t.shares = $shares, t.price = $price, t.currency = $currency, "
                "t.memo = $memo",
                id=trade_id, date=trade_date, type=trade_type,
                symbol=symbol, shares=shares, price=price,
                currency=currency, memo=memo,
            )
            session.run(
                f"MATCH (t:Trade {{id: $trade_id}}) "
                f"MERGE (s:Stock {{symbol: $symbol}}) "
                f"MERGE (t)-[:{rel_type}]->(s)",
                trade_id=trade_id, symbol=symbol,
            )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# HealthCheck node
# ---------------------------------------------------------------------------

def merge_health(health_date: str, summary: dict, symbols: list[str]) -> bool:
    """Create a HealthCheck node and CHECKED relationships."""
    if _get_mode() == "off":
        return False
    driver = _get_driver()
    if driver is None:
        return False
    health_id = f"health_{health_date}"
    try:
        with driver.session() as session:
            session.run(
                "MERGE (h:HealthCheck {id: $id}) "
                "SET h.date = $date, h.total = $total, "
                "h.healthy = $healthy, h.exit_count = $exit_count",
                id=health_id, date=health_date,
                total=summary.get("total", 0),
                healthy=summary.get("healthy", 0),
                exit_count=summary.get("exit", 0),
            )
            for sym in symbols:
                session.run(
                    "MATCH (h:HealthCheck {id: $health_id}) "
                    "MERGE (s:Stock {symbol: $symbol}) "
                    "MERGE (h)-[:CHECKED]->(s)",
                    health_id=health_id, symbol=sym,
                )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Note node
# ---------------------------------------------------------------------------

def merge_note(
    note_id: str, note_date: str, note_type: str, content: str,
    symbol: Optional[str] = None, source: str = "",
) -> bool:
    """Create a Note node and ABOUT relationship to a stock."""
    if _get_mode() == "off":
        return False
    driver = _get_driver()
    if driver is None:
        return False
    try:
        with driver.session() as session:
            session.run(
                "MERGE (n:Note {id: $id}) "
                "SET n.date = $date, n.type = $type, "
                "n.content = $content, n.source = $source",
                id=note_id, date=note_date, type=note_type,
                content=content, source=source,
            )
            if symbol:
                session.run(
                    "MATCH (n:Note {id: $note_id}) "
                    "MERGE (s:Stock {symbol: $symbol}) "
                    "MERGE (n)-[:ABOUT]->(s)",
                    note_id=note_id, symbol=symbol,
                )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Theme tagging
# ---------------------------------------------------------------------------

def tag_theme(symbol: str, theme: str) -> bool:
    """Tag a stock with a theme."""
    if _get_mode() == "off":
        return False
    driver = _get_driver()
    if driver is None:
        return False
    try:
        with driver.session() as session:
            session.run(
                "MERGE (t:Theme {name: $theme}) "
                "WITH t "
                "MERGE (s:Stock {symbol: $symbol}) "
                "MERGE (s)-[:HAS_THEME]->(t)",
                theme=theme, symbol=symbol,
            )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Research node (KIK-398)
# ---------------------------------------------------------------------------

def _safe_id(text: str) -> str:
    """Make text safe for use in a node ID (replace non-alphanum with _)."""
    return re.sub(r"[^a-zA-Z0-9]", "_", text)


def merge_research(
    research_date: str, research_type: str, target: str,
    summary: str = "",
) -> bool:
    """Create a Research node and optionally RESEARCHED relationship to Stock.

    For stock/business types, target is treated as a symbol and linked to Stock.
    For industry/market types, no Stock link is created.
    """
    if _get_mode() == "off":
        return False
    driver = _get_driver()
    if driver is None:
        return False
    research_id = f"research_{research_date}_{research_type}_{_safe_id(target)}"
    try:
        with driver.session() as session:
            session.run(
                "MERGE (r:Research {id: $id}) "
                "SET r.date = $date, r.research_type = $rtype, "
                "r.target = $target, r.summary = $summary",
                id=research_id, date=research_date, rtype=research_type,
                target=target, summary=summary,
            )
            if research_type in ("stock", "business"):
                session.run(
                    "MATCH (r:Research {id: $research_id}) "
                    "MERGE (s:Stock {symbol: $symbol}) "
                    "MERGE (r)-[:RESEARCHED]->(s)",
                    research_id=research_id, symbol=target,
                )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Watchlist node (KIK-398)
# ---------------------------------------------------------------------------

def merge_watchlist(name: str, symbols: list[str]) -> bool:
    """Create a Watchlist node and BOOKMARKED relationships to stocks."""
    if _get_mode() == "off":
        return False
    driver = _get_driver()
    if driver is None:
        return False
    try:
        with driver.session() as session:
            session.run(
                "MERGE (w:Watchlist {name: $name})",
                name=name,
            )
            for sym in symbols:
                session.run(
                    "MATCH (w:Watchlist {name: $name}) "
                    "MERGE (s:Stock {symbol: $symbol}) "
                    "MERGE (w)-[:BOOKMARKED]->(s)",
                    name=name, symbol=sym,
                )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Research SUPERSEDES chain (KIK-398)
# ---------------------------------------------------------------------------

def link_research_supersedes(research_type: str, target: str) -> bool:
    """Link Research nodes of same type+target in date order with SUPERSEDES."""
    if _get_mode() == "off":
        return False
    driver = _get_driver()
    if driver is None:
        return False
    try:
        with driver.session() as session:
            session.run(
                "MATCH (r:Research {research_type: $rtype, target: $target}) "
                "WITH r ORDER BY r.date ASC "
                "WITH collect(r) AS nodes "
                "UNWIND range(0, size(nodes)-2) AS i "
                "WITH nodes[i] AS a, nodes[i+1] AS b "
                "MERGE (a)-[:SUPERSEDES]->(b)",
                rtype=research_type, target=target,
            )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# MarketContext node (KIK-399)
# ---------------------------------------------------------------------------

def merge_market_context(context_date: str, indices: list[dict]) -> bool:
    """Create/update a MarketContext node with index snapshots.

    indices is stored as a JSON string (Neo4j can't store list-of-maps).
    """
    if _get_mode() == "off":
        return False
    driver = _get_driver()
    if driver is None:
        return False
    import json as _json
    context_id = f"market_context_{context_date}"
    try:
        with driver.session() as session:
            session.run(
                "MERGE (m:MarketContext {id: $id}) "
                "SET m.date = $date, m.indices = $indices",
                id=context_id,
                date=context_date,
                indices=_json.dumps(indices, ensure_ascii=False),
            )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Clear all (KIK-398 --rebuild)
# ---------------------------------------------------------------------------

def clear_all() -> bool:
    """Delete all nodes and relationships. Used for --rebuild."""
    driver = _get_driver()
    if driver is None:
        return False
    try:
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int = 500) -> str:
    """Truncate text to max_len characters."""
    if not isinstance(text, str):
        return str(text)[:max_len] if text else ""
    return text[:max_len]


def merge_report_full(
    report_date: str, symbol: str, score: float, verdict: str,
    price: float = 0, per: float = 0, pbr: float = 0,
    dividend_yield: float = 0, roe: float = 0, market_cap: float = 0,
) -> bool:
    """Extend an existing Report node with full valuation properties (KIK-413).

    Calls merge_report() first, then SETs additional numeric fields.
    Only runs in 'full' mode.
    """
    if _get_mode() != "full":
        return merge_report(report_date, symbol, score, verdict)
    # Ensure base Report node exists
    merge_report(report_date, symbol, score, verdict)
    driver = _get_driver()
    if driver is None:
        return False
    report_id = f"report_{report_date}_{symbol}"
    try:
        with driver.session() as session:
            session.run(
                "MATCH (r:Report {id: $id}) "
                "SET r.price = $price, r.per = $per, r.pbr = $pbr, "
                "r.dividend_yield = $div, r.roe = $roe, r.market_cap = $mcap",
                id=report_id, price=float(price or 0),
                per=float(per or 0), pbr=float(pbr or 0),
                div=float(dividend_yield or 0), roe=float(roe or 0),
                mcap=float(market_cap or 0),
            )
        return True
    except Exception:
        return False


def merge_research_full(
    research_date: str, research_type: str, target: str,
    summary: str = "",
    grok_research: dict | None = None,
    x_sentiment: dict | None = None,
    news: list | None = None,
) -> bool:
    """Create Research node with semantic sub-nodes (KIK-413).

    Expands grok_research data into News, Sentiment, Catalyst, AnalystView
    nodes connected to the Research node via relationships.
    Only creates sub-nodes in 'full' mode.
    """
    if _get_mode() != "full":
        return merge_research(research_date, research_type, target, summary)
    # Ensure base Research + Stock nodes exist
    merge_research(research_date, research_type, target, summary)
    driver = _get_driver()
    if driver is None:
        return False
    research_id = f"research_{research_date}_{research_type}_{_safe_id(target)}"
    try:
        with driver.session() as session:
            # --- News nodes (from grok recent_news + yahoo news) ---
            news_items: list[dict | str] = []
            if grok_research and isinstance(grok_research.get("recent_news"), list):
                for item in grok_research["recent_news"][:5]:
                    if isinstance(item, str):
                        news_items.append({"title": item, "source": "grok"})
                    elif isinstance(item, dict):
                        news_items.append({**item, "source": "grok"})
            if isinstance(news, list):
                for item in news[:5]:
                    if isinstance(item, dict):
                        news_items.append({
                            "title": item.get("title", ""),
                            "source": item.get("publisher", "yahoo"),
                            "link": item.get("link", ""),
                        })
            for i, nitem in enumerate(news_items[:10]):
                nid = f"{research_id}_news_{i}"
                title = _truncate(nitem.get("title", ""), 500)
                source = nitem.get("source", "")[:50]
                link = nitem.get("link", "")[:500]
                session.run(
                    "MERGE (n:News {id: $id}) "
                    "SET n.date = $date, n.title = $title, "
                    "n.source = $source, n.link = $link "
                    "WITH n "
                    "MATCH (r:Research {id: $rid}) "
                    "MERGE (r)-[:HAS_NEWS]->(n)",
                    id=nid, date=research_date, title=title,
                    source=source, link=link, rid=research_id,
                )
                # MENTIONS→Stock for stock/business research
                if research_type in ("stock", "business"):
                    session.run(
                        "MATCH (n:News {id: $nid}) "
                        "MERGE (s:Stock {symbol: $symbol}) "
                        "MERGE (n)-[:MENTIONS]->(s)",
                        nid=nid, symbol=target,
                    )

            # --- Sentiment nodes ---
            # From grok x_sentiment
            if grok_research and isinstance(grok_research.get("x_sentiment"), dict):
                xs = grok_research["x_sentiment"]
                sid = f"{research_id}_sent_grok"
                session.run(
                    "MERGE (s:Sentiment {id: $id}) "
                    "SET s.date = $date, s.source = 'grok_x', "
                    "s.score = $score, s.summary = $summary "
                    "WITH s "
                    "MATCH (r:Research {id: $rid}) "
                    "MERGE (r)-[:HAS_SENTIMENT]->(s)",
                    id=sid, date=research_date,
                    score=float(xs.get("score", 0)),
                    summary=_truncate(xs.get("summary", ""), 500),
                    rid=research_id,
                )
            # From top-level x_sentiment (yahoo/yfinance)
            if isinstance(x_sentiment, dict) and x_sentiment:
                sid2 = f"{research_id}_sent_yahoo"
                pos = x_sentiment.get("positive", [])
                neg = x_sentiment.get("negative", [])
                pos_text = _truncate("; ".join(pos[:3]) if isinstance(pos, list) else str(pos), 500)
                neg_text = _truncate("; ".join(neg[:3]) if isinstance(neg, list) else str(neg), 500)
                session.run(
                    "MERGE (s:Sentiment {id: $id}) "
                    "SET s.date = $date, s.source = 'yahoo_x', "
                    "s.positive = $pos, s.negative = $neg "
                    "WITH s "
                    "MATCH (r:Research {id: $rid}) "
                    "MERGE (r)-[:HAS_SENTIMENT]->(s)",
                    id=sid2, date=research_date,
                    pos=pos_text, neg=neg_text, rid=research_id,
                )

            # --- Catalyst nodes ---
            if grok_research and isinstance(grok_research.get("catalysts"), dict):
                cats = grok_research["catalysts"]
                for polarity in ("positive", "negative"):
                    items = cats.get(polarity, [])
                    if isinstance(items, list):
                        for j, txt in enumerate(items[:5]):
                            cid = f"{research_id}_cat_{polarity[0]}_{j}"
                            session.run(
                                "MERGE (c:Catalyst {id: $id}) "
                                "SET c.date = $date, c.type = $polarity, "
                                "c.text = $text "
                                "WITH c "
                                "MATCH (r:Research {id: $rid}) "
                                "MERGE (r)-[:HAS_CATALYST]->(c)",
                                id=cid, date=research_date, polarity=polarity,
                                text=_truncate(str(txt), 500), rid=research_id,
                            )

            # --- AnalystView nodes ---
            if grok_research and isinstance(grok_research.get("analyst_views"), list):
                for k, view_text in enumerate(grok_research["analyst_views"][:5]):
                    avid = f"{research_id}_av_{k}"
                    session.run(
                        "MERGE (a:AnalystView {id: $id}) "
                        "SET a.date = $date, a.text = $text "
                        "WITH a "
                        "MATCH (r:Research {id: $rid}) "
                        "MERGE (r)-[:HAS_ANALYST_VIEW]->(a)",
                        id=avid, date=research_date,
                        text=_truncate(str(view_text), 500),
                        rid=research_id,
                    )
        return True
    except Exception:
        return False


def merge_market_context_full(
    context_date: str, indices: list[dict],
    grok_research: dict | None = None,
) -> bool:
    """Create MarketContext with semantic sub-nodes (KIK-413).

    Expands indices into Indicator nodes, and grok_research into
    UpcomingEvent, SectorRotation, and Sentiment nodes.
    Only creates sub-nodes in 'full' mode.
    """
    if _get_mode() != "full":
        return merge_market_context(context_date, indices)
    # Ensure base MarketContext node exists
    merge_market_context(context_date, indices)
    driver = _get_driver()
    if driver is None:
        return False
    context_id = f"market_context_{context_date}"
    try:
        with driver.session() as session:
            # --- Indicator nodes (from indices) ---
            for i, idx in enumerate(indices[:20]):
                iid = f"{context_id}_ind_{i}"
                session.run(
                    "MERGE (ind:Indicator {id: $id}) "
                    "SET ind.date = $date, ind.name = $name, "
                    "ind.symbol = $symbol, ind.price = $price, "
                    "ind.daily_change = $dchange, ind.weekly_change = $wchange "
                    "WITH ind "
                    "MATCH (m:MarketContext {id: $mid}) "
                    "MERGE (m)-[:INCLUDES]->(ind)",
                    id=iid, date=context_date,
                    name=str(idx.get("name", ""))[:100],
                    symbol=str(idx.get("symbol", ""))[:20],
                    price=float(idx.get("price", 0) or 0),
                    dchange=float(idx.get("daily_change", 0) or 0),
                    wchange=float(idx.get("weekly_change", 0) or 0),
                    mid=context_id,
                )

            if not grok_research:
                return True

            # --- UpcomingEvent nodes ---
            events = grok_research.get("upcoming_events", [])
            if isinstance(events, list):
                for j, ev in enumerate(events[:5]):
                    eid = f"{context_id}_event_{j}"
                    session.run(
                        "MERGE (e:UpcomingEvent {id: $id}) "
                        "SET e.date = $date, e.text = $text "
                        "WITH e "
                        "MATCH (m:MarketContext {id: $mid}) "
                        "MERGE (m)-[:HAS_EVENT]->(e)",
                        id=eid, date=context_date,
                        text=_truncate(str(ev), 500), mid=context_id,
                    )

            # --- SectorRotation nodes ---
            rotations = grok_research.get("sector_rotation", [])
            if isinstance(rotations, list):
                for k, rot in enumerate(rotations[:3]):
                    rid = f"{context_id}_rot_{k}"
                    session.run(
                        "MERGE (sr:SectorRotation {id: $id}) "
                        "SET sr.date = $date, sr.text = $text "
                        "WITH sr "
                        "MATCH (m:MarketContext {id: $mid}) "
                        "MERGE (m)-[:HAS_ROTATION]->(sr)",
                        id=rid, date=context_date,
                        text=_truncate(str(rot), 500), mid=context_id,
                    )

            # --- Sentiment node (market-level) ---
            sentiment = grok_research.get("sentiment")
            if isinstance(sentiment, dict):
                sid = f"{context_id}_sent"
                session.run(
                    "MERGE (s:Sentiment {id: $id}) "
                    "SET s.date = $date, s.source = 'market', "
                    "s.score = $score, s.summary = $summary "
                    "WITH s "
                    "MATCH (m:MarketContext {id: $mid}) "
                    "MERGE (m)-[:HAS_SENTIMENT]->(s)",
                    id=sid, date=context_date,
                    score=float(sentiment.get("score", 0)),
                    summary=_truncate(sentiment.get("summary", ""), 500),
                    mid=context_id,
                )

        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def get_stock_history(symbol: str) -> dict:
    """Get all graph relationships for a stock.

    Returns dict with keys: screens, reports, trades, health_checks,
    notes, themes, researches.
    """
    _empty = {"screens": [], "reports": [], "trades": [],
              "health_checks": [], "notes": [], "themes": [],
              "researches": []}
    driver = _get_driver()
    if driver is None:
        return dict(_empty)
    try:
        result = dict(_empty)
        with driver.session() as session:
            # Screens
            records = session.run(
                "MATCH (sc:Screen)-[:SURFACED]->(s:Stock {symbol: $symbol}) "
                "RETURN sc.date AS date, sc.preset AS preset, sc.region AS region "
                "ORDER BY sc.date DESC",
                symbol=symbol,
            )
            result["screens"] = [dict(r) for r in records]

            # Reports
            records = session.run(
                "MATCH (r:Report)-[:ANALYZED]->(s:Stock {symbol: $symbol}) "
                "RETURN r.date AS date, r.score AS score, r.verdict AS verdict "
                "ORDER BY r.date DESC",
                symbol=symbol,
            )
            result["reports"] = [dict(r) for r in records]

            # Trades
            records = session.run(
                "MATCH (t:Trade)-[:BOUGHT|SOLD]->(s:Stock {symbol: $symbol}) "
                "RETURN t.date AS date, t.type AS type, "
                "t.shares AS shares, t.price AS price "
                "ORDER BY t.date DESC",
                symbol=symbol,
            )
            result["trades"] = [dict(r) for r in records]

            # Health checks
            records = session.run(
                "MATCH (h:HealthCheck)-[:CHECKED]->(s:Stock {symbol: $symbol}) "
                "RETURN h.date AS date "
                "ORDER BY h.date DESC",
                symbol=symbol,
            )
            result["health_checks"] = [dict(r) for r in records]

            # Notes
            records = session.run(
                "MATCH (n:Note)-[:ABOUT]->(s:Stock {symbol: $symbol}) "
                "RETURN n.id AS id, n.date AS date, n.type AS type, "
                "n.content AS content "
                "ORDER BY n.date DESC",
                symbol=symbol,
            )
            result["notes"] = [dict(r) for r in records]

            # Themes
            records = session.run(
                "MATCH (s:Stock {symbol: $symbol})-[:HAS_THEME]->(t:Theme) "
                "RETURN t.name AS name",
                symbol=symbol,
            )
            result["themes"] = [r["name"] for r in records]

            # Researches (KIK-398)
            records = session.run(
                "MATCH (r:Research)-[:RESEARCHED]->(s:Stock {symbol: $symbol}) "
                "RETURN r.date AS date, r.research_type AS research_type, "
                "r.summary AS summary "
                "ORDER BY r.date DESC",
                symbol=symbol,
            )
            result["researches"] = [dict(r) for r in records]

        return result
    except Exception:
        return dict(_empty)
