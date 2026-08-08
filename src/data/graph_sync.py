"""data/ → GraphRAG 一括同期 (KIK-735).

`save_*()` は保存時に Neo4j へ dual-write するが、**保存時に Neo4j が落ちていると
ローカルにファイルだけが残る**。sync はその取りこぼしを後から埋めるための仕組みで、
SKILL.md の「sync して」に対応する。

KIK-712 の `sync_all()` は portfolio と notes しか回しておらず、SKILL.md が
同期対象として挙げている trade / screen / report / research / health が
**一度も同期されない**状態だった（2026-08-08 発見）。本モジュールがその全カテゴリを扱う。

同期方向は常に ローカル → GraphRAG の一方向。graph_store の全関数が MERGE を
使うため、同じ id は上書きされ二重登録されない。
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from src.data.common import load_json_records

# HISTORY_CATEGORIES は _WRITERS から導出する（このファイル下部で定義）。
# 2つを別々に並べていたため、片方だけ増やす余地が残っていた。


# --- helpers ---------------------------------------------------------------


def _load_records(path: Path) -> list[dict]:
    """1ファイルからレコード列を取り出す（実体は common.load_json_records）.

    同じ読み取りが `graph_store.sync_stock_full` にもあり、そちらは list 形式に
    未対応で全件を黙って捨てていた。共通化して差分を無くしてある。
    """
    return load_json_records(path)


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
    from src.data.graph_store import link_research_supersedes, merge_research_full

    research_date = _iso_date(rec.get("date"))
    target = rec.get("target")
    if not (research_date and target):
        return False
    research_type = _first(rec, "research_type", "type", default="") or ""
    sem, emb = _embedding("research", research_type=research_type,
                          target=target, result=rec)
    ok = merge_research_full(
        semantic_summary=sem, embedding=emb,
        research_date=research_date,
        research_type=research_type,
        target=target,
        summary=rec.get("summary", "") or "",
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


# --- section syncs ---------------------------------------------------------


def _sync_portfolio(root: Path, result: dict) -> None:
    try:
        from src.data.portfolio_io import load_portfolio
        from src.data.graph_store.portfolio import sync_portfolio
        # 旧実装は DEFAULT_CSV_PATH 固定で project_root を無視していた。
        # notes/history だけ root を見て portfolio だけ見ない状態だと、
        # ワークツリーから叩いたときに portfolio が黙って 0件になる。
        csv_path = root / "data" / "portfolio.csv"
        if not csv_path.exists():
            result["skipped"].append(f"portfolio: {csv_path} が無い")
            return
        holdings = load_portfolio(str(csv_path))
        if holdings:
            sync_portfolio(holdings)
            result["synced"].append(f"portfolio({len(holdings)}銘柄)")
        else:
            result["skipped"].append("portfolio: 保有0件")
    except Exception as e:
        result["failed"].append(f"portfolio: {e}")


def _sync_notes(root: Path, result: dict) -> None:
    try:
        from src.data.graph_store.note import merge_note
        notes_dir = root / "data" / "notes"
        if not notes_dir.exists():
            return
        count = total = 0
        for nf in sorted(notes_dir.glob("*.json")):
            try:
                # 旧実装は data[0] しか見ておらず、1ファイルに複数ノートを持つ
                # 19ファイルから 36件が毎回落ちていた（123件同期 / 実体159件）。
                records = _load_records(nf)
            except Exception as e:
                result["failed"].append(f"note: {nf.name}: {e}")
                continue
            for i, note in enumerate(records):
                total += 1
                # try をレコード単位に落とす。ファイル単位だと1件の失敗で
                # 同じファイルの後続レコードが道連れになる。
                try:
                    # merge_note は失敗しても例外を投げず False を返す。
                    # 戻り値を見ないと「159件同期」と出しながら0件という
                    # 状態が作れてしまう（_sync_history とも不整合になる）。
                    sem, emb = _embedding(
                        "note", symbol=note.get("symbol", "") or "",
                        note_type=note.get("type", "observation"),
                        content=note.get("content", ""))
                    if merge_note(
                        semantic_summary=sem, embedding=emb,
                        note_id=note.get("id", nf.stem),
                        note_date=note.get("date", ""),
                        note_type=note.get("type", "observation"),
                        content=note.get("content", ""),
                        symbol=note.get("symbol"),
                        source=note.get("source", "claude"),
                        category=note.get("category", ""),
                    ):
                        count += 1
                    else:
                        result["failed"].append(f"note: {nf.name}#{i} 書き込み失敗")
                except Exception as e:
                    result["failed"].append(f"note: {nf.name}#{i}: {e}")
        if count:
            result["synced"].append(f"notes({count}件)")
        elif total:
            result["skipped"].append(f"notes: {total}件中0件同期")
    except Exception as e:
        result["failed"].append(f"notes: {e}")


def _sync_cash(root: Path, result: dict) -> None:
    """data/cash_balance.json → Portfolio ノードの cash_* プロパティ + Note 履歴.

    KIK-736 まで SKILL.md の同期表に載っているだけで呼び出し口が無かった。
    現金は銘柄ではないので HOLDS を張れず（``sync_portfolio`` も ``*.CASH`` を
    除外する）、Portfolio アンカーの属性として持たせる。残高の推移を後から
    辿れるよう、基準日ごとに Note(type=cash) も残す。

    ⚠️ 日中の履歴は原理的に取れない。``cash_balance.json`` はスナップショットで
    履歴を持たないため、同じ日に残高が何度動いても sync が見られるのは最後の
    値だけになる（2026-08-04 は7件の売却で残高が7回動いたが Note は1件）。
    冪等性のための設計ではなく、入力側の制約である。
    """
    cash_path = root / "data" / "cash_balance.json"
    if not cash_path.exists():
        return
    try:
        from src.data.graph_store import (
            extract_cash_currencies, merge_cash_balance, unrecognized_cash_keys,
        )
        from src.data.graph_store.note import merge_note

        records = _load_records(cash_path)
        if not records:
            result["skipped"].append("cash: 中身が空")
            return
        balances = records[0]

        # updated_at を優先する。tools/cash_balance.py の save_cash_balance() が
        # 更新するのは updated_at だけで、last_updated は手で書かれた値が残り
        # 続ける。逆順にすると残高更新のたびに古い日付の Note が新しい残高で
        # 上書きされ、過去の履歴が壊れる。
        balance_date = _iso_date(_first(balances, "updated_at", "last_updated"))
        if not balance_date:
            result["skipped"].append("cash: 基準日が読めない（YYYY-MM-DD 形式でない）")
            return

        currencies = extract_cash_currencies(balances)
        if not currencies:
            result["skipped"].append("cash: 通貨キーが無い")
            return
        ignored = unrecognized_cash_keys(balances)
        if ignored:
            # 黙って捨てると update_currency("usdt", ...) がグラフに出ないまま終わる
            result["skipped"].append(f"cash: 通貨として認識できないキー {ignored}")

        if not merge_cash_balance(balance_date, balances):
            result["failed"].append("cash: Portfolio への書き込み失敗")
            return

        # id を基準日で切るので、同じ日の再 sync では上書きされ増えない
        amounts = " / ".join(
            f"{code} {amount:,.0f}" for code, amount in sorted(currencies.items())
        )
        memo = balances.get("memo", "") or ""
        content = f"現金残高 {amounts}" + (f" — {memo}" if memo else "")
        sem, emb = _embedding("note", symbol="", note_type="cash", content=content)
        if not merge_note(
            semantic_summary=sem, embedding=emb,
            note_id=f"cash_{balance_date}",
            note_date=balance_date,
            note_type="cash",
            content=content,
            category="portfolio",
            source="cash_balance.json",
        ):
            result["failed"].append("cash: 履歴 Note の書き込み失敗")
            return
        result["synced"].append(f"cash({len(currencies)}通貨)")
    except Exception as e:
        result["failed"].append(f"cash: {e}")


def _sync_history(root: Path, result: dict) -> None:
    """data/history/{category}/*.json を全カテゴリ同期する."""
    for category in HISTORY_CATEGORIES:
        cat_dir = root / "data" / "history" / category
        if not cat_dir.exists():
            continue
        files = sorted(cat_dir.glob("*.json"))
        if not files:
            continue
        writer = _WRITERS[category]
        count = total = 0
        for f in files:
            try:
                records = _load_records(f)
            except Exception as e:
                # 1ファイルの失敗で残りを止めない
                result["failed"].append(f"{category}: {f.name}: {e}")
                continue
            for i, rec in enumerate(records):
                total += 1
                try:
                    if writer(rec):
                        count += 1
                    else:
                        # 部分失敗を黙って捨てると「19件落ちたが1件成功」が
                        # synced に1件と出るだけになる
                        result["failed"].append(f"{category}: {f.name}#{i} 書き込み失敗")
                except Exception as e:
                    result["failed"].append(f"{category}: {f.name}#{i}: {e}")
        if count:
            result["synced"].append(f"{category}({count}/{total}件)")
        elif total:
            # レコードはあるのに1件も書けなかった。「対象が無かった」ではなく障害。
            result["failed"].append(f"{category}: {total}件中0件同期")


def _write_status(root: Path, result: dict) -> None:
    """sync_status.yaml の last_sync を更新する（他のキーは保存する）."""
    status_path = root / "data" / "sync_status.yaml"
    try:
        import yaml
        status: dict = {}
        if status_path.exists():
            # 全上書きすると、将来 last_sync 以外のキーを足しても次の sync で消える
            try:
                loaded = yaml.safe_load(status_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    status = loaded
            except Exception:
                status = {}
        status["last_sync"] = datetime.now().isoformat()
        status_path.parent.mkdir(parents=True, exist_ok=True)
        with open(status_path, "w", encoding="utf-8") as f:
            yaml.dump(status, f, allow_unicode=True)
        result["synced"].append("sync_status更新")
    except Exception as e:
        # 「最後にいつ sync したか」の唯一の記録なので、書けなかったら見せる
        result["skipped"].append(f"sync_status: 更新できず ({e})")


# --- entry point -----------------------------------------------------------


def sync_all(project_root: Optional[str] = None) -> dict:
    """data/ → GraphRAG の一括同期.

    Neo4j 未接続時は早期リターン。個別ファイルのエラーは続行する。

    Parameters
    ----------
    project_root : str, optional
        データルート。省略時はこのファイルから2階層上（リポジトリルート）。

    Returns
    -------
    dict
        ``{"synced": [...], "failed": [...], "skipped": [...]}``
    """
    result: dict[str, list[str]] = {"synced": [], "failed": [], "skipped": []}

    try:
        from src.data.graph_store import get_mode, is_available
        # NEO4J_MODE=off は接続状態より優先されるため、is_available() だけ見ると
        # 「接続はできるが全 merge_* が False」という状態で全カテゴリを走査し、
        # 「N件中0件同期」が並ぶ。設定ミスをデータ不良と誤診させない。
        if get_mode() == "off":
            return {"synced": [], "failed": [], "skipped": ["NEO4J_MODE=off"]}
        if not is_available():
            return {"synced": [], "failed": [], "skipped": ["Neo4j未接続"]}
    except ImportError:
        return {"synced": [], "failed": [], "skipped": ["graph_store未インストール"]}

    root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]

    _sync_portfolio(root, result)
    _sync_cash(root, result)
    _sync_notes(root, result)
    _sync_history(root, result)
    _write_status(root, result)

    return result
