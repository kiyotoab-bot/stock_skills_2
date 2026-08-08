"""Shared utilities for graph_store submodules (KIK-507).

Contains connection management, mode detection, error handling decorator,
and shared helper functions used across all graph_store submodules.
"""

import functools
import os
import re
import sys
import time
from datetime import datetime
from typing import Optional


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

_NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7688")
_NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
_NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")

_driver = None
# Once-only guard for NEO4J_DEBUG=1 diagnostics (also kept as a stable
# attribute for tests that monkeypatch ``src.data.graph_store._unavailable_warned``).
_unavailable_warned = False


def _debug_enabled() -> bool:
    """Return True if NEO4J_DEBUG is set to a truthy value (1/true/yes)."""
    return os.environ.get("NEO4J_DEBUG", "").strip().lower() in ("1", "true", "yes")


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


def reset_mode_cache() -> None:
    """Reset the mode cache (KIK-743).

    Useful in tests where ``is_available`` is monkey-patched between cases —
    without resetting, the 30s TTL leaks the previous test's mode value into
    the next test.
    """
    global _mode_cache
    _mode_cache = ("", 0.0)


_driver_failure: str | None = None


def _get_driver():
    """Lazy-init Neo4j driver. Returns None if neo4j package not installed."""
    global _driver, _driver_failure
    if _driver is not None:
        return _driver
    try:
        from neo4j import GraphDatabase
    except ImportError:
        # 依存パッケージ未導入。Docker の起動状態とは無関係なので区別して記録する。
        _driver_failure = "missing_package"
        return None
    try:
        _driver = GraphDatabase.driver(_NEO4J_URI, auth=(_NEO4J_USER, _NEO4J_PASSWORD))
        _driver_failure = None
        return _driver
    except Exception:
        _driver_failure = "connect"
        return None


def _unavailable_message() -> str:
    """Diagnose *why* Neo4j is unavailable instead of always blaming Docker.

    ``neo4j`` は長らく requirements.txt に未記載で、未導入環境では ImportError の
    まま「Dockerコンテナが起動していない」と表示されていた。原因の取り違えを招くため
    パッケージ未導入と接続失敗を分けて案内する。
    """
    if _driver_failure == "missing_package":
        return (
            "⚠️  Neo4jに接続できません\n"
            "    原因: neo4j パッケージが未インストールです（Dockerの状態とは無関係）\n"
            "    対処: pip install -r requirements.txt を実行してください\n"
            "    → Neo4jなしで続行します（コンテキストなし）"
        )
    return (
        "⚠️  Neo4jに接続できません\n"
        f"    原因: {_NEO4J_URI} に到達できません。Dockerコンテナが未起動の可能性があります\n"
        "    対処: docker compose up -d を実行してください\n"
        "    → Neo4jなしで続行します（コンテキストなし）"
    )


def is_available() -> bool:
    """Check if Neo4j is reachable.

    Neo4j is optional in this project (dual-write view side; the master is
    ``data/`` JSON/CSV). Failures are silent by default. Set
    ``NEO4J_DEBUG=1`` (or ``true``/``yes``) to emit a one-line diagnostic on
    stderr the first time per process — repeated failures stay quiet to avoid
    log spam, since this function is called repeatedly via ``_get_mode()``.
    """
    global _unavailable_warned
    global _driver_failure
    driver = _get_driver()
    if driver is None:
        # 既定では沈黙（KIK-749）。NEO4J_DEBUG=1 のときだけ、原因を切り分けた
        # 案内（KIK-733 の _unavailable_message）を出す。
        if _debug_enabled() and not _unavailable_warned:
            print(_unavailable_message(), file=sys.stderr)
            _unavailable_warned = True
        return False
    try:
        driver.verify_connectivity()
        _unavailable_warned = False  # reset once connectivity recovers
        _driver_failure = None
        return True
    except Exception as exc:
        _driver_failure = "connect"
        if _debug_enabled() and not _unavailable_warned:
            # 例外は型名のみ。repr は URI・認証情報を含みうる。
            print(
                f"{_unavailable_message()}\n    詳細: {type(exc).__name__}",
                file=sys.stderr,
            )
            _unavailable_warned = True
        return False


def close():
    """Close the Neo4j driver."""
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_id(text: str) -> str:
    """Make text safe for use in a node ID (replace non-alphanum with _)."""
    return re.sub(r"[^a-zA-Z0-9]", "_", text)


def _truncate(text: str, max_len: int = 500) -> str:
    """Truncate text to max_len characters."""
    if not isinstance(text, str):
        return str(text)[:max_len] if text else ""
    return text[:max_len]


# ---------------------------------------------------------------------------
# Embedding helper (KIK-420)
# ---------------------------------------------------------------------------

def _set_embedding(session, label: str, node_id: str,
                   semantic_summary: str = "",
                   embedding: list[float] | None = None) -> None:
    """Set semantic_summary and embedding on a node if provided."""
    if not semantic_summary and embedding is None:
        return
    sets = []
    params: dict = {"id": node_id}
    if semantic_summary:
        sets.append("n.semantic_summary = $summary")
        params["summary"] = semantic_summary
    if embedding is not None:
        sets.append("n.embedding = $embedding")
        params["embedding"] = embedding
    if sets:
        query = f"MATCH (n:{label} {{id: $id}}) SET {', '.join(sets)}"
        session.run(query, **params)


# ---------------------------------------------------------------------------
# Schema
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
    # KIK-414 portfolio sync
    "CREATE CONSTRAINT portfolio_name IF NOT EXISTS FOR (p:Portfolio) REQUIRE p.name IS UNIQUE",
    # KIK-428 stress test / forecast auto-save
    "CREATE CONSTRAINT stress_test_id IF NOT EXISTS FOR (st:StressTest) REQUIRE st.id IS UNIQUE",
    "CREATE CONSTRAINT forecast_id IF NOT EXISTS FOR (f:Forecast) REQUIRE f.id IS UNIQUE",
    # KIK-472 action item
    "CREATE CONSTRAINT action_item_id IF NOT EXISTS FOR (a:ActionItem) REQUIRE a.id IS UNIQUE",
    # KIK-547 community detection
    "CREATE CONSTRAINT community_id IF NOT EXISTS FOR (c:Community) REQUIRE c.id IS UNIQUE",
    # KIK-571 lesson community
    "CREATE CONSTRAINT lesson_community_name IF NOT EXISTS FOR (lc:LessonCommunity) REQUIRE lc.name IS UNIQUE",
    # KIK-603 theme trend
    "CREATE CONSTRAINT theme_trend_id IF NOT EXISTS FOR (tt:ThemeTrend) REQUIRE tt.id IS UNIQUE",
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
    # KIK-428 stress test / forecast indexes
    "CREATE INDEX stress_test_date IF NOT EXISTS FOR (st:StressTest) ON (st.date)",
    "CREATE INDEX forecast_date IF NOT EXISTS FOR (f:Forecast) ON (f.date)",
    # KIK-413 full-mode indexes
    "CREATE INDEX news_date IF NOT EXISTS FOR (n:News) ON (n.date)",
    "CREATE INDEX sentiment_source IF NOT EXISTS FOR (s:Sentiment) ON (s.source)",
    "CREATE INDEX catalyst_type IF NOT EXISTS FOR (c:Catalyst) ON (c.type)",
    "CREATE INDEX indicator_date IF NOT EXISTS FOR (i:Indicator) ON (i.date)",
    # KIK-472 action item indexes
    "CREATE INDEX action_item_status IF NOT EXISTS FOR (a:ActionItem) ON (a.status)",
    "CREATE INDEX action_item_date IF NOT EXISTS FOR (a:ActionItem) ON (a.date)",
    # KIK-547 community detection indexes
    "CREATE INDEX community_level IF NOT EXISTS FOR (c:Community) ON (c.level)",
    "CREATE INDEX community_created IF NOT EXISTS FOR (c:Community) ON (c.created_at)",
    # KIK-603 theme trend indexes
    "CREATE INDEX theme_trend_date IF NOT EXISTS FOR (tt:ThemeTrend) ON (tt.date)",
    "CREATE INDEX theme_trend_theme IF NOT EXISTS FOR (tt:ThemeTrend) ON (tt.theme)",
]

# KIK-420: Vector indexes for semantic search
_VECTOR_INDEXES = [
    "CREATE VECTOR INDEX screen_embedding IF NOT EXISTS FOR (s:Screen) ON (s.embedding) "
    "OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}",
    "CREATE VECTOR INDEX report_embedding IF NOT EXISTS FOR (r:Report) ON (r.embedding) "
    "OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}",
    "CREATE VECTOR INDEX trade_embedding IF NOT EXISTS FOR (t:Trade) ON (t.embedding) "
    "OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}",
    "CREATE VECTOR INDEX healthcheck_embedding IF NOT EXISTS FOR (h:HealthCheck) ON (h.embedding) "
    "OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}",
    "CREATE VECTOR INDEX research_embedding IF NOT EXISTS FOR (r:Research) ON (r.embedding) "
    "OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}",
    "CREATE VECTOR INDEX marketcontext_embedding IF NOT EXISTS FOR (m:MarketContext) ON (m.embedding) "
    "OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}",
    "CREATE VECTOR INDEX note_embedding IF NOT EXISTS FOR (n:Note) ON (n.embedding) "
    "OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}",
    "CREATE VECTOR INDEX watchlist_embedding IF NOT EXISTS FOR (w:Watchlist) ON (w.embedding) "
    "OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}",
    # KIK-428 stress test / forecast vector indexes
    "CREATE VECTOR INDEX stresstest_embedding IF NOT EXISTS FOR (st:StressTest) ON (st.embedding) "
    "OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}",
    "CREATE VECTOR INDEX forecast_embedding IF NOT EXISTS FOR (f:Forecast) ON (f.embedding) "
    "OPTIONS {indexConfig: {`vector.dimensions`: 384, `vector.similarity_function`: 'cosine'}}",
]


_DDL_NAME = re.compile(r"CREATE\s+(?:VECTOR\s+)?(?:CONSTRAINT|INDEX)\s+(\w+)")


def _expected_schema() -> dict[str, list[str]]:
    """DDL 定義から、あるべき制約・索引の名前を取り出す (KIK-742)."""
    def names(stmts):
        return [m.group(1) for m in (_DDL_NAME.search(s) for s in stmts) if m]
    return {
        "constraints": names(_SCHEMA_CONSTRAINTS),
        "indexes": names(_SCHEMA_INDEXES),
        "vector_indexes": names(_VECTOR_INDEXES),
    }


def check_schema() -> dict:
    """制約・索引・ベクトル索引が実在するかを確認する (KIK-742).

    ⚠️ **`init_schema()` が True を返しても、作られた保証はない。**
    ベクトル索引の失敗は `try/except: pass` で握り潰される設計（古い Neo4j
    互換のため）なので、1つも作られなくても True が返る。実際 2026-08-09 に
    調べたところ、このDBには索引も制約も **1つも存在しなかった**
    （Neo4j 既定の LOOKUP 2件のみ）。

    埋め込みを全ノードに付けても、ベクトル索引が無ければ
    `db.index.vector.queryNodes` は呼べず意味検索は一切動かない。
    「埋め込みの欠落」より上流の問題なので、日次の Step 0 で見る。

    Returns
    -------
    dict
        ``ok`` / ``missing`` / ``present`` / ``vector_online`` / ``alerts``
    """
    expected = _expected_schema()
    driver = _get_driver()
    if driver is None:
        return {"ok": None, "skipped": "Neo4j未接続", "missing": {}, "alerts": []}
    try:
        with driver.session() as session:
            idx = session.run(
                "SHOW INDEXES YIELD name, type, state RETURN name, type, state").data()
            con = session.run("SHOW CONSTRAINTS YIELD name RETURN name").data()
    except Exception as e:
        return {"ok": None, "skipped": f"スキーマを読めない: {e}",
                "missing": {}, "alerts": []}

    have_idx = {r["name"] for r in idx}
    have_con = {r["name"] for r in con}
    vec_state = {r["name"]: r.get("state") for r in idx if r.get("type") == "VECTOR"}

    missing = {
        "constraints": [n for n in expected["constraints"] if n not in have_con],
        "indexes": [n for n in expected["indexes"] if n not in have_idx],
        "vector_indexes": [n for n in expected["vector_indexes"] if n not in have_idx],
    }
    # 作られていても ONLINE でなければ引けない
    not_online = [n for n in expected["vector_indexes"]
                  if n in vec_state and vec_state[n] != "ONLINE"]

    alerts = []
    if missing["vector_indexes"]:
        alerts.append({
            "symbol": "SCHEMA", "type": "vector_index_missing", "severity": "CRITICAL",
            "message": (f"ベクトル索引が {len(missing['vector_indexes'])}件 未作成 "
                        "→ 意味検索が動きません（init_schema() を実行）"),
            "value": missing["vector_indexes"]})
    if not_online:
        alerts.append({
            "symbol": "SCHEMA", "type": "vector_index_not_online", "severity": "WARN",
            "message": f"ベクトル索引が構築中/失敗: {not_online}",
            "value": not_online})
    if missing["constraints"]:
        alerts.append({
            "symbol": "SCHEMA", "type": "constraint_missing", "severity": "WARN",
            "message": (f"一意制約が {len(missing['constraints'])}件 未作成 "
                        "→ ノードの重複を防げません"),
            "value": missing["constraints"]})
    if missing["indexes"]:
        alerts.append({
            "symbol": "SCHEMA", "type": "index_missing", "severity": "INFO",
            "message": f"索引が {len(missing['indexes'])}件 未作成（クエリが遅くなります）",
            "value": missing["indexes"]})

    return {
        "ok": not any(missing.values()) and not not_online,
        "missing": missing,
        "present": {k: len(set(expected[k]) & (have_con if k == "constraints" else have_idx))
                    for k in expected},
        "expected": {k: len(v) for k, v in expected.items()},
        "vector_online": sum(1 for v in vec_state.values() if v == "ONLINE"),
        "alerts": alerts,
    }


def init_schema() -> bool:
    """Create constraints and indexes. Returns True on success.

    ⚠️ 戻り値の True は「文を流した」以上の意味を持たない。ベクトル索引の
    失敗は握り潰される。**作られたかは `check_schema()` で確認すること。**
    """
    driver = _get_driver()
    if driver is None:
        return False
    try:
        with driver.session() as session:
            for stmt in _SCHEMA_CONSTRAINTS + _SCHEMA_INDEXES:
                session.run(stmt)
            # KIK-420: Vector indexes (separate try/except -- older Neo4j may not support)
            for stmt in _VECTOR_INDEXES:
                try:
                    session.run(stmt)
                except Exception:
                    pass  # Skip if vector indexes not supported
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# AI relationship cyphers (KIK-434)
# ---------------------------------------------------------------------------

_AI_REL_CYPHERS = {
    "INFLUENCES": (
        "MATCH (a {id: $fid}) MATCH (b {id: $tid}) "
        "MERGE (a)-[r:INFLUENCES]->(b) "
        "SET r.confidence = $conf, r.reason = $reason, "
        "r.created_by = 'ai', r.created_at = $ts"
    ),
    "CONTRADICTS": (
        "MATCH (a {id: $fid}) MATCH (b {id: $tid}) "
        "MERGE (a)-[r:CONTRADICTS]->(b) "
        "SET r.confidence = $conf, r.reason = $reason, "
        "r.created_by = 'ai', r.created_at = $ts"
    ),
    "CONTEXT_OF": (
        "MATCH (a {id: $fid}) MATCH (b {id: $tid}) "
        "MERGE (a)-[r:CONTEXT_OF]->(b) "
        "SET r.confidence = $conf, r.reason = $reason, "
        "r.created_by = 'ai', r.created_at = $ts"
    ),
    "INFORMS": (
        "MATCH (a {id: $fid}) MATCH (b {id: $tid}) "
        "MERGE (a)-[r:INFORMS]->(b) "
        "SET r.confidence = $conf, r.reason = $reason, "
        "r.created_by = 'ai', r.created_at = $ts"
    ),
    "SUPPORTS": (
        "MATCH (a {id: $fid}) MATCH (b {id: $tid}) "
        "MERGE (a)-[r:SUPPORTS]->(b) "
        "SET r.confidence = $conf, r.reason = $reason, "
        "r.created_by = 'ai', r.created_at = $ts"
    ),
}


def create_ai_relationship(
    from_id: str,
    to_id: str,
    rel_type: str,
    confidence: float,
    reason: str,
) -> bool:
    """MERGE an AI-determined semantic relationship between two nodes (KIK-434)."""
    if _get_mode() == "off":
        return False
    cypher = _AI_REL_CYPHERS.get(rel_type)
    if not cypher:
        return False
    driver = _get_driver()
    if driver is None:
        return False
    try:
        ts = datetime.now().isoformat(timespec="seconds")
        with driver.session() as session:
            session.run(
                cypher,
                fid=from_id, tid=to_id,
                conf=float(confidence),
                reason=str(reason)[:500],
                ts=ts,
            )
        return True
    except Exception:
        return False


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
