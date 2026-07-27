"""信用取引残高取得 (JPX 週次 XLS)。

XLS 構造 (mtdailyk*.xls):
  row 0: タイトル
  row 1: "as of YYYY/M/DD application based"
  row 5-6: 列ヘッダー
  row 7+: 銘柄別データ
    col[8]  = Outstanding Sales 信用売り残 (株数)
    col[11] = Outstanding Purchases 信用買い残 (株数)
  全行を合計して市場全体の信用倍率を算出する。
"""

import re
import sys
from typing import Optional

import pandas as pd

from src.data.jpx_client._common import (
    MARGIN_PAGE_URL,
    _extract_first_href,
    _fetch_bytes,
    _fetch_page,
    _detect_xls_engine,
    _set_error,
)
from src.data.jpx_client._cache import read_cache, week_key, write_cache
from src.data.jpx_client._xls_helpers import read_xls, to_numeric

_MARGIN_LINK_PATTERN = r'href="([^"]+mtdailyk\d+\.xls[x]?)"'

_SIGNAL_HIGH = 4.0
_SIGNAL_LOW = 2.0

_EMPTY = {
    "buy_shares": None,
    "sell_shares": None,
    "margin_ratio": None,
    "wow_change_pct": None,
    "week_of": None,
    "signal": None,
    "available": False,
    "error": None,
}


def _get_xls_url() -> Optional[str]:
    html = _fetch_page(MARGIN_PAGE_URL)
    if html is None:
        return None
    url = _extract_first_href(html, _MARGIN_LINK_PATTERN)
    if url is None:
        _set_error("parse_error", "margin XLS link not found in page HTML", "margin")
    return url


def _parse_xls(data: bytes) -> Optional[dict]:
    engine = _detect_xls_engine(data)
    df = read_xls(data, engine)
    if df is None:
        return None
    try:
        # 日付をヘッダー行から取得
        week_of = None
        for row_idx in range(min(5, len(df))):
            cell = str(df.iloc[row_idx, 1] or "")
            m = re.search(r"as of (\d{4}/\d{1,2}/\d{1,2})", cell)
            if m:
                raw = m.group(1)
                parts = raw.split("/")
                week_of = f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
                break

        # データ行（row 7以降）で数値列を合計
        data_df = df.iloc[7:].copy()
        sell = to_numeric(data_df.iloc[:, 8]).dropna()
        buy = to_numeric(data_df.iloc[:, 11]).dropna()

        total_sell = int(sell.sum())
        total_buy = int(buy.sum())

        if total_sell <= 0:
            _set_error("parse_error", "信用売り残合計がゼロまたは負", "margin")
            return None

        ratio = round(total_buy / total_sell, 2)

        signal = "neutral"
        if ratio >= _SIGNAL_HIGH:
            signal = "high"
        elif ratio < _SIGNAL_LOW:
            signal = "low"

        return {
            "buy_shares": total_buy,
            "sell_shares": total_sell,
            "margin_ratio": ratio,
            "week_of": week_of,
            "signal": signal,
        }
    except Exception as e:
        _set_error("parse_error", f"margin XLS parse failed: {e}", "margin")
        print(f"[jpx_client] margin parse error: {e}", file=sys.stderr)
        return None


def get_margin() -> dict:
    """信用取引残高を取得する（キャッシュ付き）。

    Returns:
        {
            buy_shares: int | None,     # 信用買い残（株数）
            sell_shares: int | None,    # 信用売り残（株数）
            margin_ratio: float | None, # 信用倍率
            wow_change_pct: float | None,
            week_of: str | None,        # "2026-04-27"
            signal: str | None,         # "high" | "neutral" | "low"
            available: bool,
            error: str | None,
        }
    """
    key = week_key()
    cached = read_cache("margin", key, "weekly")
    if cached:
        result = {k: v for k, v in cached.items() if not k.startswith("_")}
        result["available"] = True
        result["error"] = None
        return result

    url = _get_xls_url()
    if url is None:
        err = _error_state_msg()
        return {**_EMPTY, "error": err}

    xls_data = _fetch_bytes(url)
    if xls_data is None:
        err = _error_state_msg()
        return {**_EMPTY, "error": err}

    parsed = _parse_xls(xls_data)
    if parsed is None:
        err = _error_state_msg()
        return {**_EMPTY, "error": err}

    # 前週比の計算（前週キャッシュがあれば）
    prev_key = _prev_week_key(key)
    prev = read_cache("margin", prev_key, "weekly")
    wow_change = None
    if prev and prev.get("margin_ratio") and parsed.get("margin_ratio"):
        try:
            prev_ratio = float(prev["margin_ratio"])
            curr_ratio = float(parsed["margin_ratio"])
            wow_change = round((curr_ratio - prev_ratio) / prev_ratio * 100, 1)
        except (TypeError, ZeroDivisionError):
            pass

    parsed["wow_change_pct"] = wow_change
    write_cache("margin", key, parsed)

    return {**parsed, "available": True, "error": None}


def _error_state_msg() -> str:
    from src.data.jpx_client._common import get_error_status
    s = get_error_status()
    return s.get("message") or s.get("status") or "unknown error"


def _prev_week_key(current: str) -> str:
    """現在の ISO 週キーから前週のキーを生成する。"""
    try:
        year = int(current[:4])
        week = int(current[4:])
        if week > 1:
            return f"{year}{week - 1:02d}"
        return f"{year - 1}53"
    except (ValueError, IndexError):
        return ""
