"""GraphRAG 基盤（Neo4j / TEI）が生きているかの確認（KIK-784）.

日次 Step 0 の ``check_routine_health()`` から呼ぶ。

なぜ要るか: 2026-11-06 に「syncして」で発覚するまで、Docker の Neo4j と TEI の
コンテナが**約2ヶ月間止まっていた**のに誰も気づかなかった。

- Neo4j の接続失敗は既定で無音（KIK-749）
- ``check_schema()`` は未接続なら ``alerts=[]`` を返す
- ``check_routine_health()`` は「Neo4j 未接続なら黙って飛ばす」設計だった

この3つが重なり、日次チェックは毎日「異常なし」を返していた。その間、
GraphRAG の文脈補完・ベクトル検索・保存時の dual-write はすべて効いていなかった。
データの正本は ``data/`` なので損失は無いが、**止まっていること自体が見えない**のが問題。

方針:
- ``NEO4J_MODE=off`` が環境変数で明示されていれば意図的な停止とみなし、何も出さない
  （テストもこの設定で動く）
- それ以外で Neo4j / TEI に繋がらなければ WARN を出し、起動方法を添える
- 最後の sync からの日数も出す。Neo4j が落ちている間に保存したデータは、
  sync するまでグラフに入らない
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

SYNC_STALE_DAYS = {"warn": 7, "critical": 30}

_START_HINT = "docker compose up -d で起動してください"


def _alert(type_: str, severity: str, message: str, value=None) -> dict:
    return {"symbol": "INFRA", "type": type_, "severity": severity,
            "message": message, "value": value}


_UNREADABLE = "unreadable"


def _default_status_path() -> Path:
    # graph_sync._write_status() はリポジトリ直下の data/ に書く。cwd 基準だと
    # 別ディレクトリから日次を回したときに偽の sync_never_run が出る
    return Path(__file__).resolve().parents[2] / "data" / "sync_status.yaml"


def read_last_sync(status_path: str | None = None) -> str | None:
    """``sync_status.yaml`` の ``last_sync`` の日付（ISO）を返す。

    ファイルが無い・キーが無い → None（sync の記録なし）。
    ファイルはあるが読めない・日付として読めない → ``"unreadable"``。
    「記録が無い」と「記録が壊れている」は対処が違うので混ぜない。
    """
    p = Path(status_path) if status_path else _default_status_path()
    if not p.exists():
        return None
    try:
        import yaml
        loaded = yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:
        return _UNREADABLE
    if loaded is None:
        return None
    if not isinstance(loaded, dict):
        return _UNREADABLE
    raw = loaded.get("last_sync")
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    try:
        return date.fromisoformat(str(raw)[:10]).isoformat()
    except ValueError:
        return _UNREADABLE


def check_sync_freshness(last_sync: str | None,
                         today: date | None = None) -> list[dict]:
    """最後の sync からの経過日数。7日超で WARN、30日超で CRITICAL。"""
    today = today or date.today()
    if not last_sync:
        return [_alert("sync_never_run", "WARN",
                       "GraphRAG への sync の記録がありません（「syncして」で実行）")]
    try:
        elapsed = (today - date.fromisoformat(last_sync)).days
    except ValueError:
        # 黙らない（読めない記録は「新しい」とも「古い」とも言えない）
        return [_alert("sync_status_unreadable", "WARN",
                       "data/sync_status.yaml の last_sync を読めません。"
                       "「syncして」で書き直されます")]
    if elapsed > SYNC_STALE_DAYS["critical"]:
        sev = "CRITICAL"
    elif elapsed > SYNC_STALE_DAYS["warn"]:
        sev = "WARN"
    else:
        return []
    return [_alert("sync_stale", sev,
                   f"GraphRAG への sync が {elapsed}日 未実行（最終 {last_sync}）。"
                   "Neo4j が止まっていた間の保存はグラフに入っていない（「syncして」で解消）",
                   elapsed)]


def check_infra_health(status_path: str | None = None,
                       today: date | None = None) -> list[dict]:
    """Neo4j / TEI の接続と sync の鮮度を見る。

    ``NEO4J_MODE=off`` が明示されていれば空リストを返す（意図的な停止）。
    接続確認の例外は「繋がらない」として扱う（確認できないことを黙らない）。
    """
    if os.environ.get("NEO4J_MODE", "").strip().lower() == "off":
        return []

    alerts: list[dict] = []
    # graph_store.is_available() はキャッシュを持たず毎回 verify_connectivity() する。
    # localhost でコンテナが止まっているだけなら即座に拒否されるが、到達不能なホストを
    # NEO4J_URI に指定していると接続タイムアウト（既定 約30秒）を払いうる。日次1回なので許容
    try:
        from src.data import graph_store
        neo4j_ok = bool(graph_store.is_available())
    except Exception:
        neo4j_ok = False
    if not neo4j_ok:
        alerts.append(_alert(
            "neo4j_unavailable", "WARN",
            "Neo4j に接続できません。GraphRAG の文脈補完・ベクトル検索・"
            f"保存時の書き込みが止まっています（データの正本 data/ は無事）。{_START_HINT}"))

    try:
        from src.data import embedding_client
        tei_ok = bool(embedding_client.is_available())
    except Exception:
        tei_ok = False
    if not tei_ok:
        alerts.append(_alert(
            "tei_unavailable", "WARN",
            "TEI（埋め込み）に接続できません。保存したノードに埋め込みが付かず、"
            f"ベクトル検索から漏れます。{_START_HINT}"))

    alerts.extend(check_sync_freshness(read_last_sync(status_path), today))
    return alerts
