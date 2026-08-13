"""上場銘柄マスタ（日本語社名・33業種・市場区分・規模区分） — KIK-758.

yfinance の ``name`` は英語表記（"CANON INC" / "TOSO CO LTD"）しか返さない。
レポートの銘柄一覧を日本語にするために毎回手で書いていたが、それでは
**書き間違えても誰も気づかない**。J-Quants の上場銘柄一覧を一次情報として使う。

取得できるもの（列名は J-Quants V2 の短縮形）:
    CoName    日本語社名          例: キヤノン
    CoNameEn  英語社名
    S33Nm     33業種区分          例: 電気機器
    MktNm     市場区分            例: プライム
    ScaleCat  規模区分            例: TOPIX Large70

日次で 4,443 銘柄を毎回引くのは無駄なので、プロセス内に1回だけ載せる。

get_company_names : {symbol: 日本語社名}
get_listed_info   : 上記の全項目
"""

from __future__ import annotations

from typing import Iterable, Optional

from src.data.jquants_client.fin_summary import normalize_code

# プロセス内キャッシュ。上場マスタは日次でしか変わらないので、
# 1セッション中に何度も引き直す必要はない。
_CACHE: Optional[dict] = None


def _load_master() -> dict:
    """J-Quants の上場銘柄一覧を {4桁コード: dict} で返す。失敗時は空。"""
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    table: dict = {}
    try:
        from src.data.jquants_client._client import get_client

        client = get_client()
        if client is None:
            _CACHE = table
            return table
        df = client.get_list()
        for row in df.to_dict("records"):
            code = normalize_code(str(row.get("Code") or ""))
            if not code:
                continue
            table[code] = {
                "name_ja": row.get("CoName"),
                "name_en": row.get("CoNameEn"),
                "sector33": row.get("S33Nm"),
                "sector17": row.get("S17Nm"),
                "market": row.get("MktNm"),
                "scale": row.get("ScaleCat"),
            }
    except Exception:
        # J-Quants 未設定・ネットワーク断でもレポートは出す（graceful degradation）
        pass

    _CACHE = table
    return table


def reset_cache() -> None:
    """プロセス内キャッシュを捨てる（テスト用）。"""
    global _CACHE
    _CACHE = None


def get_listed_info(symbol: str) -> dict:
    """1銘柄の上場情報。見つからなければ空 dict。

    ``symbol`` は '7751.T' / '7751' / '77510' のいずれでもよい。
    """
    return dict(_load_master().get(normalize_code(symbol), {}))


def get_company_names(symbols: Iterable[str]) -> dict:
    """``{symbol: 日本語社名}``。取れなかった銘柄は入力の symbol をそのまま値にする。

    ⚠️ 取れなかったときに **空文字や None を返さない**。呼び出し側が
    ``names[s]`` をそのまま表示する前提なので、欠けると銘柄名が消えた
    レポートが出る。symbol にフォールバックすれば少なくとも識別はできる。
    """
    master = _load_master()
    out = {}
    for s in symbols:
        info = master.get(normalize_code(s)) or {}
        out[s] = info.get("name_ja") or s
    return out


def get_company_name(symbol: str) -> str:
    """1銘柄の日本語社名。取れなければ symbol をそのまま返す。"""
    return get_company_names([symbol])[symbol]
