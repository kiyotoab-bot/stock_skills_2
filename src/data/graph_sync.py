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
# レコード → ノードの変換は graph_writers ひとつ。save 経路も同じものを使う。
from src.data.graph_writers import (  # noqa: F401
    HISTORY_CATEGORIES,
    _WRITERS,
    _embedding,
    _first,
    _iso_date,
    _num,
    _required_num,
    _sync_forecast,
    _sync_health,
    _sync_market_context,
    _sync_report,
    _sync_research,
    _sync_screen,
    _sync_stress_test,
    _sync_trade,
)

# HISTORY_CATEGORIES は _WRITERS から導出する（このファイル下部で定義）。
# 2つを別々に並べていたため、片方だけ増やす余地が残っていた。


# --- helpers ---------------------------------------------------------------


def _load_records(path: Path) -> list[dict]:
    """1ファイルからレコード列を取り出す（実体は common.load_json_records）.

    同じ読み取りが `graph_store.sync_stock_full` にもあり、そちらは list 形式に
    未対応で全件を黙って捨てていた。共通化して差分を無くしてある。
    """
    return load_json_records(path)



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
