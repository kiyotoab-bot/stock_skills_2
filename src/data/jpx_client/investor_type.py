"""投資主体別売買動向取得 (JPX 週次 XLS)。

XLS 構造 (stock_val_1_*.xls) — Brokerage Trading セクション:
  row 3: "2026年4月 week3 (4/13 - 4/17)"
  row 29-31: Foreigners  — col[2]=Sales/Purchases/Total, col[4]=金額(千円), col[6]=Balance(千円)
  row 26-28: Individuals
  row 37-39: Investment Trusts (行番号はバージョンで変動するため動的検出)

  Balance (col[6]) = Purchases - Sales。正=純買い、負=純売り。単位: 千円
  返却は億円単位に変換 (千円 / 100000)。
"""

import re
import sys
from typing import Optional

import pandas as pd

from src.data.jpx_client._common import (
    INVESTOR_TYPE_PAGE_URL,
    _extract_first_href,
    _fetch_bytes,
    _fetch_page,
    _detect_xls_engine,
    _set_error,
)
from src.data.jpx_client._cache import read_cache, week_key, write_cache
from src.data.jpx_client._xls_helpers import read_xls, to_numeric

_INVESTOR_VAL_PATTERN = r'href="([^"]+stock_val_1_\d+\.xls[x]?)"'

_EMPTY = {
    "foreign_net_bn": None,
    "individual_net_bn": None,
    "trust_net_bn": None,
    "week_of": None,
    "foreign_consecutive_buy_weeks": None,
    "available": False,
    "error": None,
}

_CATEGORY_KEYWORDS = {
    "foreign": ["foreigners", "foreign"],
    "individual": ["individuals", "individual"],
    "trust": ["investment trusts", "investment trust", "trust"],
}


def _get_xls_url() -> Optional[str]:
    html = _fetch_page(INVESTOR_TYPE_PAGE_URL)
    if html is None:
        return None
    url = _extract_first_href(html, _INVESTOR_VAL_PATTERN)
    if url is None:
        _set_error("parse_error", "investor_type XLS link not found", "investor_type")
    return url


def _parse_week_of(df: pd.DataFrame) -> Optional[str]:
    """XLS から週の日付文字列を抽出する。例: '2026-04-17'（週末日）。"""
    for row_idx in range(min(6, len(df))):
        cell = str(df.iloc[row_idx, 0] or "")
        # "4/13 - 4/17" パターンから週末日を取得
        m = re.search(r"(\d{1,2})/(\d{1,2})\s*-\s*(\d{1,2})/(\d{1,2})", cell)
        if m:
            # 年は cell の別の場所から取得
            year_m = re.search(r"(\d{4})", cell)
            year = year_m.group(1) if year_m else "2026"
            mo_end, d_end = m.group(3), m.group(4)
            return f"{year}-{int(mo_end):02d}-{int(d_end):02d}"
        # "2026/4 week3 (4/13 - 4/17)" ASCII-safe バージョン
        m2 = re.search(r"(\d{4})/(\d{1,2})\s+week\d+\s*\(\s*(\d{1,2})/(\d{1,2})\s*-\s*(\d{1,2})/(\d{1,2})", cell)
        if m2:
            year, mo2 = m2.group(1), m2.group(2)
            d_end2 = m2.group(6)
            return f"{year}-{int(mo2):02d}-{int(d_end2):02d}"
    return None


def _find_category_net(df: pd.DataFrame, keywords: list) -> Optional[float]:
    """カテゴリ名を含む行を検索し、近接行の col[6] (Balance) を返す。単位: 千円。

    Balance は Sales または Purchases 行のいずれかに現れるため、
    キーワード行から ±2 行の範囲で非 null の col[6] を探す。
    """
    if df.shape[1] <= 6:
        return None
    for i, val in df.iloc[:, 0].items():
        text = str(val).lower()
        if any(kw in text for kw in keywords):
            # ±2 行の範囲で非 null の col6 を探す
            for offset in range(-2, 3):
                row_idx = i + offset
                if row_idx < 0 or row_idx >= len(df):
                    continue
                val6 = df.iloc[row_idx, 6]
                try:
                    if pd.notna(val6) and val6 != "":
                        cleaned = str(val6).replace(",", "")
                        return float(cleaned)
                except (TypeError, ValueError):
                    pass
    return None


def _parse_xls(data: bytes) -> Optional[dict]:
    engine = _detect_xls_engine(data)
    df = read_xls(data, engine)
    if df is None:
        return None
    try:
        week_of = _parse_week_of(df)

        foreign_net = _find_category_net(df, _CATEGORY_KEYWORDS["foreign"])
        individual_net = _find_category_net(df, _CATEGORY_KEYWORDS["individual"])
        trust_net = _find_category_net(df, _CATEGORY_KEYWORDS["trust"])

        def _to_bn(v: Optional[float]) -> Optional[float]:
            if v is None:
                return None
            return round(v / 100_000, 1)  # 千円 → 億円

        return {
            "foreign_net_bn": _to_bn(foreign_net),
            "individual_net_bn": _to_bn(individual_net),
            "trust_net_bn": _to_bn(trust_net),
            "week_of": week_of,
        }
    except Exception as e:
        _set_error("parse_error", f"investor_type XLS parse failed: {e}", "investor_type")
        print(f"[jpx_client] investor_type parse error: {e}", file=sys.stderr)
        return None


def _calc_consecutive_weeks(key: str, foreign_net: Optional[float]) -> Optional[int]:
    """過去キャッシュを遡って外国人の連続買い越し（または売り越し）週数を返す。"""
    if foreign_net is None:
        return None
    direction = 1 if foreign_net >= 0 else -1
    count = 1
    current_key = key
    for _ in range(7):
        prev_key = _prev_week_key(current_key)
        if not prev_key:
            break
        cached = read_cache("investor", prev_key, "weekly")
        if not cached or cached.get("foreign_net_bn") is None:
            break
        prev_net = cached["foreign_net_bn"]
        prev_dir = 1 if prev_net >= 0 else -1
        if prev_dir != direction:
            break
        count += 1
        current_key = prev_key
    return count


def get_investor_type() -> dict:
    """投資主体別売買動向を取得する（キャッシュ付き）。"""
    key = week_key()
    cached = read_cache("investor", key, "weekly")
    if cached:
        result = {k: v for k, v in cached.items() if not k.startswith("_")}
        result["available"] = True
        result["error"] = None
        return result

    url = _get_xls_url()
    if url is None:
        return {**_EMPTY, "error": _error_state_msg()}

    xls_data = _fetch_bytes(url)
    if xls_data is None:
        return {**_EMPTY, "error": _error_state_msg()}

    parsed = _parse_xls(xls_data)
    if parsed is None:
        return {**_EMPTY, "error": _error_state_msg()}

    consecutive = _calc_consecutive_weeks(key, parsed.get("foreign_net_bn"))
    parsed["foreign_consecutive_buy_weeks"] = consecutive

    write_cache("investor", key, parsed)
    return {**parsed, "available": True, "error": None}


def _error_state_msg() -> str:
    from src.data.jpx_client._common import get_error_status
    s = get_error_status()
    return s.get("message") or s.get("status") or "unknown error"


def _prev_week_key(current: str) -> str:
    try:
        year = int(current[:4])
        week = int(current[4:])
        if week > 1:
            return f"{year}{week - 1:02d}"
        return f"{year - 1}53"
    except (ValueError, IndexError):
        return ""
