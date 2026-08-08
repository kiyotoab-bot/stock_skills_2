"""Portfolio, Trade, HealthCheck, Forecast, StressTest node operations (KIK-507).

Handles merge_trade, merge_health, sync_portfolio, is_held, get_held_symbols,
merge_stress_test, merge_forecast, sync_stock_full (KIK-555).
"""

import re

from src.data.graph_store import _common


# ---------------------------------------------------------------------------
# Trade node
# ---------------------------------------------------------------------------

def merge_trade(
    trade_date: str, trade_type: str, symbol: str,
    shares: int, price: float, currency: str, memo: str = "",
    semantic_summary: str = "", embedding: list[float] | None = None,
    sell_price: float | None = None,
    realized_pnl: float | None = None,
    hold_days: int | None = None,
) -> bool:
    """Create a Trade node and BOUGHT/SOLD relationship."""
    if _common._get_mode() == "off":
        return False
    driver = _common._get_driver()
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
                "t.memo = $memo, "
                "t.sell_price = $sell_price, t.realized_pnl = $realized_pnl, "
                "t.hold_days = $hold_days",
                id=trade_id, date=trade_date, type=trade_type,
                symbol=symbol, shares=shares, price=price,
                currency=currency, memo=memo,
                sell_price=sell_price, realized_pnl=realized_pnl,
                hold_days=hold_days,
            )
            session.run(
                f"MATCH (t:Trade {{id: $trade_id}}) "
                f"MERGE (s:Stock {{symbol: $symbol}}) "
                f"MERGE (t)-[:{rel_type}]->(s)",
                trade_id=trade_id, symbol=symbol,
            )
            _common._set_embedding(session, "Trade", trade_id, semantic_summary, embedding)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# HealthCheck node
# ---------------------------------------------------------------------------

def merge_health(health_date: str, summary: dict, symbols: list[str],
                  semantic_summary: str = "", embedding: list[float] | None = None,
                  ) -> bool:
    """Create a HealthCheck node and CHECKED relationships."""
    if _common._get_mode() == "off":
        return False
    driver = _common._get_driver()
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
            _common._set_embedding(session, "HealthCheck", health_id, semantic_summary, embedding)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Portfolio sync (KIK-414)
# ---------------------------------------------------------------------------

def sync_portfolio(holdings: list[dict]) -> bool:
    """Sync portfolio CSV holdings to Neo4j HOLDS relationships.

    Creates a Portfolio anchor node and HOLDS relationships to each Stock.
    Removes HOLDS for stocks no longer in the portfolio.
    Cash positions (*.CASH) are excluded.
    """
    if _common._get_mode() == "off":
        return False
    driver = _common._get_driver()
    if driver is None:
        return False
    try:
        from src.data.common import is_cash

        with driver.session() as session:
            session.run("MERGE (p:Portfolio {name: 'default'})")

            current_symbols = []
            for h in holdings:
                symbol = h.get("symbol", "")
                if not symbol or is_cash(symbol):
                    continue
                current_symbols.append(symbol)
                session.run(
                    "MERGE (s:Stock {symbol: $symbol})",
                    symbol=symbol,
                )
                session.run(
                    "MATCH (p:Portfolio {name: 'default'}) "
                    "MATCH (s:Stock {symbol: $symbol}) "
                    "MERGE (p)-[r:HOLDS]->(s) "
                    "SET r.shares = $shares, r.cost_price = $cost_price, "
                    "r.cost_currency = $cost_currency, "
                    "r.purchase_date = $purchase_date",
                    symbol=symbol,
                    shares=int(h.get("shares", 0)),
                    cost_price=float(h.get("cost_price", 0)),
                    cost_currency=h.get("cost_currency", "JPY"),
                    purchase_date=h.get("purchase_date", ""),
                )

            if current_symbols:
                session.run(
                    "MATCH (p:Portfolio {name: 'default'})-[r:HOLDS]->(s:Stock) "
                    "WHERE NOT s.symbol IN $symbols "
                    "DELETE r",
                    symbols=current_symbols,
                )
            else:
                session.run(
                    "MATCH (p:Portfolio {name: 'default'})-[r:HOLDS]->() "
                    "DELETE r",
                )
        return True
    except Exception:
        return False


def is_held(symbol: str) -> bool:
    """Check if a symbol is currently held in the portfolio."""
    driver = _common._get_driver()
    if driver is None:
        return False
    try:
        with driver.session() as session:
            result = session.run(
                "MATCH (p:Portfolio {name: 'default'})-[:HOLDS]->(s:Stock {symbol: $symbol}) "
                "RETURN count(*) AS cnt",
                symbol=symbol,
            )
            record = result.single()
            return record["cnt"] > 0 if record else False
    except Exception:
        return False


def get_held_symbols() -> list[str]:
    """Return symbols currently held in portfolio via HOLDS relationship."""
    driver = _common._get_driver()
    if driver is None:
        return []
    try:
        with driver.session() as session:
            result = session.run(
                "MATCH (p:Portfolio {name: 'default'})-[:HOLDS]->(s:Stock) "
                "RETURN s.symbol AS symbol"
            )
            return [r["symbol"] for r in result]
    except Exception:
        return []


# 通貨ではないと分かっているキー（メタデータ・派生値）。balance_jpy は JPY の重複。
# 判定そのものはホワイトリストで行うので、これは「未知のキー」を報告するときに
# 既知のメタデータを除くためだけに使う。
_CASH_META_KEYS = frozenset({"updated_at", "last_updated", "memo", "balance_jpy"})


def _known_currencies() -> frozenset[str]:
    """このシステムが扱いうる通貨コード.

    ticker_utils の地域→通貨マッピングを唯一の出典にする。USD は米国株が
    サフィックス無しで表されるためマッピングに現れないので明示的に足す。
    """
    from src.data.ticker_utils import SUFFIX_TO_CURRENCY
    return frozenset(SUFFIX_TO_CURRENCY.values()) | {"USD"}


def extract_cash_currencies(balances: dict) -> dict[str, float]:
    """``cash_balance.json`` から通貨コードと残高だけを取り出す.

    ファイルにはメタデータ（``updated_at`` / ``memo``）と派生値（``balance_jpy``）が
    同じ階層に混ざっている。

    ⚠️ 「3文字の大文字」という形だけの判定にしてはいけない。``NAV`` / ``FEE`` /
    ``PNL`` / ``TAX`` のような派生値を将来同じ階層に足すと、そのまま
    ``cash_pnl`` として Portfolio ノードに書かれ現金として二重計上される。
    既知の通貨コードのホワイトリストで判定する。

    bool は ``float(True) == 1.0`` になるため明示的に弾く。
    """
    known = _known_currencies()
    out: dict[str, float] = {}
    for key, value in balances.items():
        if key not in known or isinstance(value, bool):
            continue
        try:
            out[key] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def unrecognized_cash_keys(balances: dict) -> list[str]:
    """通貨として扱えなかったキーのうち、既知のメタデータでないものを返す.

    ``tools/cash_balance.py`` の ``update_currency()`` は通貨コードを検証せずに
    書き込むため、``update_currency("usdt", 500)`` はファイルに残るがグラフには
    現れない。黙って消えると気づけないので、呼び出し側が報告できるようにする。
    """
    known = _known_currencies()
    return sorted(k for k in balances if k not in known and k not in _CASH_META_KEYS)


def merge_cash_balance(balance_date: str, balances: dict) -> bool:
    """現金残高を Portfolio ノードのプロパティとして書く (KIK-736).

    現金は銘柄ではないので HOLDS を張れない（``sync_portfolio`` も ``*.CASH`` を
    除外している）。Portfolio アンカーの属性として持たせ、``cash_jpy`` のように
    通貨ごとのプロパティにする。履歴は呼び出し側が Note で残す。

    Parameters
    ----------
    balance_date : str
        残高の基準日（``updated_at`` の日付部分）。
    balances : dict
        ``cash_balance.json`` の中身そのまま。通貨キーだけ拾う。

    Returns
    -------
    bool
        書けたら True。通貨キーが1つも無ければ False。
    """
    if _common._get_mode() == "off":
        return False
    driver = _common._get_driver()
    if driver is None:
        return False

    currencies = extract_cash_currencies(balances)
    if not currencies:
        return False

    props = {f"cash_{code.lower()}": amount for code, amount in currencies.items()}
    props["cash_updated_at"] = balance_date

    try:
        with driver.session() as session:
            session.run("MERGE (p:Portfolio {name: 'default'})")

            # SET p += は追記なので、それだけだと消えた通貨のプロパティが残る。
            # USD を使い切って cash_balance.json から "USD" を消しても cash_usd が
            # 居座り、現金を過大計上する（sync_portfolio が消えた銘柄の HOLDS を
            # DELETE しているのと揃える）。REMOVE はプロパティ名を変数に取れないので、
            # 既存キーを読んでから名前を埋め込む。APOC には依存しない。
            existing = session.run(
                "MATCH (p:Portfolio {name: 'default'}) "
                "RETURN [k IN keys(p) WHERE k STARTS WITH 'cash_'] AS ks"
            ).single()
            stale = [k for k in (existing["ks"] if existing else [])
                     if k not in props and re.fullmatch(r"cash_[a-z_]+", k)]
            if stale:
                session.run(
                    "MATCH (p:Portfolio {name: 'default'}) REMOVE "
                    + ", ".join(f"p.`{k}`" for k in stale)
                )

            # プロパティ名が通貨で変わるので SET p += $props で流し込む
            session.run(
                "MATCH (p:Portfolio {name: 'default'}) SET p += $props",
                props=props,
            )
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# StressTest node (KIK-428)
# ---------------------------------------------------------------------------

def merge_stress_test(
    test_date: str, scenario: str, portfolio_impact: float,
    symbols: list[str], var_95: float = 0, var_99: float = 0,
    semantic_summary: str = "", embedding: list[float] | None = None,
) -> bool:
    """Create a StressTest node and STRESSED relationships to stocks."""
    if _common._get_mode() == "off":
        return False
    driver = _common._get_driver()
    if driver is None:
        return False
    test_id = f"stress_test_{test_date}_{_common._safe_id(scenario)}"
    try:
        with driver.session() as session:
            session.run(
                "MERGE (st:StressTest {id: $id}) "
                "SET st.date = $date, st.scenario = $scenario, "
                "st.portfolio_impact = $impact, "
                "st.var_95 = $var95, st.var_99 = $var99, "
                "st.symbol_count = $cnt",
                id=test_id, date=test_date, scenario=scenario,
                impact=float(portfolio_impact),
                var95=float(var_95), var99=float(var_99),
                cnt=len(symbols),
            )
            for sym in symbols:
                session.run(
                    "MATCH (st:StressTest {id: $test_id}) "
                    "MERGE (s:Stock {symbol: $symbol}) "
                    "MERGE (st)-[:STRESSED]->(s)",
                    test_id=test_id, symbol=sym,
                )
            _common._set_embedding(session, "StressTest", test_id, semantic_summary, embedding)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Forecast node (KIK-428)
# ---------------------------------------------------------------------------

def merge_forecast(
    forecast_date: str, optimistic: float, base: float, pessimistic: float,
    symbols: list[str], total_value_jpy: float = 0,
    semantic_summary: str = "", embedding: list[float] | None = None,
) -> bool:
    """Create a Forecast node and FORECASTED relationships to stocks."""
    if _common._get_mode() == "off":
        return False
    driver = _common._get_driver()
    if driver is None:
        return False
    forecast_id = f"forecast_{forecast_date}"
    try:
        with driver.session() as session:
            session.run(
                "MERGE (f:Forecast {id: $id}) "
                "SET f.date = $date, f.optimistic = $opt, "
                "f.base = $base, f.pessimistic = $pess, "
                "f.total_value_jpy = $total, f.symbol_count = $cnt",
                id=forecast_id, date=forecast_date,
                opt=float(optimistic), base=float(base),
                pess=float(pessimistic),
                total=float(total_value_jpy), cnt=len(symbols),
            )
            for sym in symbols:
                session.run(
                    "MATCH (f:Forecast {id: $forecast_id}) "
                    "MERGE (s:Stock {symbol: $symbol}) "
                    "MERGE (f)-[:FORECASTED]->(s)",
                    forecast_id=forecast_id, symbol=sym,
                )
            _common._set_embedding(session, "Forecast", forecast_id, semantic_summary, embedding)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Full stock sync (KIK-555)
# ---------------------------------------------------------------------------

def sync_stock_full(symbol: str, client=None, csv_path: str = "") -> dict:
    """Single entry point for complete Stock + Trade Neo4j sync (KIK-555).

    Ensures all of the following are present:
    1. Stock metadata (name, sector, country) from yfinance
    2. Trade nodes with embeddings from history JSON
    3. IN_SECTOR relationship (auto from merge_stock when sector set)
    4. Community assignment (incremental)

    Parameters
    ----------
    symbol : str
        Ticker symbol.
    client : module, optional
        yahoo_client module. If None, imports automatically.
    csv_path : str, optional
        Path to portfolio CSV. Used to find trade history.

    Returns
    -------
    dict with keys: stock (bool), trades (int), community (bool)
    """
    result = {"stock": False, "trades": 0, "community": False}

    if _common._get_mode() == "off":
        return result

    # 1. Stock metadata from yfinance
    try:
        if client is None:
            from src.data import yahoo_client as client  # noqa: N811
        info = client.get_stock_info(symbol)
        if info:
            from src.data.graph_store.stock import merge_stock
            result["stock"] = merge_stock(
                symbol=symbol,
                name=info.get("name", ""),
                sector=info.get("sector", ""),
                country=info.get("country", ""),
            )
    except Exception:
        pass

    # 2. Trade records from history JSON
    try:
        import glob
        import json
        from pathlib import Path

        history_dir = Path("data/history/trade")
        if not history_dir.exists():
            history_dir = Path(__file__).resolve().parents[3] / "data" / "history" / "trade"

        if history_dir.exists():
            # KIK-740: 取引レコード → Trade ノードの変換は graph_sync._sync_trade
            # ひとつに寄せた。以前はここに写しがあり、キー名の揺れ吸収も
            # 必須フィールドのガードも graph_sync 側と食い違っていた
            # （list 形式で全件落ちる KIK-737 のバグはここだけに残っていた）。
            from src.data.common import load_json_records
            from src.data.graph_sync import _sync_trade

            for fp in sorted(history_dir.glob("*.json")):
                try:
                    records = load_json_records(fp)
                except Exception:
                    continue
                for rec in records:
                    if rec.get("symbol") != symbol:
                        continue
                    try:
                        if _sync_trade(rec):
                            result["trades"] += 1
                    except Exception:
                        continue
    except Exception:
        pass

    # 3. Community assignment
    try:
        from src.data.graph_query.community import update_stock_community
        comm = update_stock_community(symbol)
        result["community"] = comm is not None
    except Exception:
        pass

    return result
