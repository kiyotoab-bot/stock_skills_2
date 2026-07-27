"""EDINET コード → 会社名・証券コード マッピング。

APIレスポンスから観測した (edinetCode, filerName, secCode) を
ローカルJSONファイルに永続化し、累積的に充実させる。
EDINETコードリストCSVは公式ポータル経由のみ取得可能だが、
APIレスポンスを観測することで実用的なマッピングを構築できる。
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

_CACHE_FILE = Path("data/cache/edinet_company_map.json")
_FALLBACK_FILE = Path("data/cache/edinet_company_map_fallback.json")

_learned_map: dict[str, dict] = {}
_map_loaded = False
_map_dirty = False


def _load_map() -> None:
    global _learned_map, _map_loaded
    if _map_loaded:
        return
    _map_loaded = True
    for p in (_CACHE_FILE, _FALLBACK_FILE):
        if p.exists():
            try:
                _learned_map = json.loads(p.read_text(encoding="utf-8"))
                return
            except Exception:
                pass
    _learned_map = {}


def _save_map() -> None:
    global _map_dirty
    if not _map_dirty:
        return
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(
            json.dumps(_learned_map, ensure_ascii=False, indent=None),
            encoding="utf-8",
        )
        _map_dirty = False
    except Exception as e:
        print(f"[edinet_client] company map save failed: {e}", file=sys.stderr)


def observe(
    edinet_code: Optional[str],
    name: Optional[str],
    securities_code: Optional[str] = None,
) -> None:
    """APIレスポンスから会社情報を観測・保存する。

    get_document_list() の呼び出し元が filerName / secCode を渡すことで
    EDINETコードマップを継続的に充実させる。
    """
    global _map_dirty
    if not edinet_code or not name:
        return
    _load_map()

    existing = _learned_map.get(edinet_code)
    sec = securities_code.strip() if securities_code and securities_code.strip() else None
    ticker = f"{sec}.T" if sec and sec.isdigit() and len(sec) in (4, 5) else None

    entry = {"name": name, "securities_code": sec, "ticker": ticker}
    if existing != entry:
        _learned_map[edinet_code] = entry
        _map_dirty = True
    if _map_dirty:
        _save_map()


def get_company_map() -> dict[str, dict]:
    """学習済み会社マップを返す。"""
    _load_map()
    return _learned_map


def lookup(edinet_code: Optional[str]) -> dict:
    """edinetCode → {name, securities_code, ticker} を返す。不明時は空値。"""
    if not edinet_code:
        return {"name": None, "securities_code": None, "ticker": None}
    _load_map()
    return _learned_map.get(
        edinet_code,
        {"name": None, "securities_code": None, "ticker": None},
    )
