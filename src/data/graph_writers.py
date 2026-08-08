"""レコード dict → GraphRAG ノードの変換 (KIK-741).

**save 経路と sync 経路で同じものを使う。** 以前は同じ変換が3箇所にあり、
既に食い違っていた:

  - `history/save_*.py` の `_graph_write`（保存時の dual-write）
  - `graph_sync` の `_sync_*`（後追いの sync）
  - `graph_store.sync_stock_full`（銘柄単位の再同期）

`save_*()` が JSON に書く payload の形が、そのままここの入力になっている。
つまり **payload がインターフェース**であり、保存したものを後から読んで
同期しても、保存と同時に同期しても、同じ関数を通る。

判断はしない。書けたら True、必須フィールドが欠けていれば False を返す。
"""

from datetime import datetime
from typing import Any, Callable, Optional

def _first(rec: dict, *keys: str, default: Any = None) -> Any:
    """最初に見つかった有効値を返す（キー名の揺れを吸収）.

    空文字は「無い」とみなして次のキーに進む。手書き JSON では欠落を `""` で
    表すことがあり、None 判定だけだと `{"action": "", "trade_type": "sell"}` で
    有効な `sell` を捨ててレコードごと落とす。
    """
    for k in keys:
        v = rec.get(k)
        if v is not None and v != "":
            return v
    return default


def _num(value: Any, default: float = 0.0) -> float:
    """数値化に失敗したら default を返す（欠けても構わない項目用）."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _required_num(value: Any) -> Optional[float]:
    """数値化できなければ None。**欠けたら書いてはいけない項目用**.

    `_num` は失敗を 0.0 に潰すので、株数や単価に使うと「0株・0円の取引」が
    グラフに書かれて成功として数えられる。必須項目はこちらを使う。
    bool は数値に化けるので明示的に弾く（`float(True) == 1.0`）。
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _embedding(category: str, **kwargs) -> tuple[str, Optional[list]]:
    """semantic_summary と埋め込みベクトルを作る (KIK-740).

    ⚠️ sync 経路はこれを一切呼んでいなかった。``save_*()`` 経由の書き込みだけが
    埋め込みを付けるため、**Neo4j 停止中に保存 → 復旧後に sync で補完**した
    ノードだけが `embedding` を持たず、ベクトル検索から永久に漏れていた。
    ノードは作られ件数も合うので、出力からは検知できない。

    実体は `history/_helpers._build_embedding`（save 経路と同じもの）。
    TEI 未起動なら ("", None) が返り、埋め込みなしで書かれる。
    """
    try:
        from src.data.history._helpers import _build_embedding
        return _build_embedding(category, **kwargs)
    except Exception:
        return ("", None)


def _iso_date(value: Any) -> Optional[str]:
    """先頭10文字を YYYY-MM-DD として検証して返す。駄目なら None.

    素の `str(v)[:10]` は `"Aug 4, 2026"` を `"Aug 4, 202"` に切って truthy の
    まま通してしまい、壊れた id と日付が静かにグラフへ蓄積する。
    """
    if value is None:
        return None
    head = str(value)[:10]
    try:
        datetime.strptime(head, "%Y-%m-%d")
    except ValueError:
        return None
    return head


# --- per-category writers --------------------------------------------------


def _sync_trade(rec: dict) -> bool:
    from src.data.graph_store import merge_trade

    symbol = rec.get("symbol")
    # 実データでは direction が action / trade_type どちらかに入る（action が全件、
    # trade_type は 8/20 件のみ）。action を先に見る。
    trade_type = _first(rec, "action", "trade_type")
    trade_date = _iso_date(_first(rec, "date", "trade_date"))
    # 株数・単価は必須。欠けたまま書くと 0株/0円の取引ノードが「成功」として
    # 数えられ、誰も気づかない。手書き JSON が混ざる領域なので必ず弾く。
    shares = _required_num(rec.get("shares"))
    price = _required_num(rec.get("price"))
    if not (symbol and trade_type and trade_date) or shares is None or price is None:
        return False
    sem, emb = _embedding("trade", date=trade_date, trade_type=str(trade_type).lower(),
                          symbol=symbol, shares=int(shares), memo=rec.get("memo", ""))
    return merge_trade(
        semantic_summary=sem, embedding=emb,
        trade_date=trade_date,
        trade_type=str(trade_type).lower(),
        symbol=symbol,
        shares=int(shares),
        price=price,
        currency=rec.get("currency", "JPY"),
        memo=rec.get("memo", "") or "",
        sell_price=rec.get("sell_price"),
        # 実現損益のキーは realized_pnl / realized_pl / pnl の3通りが存在する
        realized_pnl=_first(rec, "realized_pnl", "realized_pl", "pnl"),
        hold_days=rec.get("hold_days"),
    )


def _sync_screen(rec: dict) -> bool:
    from src.data.graph_store import merge_screen, merge_stock, tag_theme

    screen_date = _iso_date(rec.get("date"))
    if not screen_date:
        return False
    results = [r for r in (rec.get("results") or []) if isinstance(r, dict) and r.get("symbol")]
    symbols = [r["symbol"] for r in results]
    theme = rec.get("theme")
    for r in results:
        merge_stock(symbol=r["symbol"], name=r.get("name", "") or "",
                    sector=r.get("sector", "") or "")
        # save_screen.py の dual-write と同じことをする。ここで tag_theme を
        # 落とすと sync 経由の Screen だけ Theme に繋がらず、get_theme_trends()
        # の集計から静かに抜ける。
        if theme:
            tag_theme(r["symbol"], theme)
    sem, emb = _embedding("screen", date=screen_date, preset=rec.get("preset", ""),
                          region=rec.get("region", ""), top_symbols=symbols[:5])
    return merge_screen(
        semantic_summary=sem, embedding=emb,
        screen_date=screen_date,
        preset=rec.get("preset", "") or "",
        region=rec.get("region", "") or "",
        count=int(_num(_first(rec, "count", default=len(symbols)))),
        symbols=symbols,
    )


def _sync_report(rec: dict) -> bool:
    from src.data.graph_store import merge_report_full, merge_stock

    symbol = rec.get("symbol")
    report_date = _iso_date(rec.get("date"))
    if not (symbol and report_date):
        return False
    merge_stock(symbol=symbol, name=rec.get("name", "") or "",
                sector=rec.get("sector", "") or "")
    sem, emb = _embedding("report", symbol=symbol, name=rec.get("name", ""),
                          score=_num(_first(rec, "value_score", "score")),
                          verdict=rec.get("verdict", ""), sector=rec.get("sector", ""))
    return merge_report_full(
        semantic_summary=sem, embedding=emb,
        report_date=report_date,
        symbol=symbol,
        score=_num(_first(rec, "value_score", "score")),
        verdict=rec.get("verdict", "") or "",
        price=_num(rec.get("price")),
        per=_num(rec.get("per")),
        pbr=_num(rec.get("pbr")),
        dividend_yield=_num(rec.get("dividend_yield")),
        roe=_num(rec.get("roe")),
        market_cap=_num(rec.get("market_cap")),
    )


def _sync_research(rec: dict) -> bool:
    from src.data.graph_store import (
        link_research_supersedes, merge_research_full, merge_stock,
    )

    research_date = _iso_date(rec.get("date"))
    target = rec.get("target")
    if not (research_date and target):
        return False
    research_type = _first(rec, "research_type", "type", default="") or ""
    # save_research.py と同じ。銘柄・事業のリサーチは Stock ノードも作る
    if research_type in ("stock", "business"):
        fundamentals = rec.get("fundamentals") or {}
        merge_stock(symbol=target, name=rec.get("name", "") or "",
                    sector=fundamentals.get("sector", "") or "")
    sem, emb = _embedding("research", research_type=research_type,
                          target=target, result=rec)
    # summary が payload に無ければ本文から組み立てる（save_research と同じ）。
    # 落とすと Research ノードの summary が空になり、後から読めなくなる。
    summary = rec.get("summary", "") or ""
    if not summary:
        try:
            from src.data.history.save_research import _build_research_summary
            summary = _build_research_summary(research_type, rec)
        except Exception:
            summary = ""
    ok = merge_research_full(
        semantic_summary=sem, embedding=emb,
        research_date=research_date,
        research_type=research_type,
        target=target,
        summary=summary,
        grok_research=rec.get("grok_research"),
        x_sentiment=rec.get("x_sentiment"),
        news=rec.get("news"),
    )
    if ok:
        # save_research.py と同じ。張らないと get_research_chain() が
        # 古い research を最新扱いする。
        link_research_supersedes(research_type, target)
    return ok


def _sync_health(rec: dict) -> bool:
    from src.data.graph_store import merge_health

    health_date = _iso_date(rec.get("date"))
    if not health_date:
        return False
    positions = rec.get("positions") or []
    symbols = [p.get("symbol") for p in positions if isinstance(p, dict) and p.get("symbol")]
    sem, emb = _embedding("health", date=health_date, summary=rec.get("summary") or {})
    return merge_health(
        semantic_summary=sem, embedding=emb,
        health_date=health_date,
        summary=rec.get("summary") or {},
        symbols=symbols,
    )


def _sync_market_context(rec: dict) -> bool:
    from src.data.graph_store import merge_market_context_full

    context_date = _iso_date(rec.get("date"))
    if not context_date:
        return False
    sem, emb = _embedding("market_context", date=context_date,
                          indices=rec.get("indices") or [],
                          grok_research=rec.get("grok_research"))
    return merge_market_context_full(
        semantic_summary=sem, embedding=emb,
        context_date=context_date,
        indices=rec.get("indices") or [],
        grok_research=rec.get("grok_research"),
    )


def _sync_stress_test(rec: dict) -> bool:
    from src.data.graph_store import merge_stock, merge_stress_test

    test_date = _iso_date(rec.get("date"))
    scenario = rec.get("scenario")
    if not (test_date and scenario):
        return False
    symbols = [s for s in (rec.get("symbols") or []) if s]
    for sym in symbols:
        merge_stock(symbol=sym)
    var = rec.get("var_result") or {}
    sem, emb = _embedding("stress_test", date=test_date, scenario=scenario,
                          portfolio_impact=_num(rec.get("portfolio_impact")),
                          symbol_count=len(symbols))
    return merge_stress_test(
        semantic_summary=sem, embedding=emb,
        test_date=test_date,
        scenario=scenario,
        portfolio_impact=_num(rec.get("portfolio_impact")),
        symbols=symbols,
        var_95=_num(var.get("var_95_daily")),
        var_99=_num(var.get("var_99_daily")),
    )


def _sync_forecast(rec: dict) -> bool:
    from src.data.graph_store import merge_forecast, merge_stock

    forecast_date = _iso_date(rec.get("date"))
    if not forecast_date:
        return False
    positions = rec.get("positions") or []
    symbols = [p.get("symbol") for p in positions
               if isinstance(p, dict) and p.get("symbol")]
    for sym in symbols:
        merge_stock(symbol=sym)
    pf = rec.get("portfolio") or {}
    sem, emb = _embedding("forecast", date=forecast_date,
                          optimistic=_num(pf.get("optimistic")),
                          base=_num(pf.get("base")),
                          pessimistic=_num(pf.get("pessimistic")),
                          symbol_count=len(symbols))
    return merge_forecast(
        semantic_summary=sem, embedding=emb,
        forecast_date=forecast_date,
        optimistic=_num(pf.get("optimistic")),
        base=_num(pf.get("base")),
        pessimistic=_num(pf.get("pessimistic")),
        symbols=symbols,
        total_value_jpy=_num(rec.get("total_value_jpy")),
    )


# `save_*()` が data/history/ 配下に作る **全カテゴリ** をここに並べる。
# 対応は tests/data/test_graph_sync.py が save_*.py の実装から機械的に検証する。
# KIK-735 では最初の5つしか入れておらず、market_context / stress_test / forecast が
# 同じ穴（Neo4j 停止中に保存 → sync しても永久に埋まらない）を残していた。
_WRITERS: dict[str, Callable[[dict], bool]] = {
    "trade": _sync_trade,
    "screen": _sync_screen,
    "report": _sync_report,
    "research": _sync_research,
    "health": _sync_health,
    "market_context": _sync_market_context,
    "stress_test": _sync_stress_test,
    "forecast": _sync_forecast,
}

HISTORY_CATEGORIES = tuple(_WRITERS)

