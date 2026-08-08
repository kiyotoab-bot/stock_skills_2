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

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

# SKILL.md の同期対象表と1対1に対応する。ここに足したら SKILL.md も更新すること。
HISTORY_CATEGORIES = ("trade", "screen", "report", "research", "health")


# --- helpers ---------------------------------------------------------------


def _load_records(path: Path) -> list[dict]:
    """1ファイルからレコード列を取り出す.

    履歴ファイルには dict 形式（`save_*()` が書いたもの）と list 形式
    （direct action が書いたもの）が混在している。実データ 20件の trade は
    全て list だった。どちらでも読めるようにする。
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _first(rec: dict, *keys: str, default: Any = None) -> Any:
    """最初に見つかった非 None のキーの値を返す（キー名の揺れを吸収）."""
    for k in keys:
        v = rec.get(k)
        if v is not None:
            return v
    return default


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# --- per-category writers --------------------------------------------------


def _sync_trade(rec: dict) -> bool:
    from src.data.graph_store import merge_trade

    symbol = rec.get("symbol")
    # 実データでは direction が action / trade_type どちらかに入る（action が全件、
    # trade_type は 8/20 件のみ）。action を先に見る。
    trade_type = _first(rec, "action", "trade_type")
    trade_date = _first(rec, "date", "trade_date")
    if not (symbol and trade_type and trade_date):
        return False
    return merge_trade(
        trade_date=trade_date,
        trade_type=str(trade_type).lower(),
        symbol=symbol,
        shares=int(_num(rec.get("shares"))),
        price=_num(rec.get("price")),
        currency=rec.get("currency", "JPY"),
        memo=rec.get("memo", "") or "",
        sell_price=rec.get("sell_price"),
        # 実現損益のキーは realized_pnl / realized_pl / pnl の3通りが存在する
        realized_pnl=_first(rec, "realized_pnl", "realized_pl", "pnl"),
        hold_days=rec.get("hold_days"),
    )


def _sync_screen(rec: dict) -> bool:
    from src.data.graph_store import merge_screen, merge_stock

    screen_date = rec.get("date")
    if not screen_date:
        return False
    results = rec.get("results") or []
    symbols = [r.get("symbol") for r in results if isinstance(r, dict) and r.get("symbol")]
    for r in results:
        if isinstance(r, dict) and r.get("symbol"):
            merge_stock(symbol=r["symbol"], name=r.get("name", "") or "",
                        sector=r.get("sector", "") or "")
    return merge_screen(
        screen_date=screen_date,
        preset=rec.get("preset", "") or "",
        region=rec.get("region", "") or "",
        count=int(_num(_first(rec, "count", default=len(symbols)))),
        symbols=symbols,
    )


def _sync_report(rec: dict) -> bool:
    from src.data.graph_store import merge_report_full, merge_stock

    symbol = rec.get("symbol")
    report_date = rec.get("date")
    if not (symbol and report_date):
        return False
    merge_stock(symbol=symbol, name=rec.get("name", "") or "",
                sector=rec.get("sector", "") or "")
    return merge_report_full(
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
    from src.data.graph_store import merge_research_full

    research_date = rec.get("date")
    target = rec.get("target")
    if not (research_date and target):
        return False
    return merge_research_full(
        research_date=research_date,
        research_type=_first(rec, "research_type", "type", default="") or "",
        target=target,
        summary=rec.get("summary", "") or "",
        grok_research=rec.get("grok_research"),
        x_sentiment=rec.get("x_sentiment"),
        news=rec.get("news"),
    )


def _sync_health(rec: dict) -> bool:
    from src.data.graph_store import merge_health

    health_date = rec.get("date")
    if not health_date:
        return False
    positions = rec.get("positions") or []
    symbols = [p.get("symbol") for p in positions if isinstance(p, dict) and p.get("symbol")]
    return merge_health(
        health_date=health_date,
        summary=rec.get("summary") or {},
        symbols=symbols,
    )


_WRITERS: dict[str, Callable[[dict], bool]] = {
    "trade": _sync_trade,
    "screen": _sync_screen,
    "report": _sync_report,
    "research": _sync_research,
    "health": _sync_health,
}


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
        count = 0
        for nf in sorted(notes_dir.glob("*.json")):
            try:
                # 旧実装は data[0] しか見ておらず、1ファイルに複数ノートを持つ
                # 19ファイルから 36件が毎回落ちていた（123件同期 / 実体159件）。
                for note in _load_records(nf):
                    merge_note(
                        note_id=note.get("id", nf.stem),
                        note_date=note.get("date", ""),
                        note_type=note.get("type", "observation"),
                        content=note.get("content", ""),
                        symbol=note.get("symbol"),
                        source=note.get("source", "claude"),
                        category=note.get("category", ""),
                    )
                    count += 1
            except Exception:
                result["failed"].append(f"note: {nf.name}")
        if count:
            result["synced"].append(f"notes({count}件)")
    except Exception as e:
        result["failed"].append(f"notes: {e}")


def _sync_cash(root: Path, result: dict) -> None:
    """data/cash_balance.json → Portfolio ノードの cash_* プロパティ + Note 履歴.

    KIK-736 まで SKILL.md の同期表に載っているだけで呼び出し口が無かった。
    現金は銘柄ではないので HOLDS を張れず（``sync_portfolio`` も ``*.CASH`` を
    除外する）、Portfolio アンカーの属性として持たせる。残高の推移を後から
    辿れるよう、基準日ごとに Note(type=cash) も残す。
    """
    cash_path = root / "data" / "cash_balance.json"
    if not cash_path.exists():
        return
    try:
        from src.data.graph_store import extract_cash_currencies, merge_cash_balance
        from src.data.graph_store.note import merge_note

        records = _load_records(cash_path)
        if not records:
            result["skipped"].append("cash: 中身が空")
            return
        balances = records[0]

        # last_updated（残高の基準日）優先。無ければ updated_at の日付部分。
        balance_date = str(_first(balances, "last_updated", "updated_at", default=""))[:10]
        if not balance_date:
            result["skipped"].append("cash: 基準日が無い")
            return

        currencies = extract_cash_currencies(balances)
        if not currencies:
            result["skipped"].append("cash: 通貨キーが無い")
            return

        if not merge_cash_balance(balance_date, balances):
            result["failed"].append("cash: Portfolio への書き込み失敗")
            return

        # id を基準日で切るので、同じ日の再 sync では上書きされ増えない
        amounts = " / ".join(
            f"{code} {amount:,.0f}" for code, amount in sorted(currencies.items())
        )
        memo = balances.get("memo", "") or ""
        merge_note(
            note_id=f"cash_{balance_date}",
            note_date=balance_date,
            note_type="cash",
            content=f"現金残高 {amounts}" + (f" — {memo}" if memo else ""),
            category="portfolio",
            source="cash_balance.json",
        )
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
        count = 0
        for f in files:
            try:
                for rec in _load_records(f):
                    if writer(rec):
                        count += 1
            except Exception:
                # 1ファイルの失敗で残りを止めない
                result["failed"].append(f"{category}: {f.name}")
        if count:
            result["synced"].append(f"{category}({count}件)")
        else:
            # ファイルはあるのに1件も書けなかった = 気づけるようにする
            result["skipped"].append(f"{category}: {len(files)}ファイル中0件同期")


def _write_status(root: Path, result: dict) -> None:
    try:
        import yaml
        status_path = root / "data" / "sync_status.yaml"
        status_path.parent.mkdir(parents=True, exist_ok=True)
        with open(status_path, "w", encoding="utf-8") as f:
            yaml.dump({"last_sync": datetime.now().isoformat()}, f)
        result["synced"].append("sync_status更新")
    except Exception:
        pass  # non-critical


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
        from src.data.graph_store._common import is_available
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
