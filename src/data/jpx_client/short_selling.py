"""空売り出来高取得 (JPX 日次 PDF + pdfminer.six)。

JPX の空売り PDF (-m.pdf) から市場全体の空売り出来高 (d) を抽出する。
注: PDF は 空売り比率 (%) を直接含まず、空売り出来高の絶対量のみ提供される。
  (a) 裸空売り + (b) 借入空売り + (c) その他 = (d) 空売り合計

空売り比率の代わりに前日比 (%) を提供し、空売り圧力の増減傾向を示す。
"""

import io
import re
import sys
from typing import Optional

from src.data.jpx_client._common import (
    SHORT_SELLING_PAGE_URL,
    _extract_first_href,
    _fetch_bytes,
    _fetch_page,
    _set_error,
)
from src.data.jpx_client._cache import date_key, read_cache, write_cache

try:
    from pdfminer.high_level import extract_text as _pdf_extract
    from pdfminer.layout import LAParams as _LAParams
    _HAS_PDFMINER = True
except ImportError:
    _HAS_PDFMINER = False

_SHORT_PDF_PATTERN = r'href="([^"]+/\d{6}-m\.pdf)"'

_EMPTY = {
    "short_volume": None,
    "dod_change_pct": None,
    "date": None,
    "available": False,
    "error": None,
}


def _get_pdf_url() -> Optional[str]:
    html = _fetch_page(SHORT_SELLING_PAGE_URL)
    if html is None:
        return None
    url = _extract_first_href(html, _SHORT_PDF_PATTERN)
    if url is None:
        _set_error("parse_error", "short selling PDF link not found", "short_selling")
    return url


def _parse_pdf(pdf_bytes: bytes) -> Optional[dict]:
    if not _HAS_PDFMINER:
        _set_error("unavailable", "pdfminer.six not installed", "short_selling")
        return None
    try:
        laparams = _LAParams(line_margin=0.1, word_margin=0.1, char_margin=2.0, boxes_flow=None)
        text = _pdf_extract(io.BytesIO(pdf_bytes), laparams=laparams)

        # 日付抽出: "2026/4/28"
        date_m = re.search(r"(\d{4}/\d{1,2}/\d{1,2})", text)
        date_str = None
        if date_m:
            parts = date_m.group(1).split("/")
            date_str = f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"

        # 数値抽出: カンマ区切り整数（株数）
        nums = re.findall(r"(\d{1,3}(?:,\d{3})+)", text)
        int_vals = []
        for n in nums:
            try:
                int_vals.append(int(n.replace(",", "")))
            except ValueError:
                pass

        if not int_vals:
            _set_error("parse_error", "空売り出来高数値を抽出できませんでした", "short_selling")
            return None

        # 最大値が (d) = 空売り合計
        total_short = max(int_vals)

        # 妥当性チェック（1千万〜100億の範囲）
        if not (1_000_000 <= total_short <= 10_000_000_000):
            _set_error("parse_error", f"空売り合計値が範囲外: {total_short}", "short_selling")
            return None

        return {"short_volume": total_short, "date": date_str}
    except Exception as e:
        _set_error("parse_error", f"short selling PDF parse failed: {e}", "short_selling")
        print(f"[jpx_client] short_selling parse error: {e}", file=sys.stderr)
        return None


def get_short_selling() -> dict:
    """空売り出来高を取得する（キャッシュ付き）。

    Returns:
        {
            short_volume: int | None,       # 空売り合計出来高（株数）
            dod_change_pct: float | None,   # 前日比（%）
            date: str | None,               # "2026-04-28"
            available: bool,
            error: str | None,
        }
    """
    if not _HAS_PDFMINER:
        return {**_EMPTY, "error": "pdfminer.six not installed"}

    key = date_key()
    cached = read_cache("short", key, "daily")
    if cached:
        result = {k: v for k, v in cached.items() if not k.startswith("_")}
        result["available"] = True
        result["error"] = None
        return result

    url = _get_pdf_url()
    if url is None:
        return {**_EMPTY, "error": _error_state_msg()}

    pdf_data = _fetch_bytes(url)
    if pdf_data is None:
        return {**_EMPTY, "error": _error_state_msg()}

    parsed = _parse_pdf(pdf_data)
    if parsed is None:
        return {**_EMPTY, "error": _error_state_msg()}

    # 前日比の計算
    from datetime import datetime, timedelta
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    prev = read_cache("short", yesterday, "daily")
    dod_change = None
    if prev and prev.get("short_volume") and parsed.get("short_volume"):
        try:
            prev_vol = float(prev["short_volume"])
            curr_vol = float(parsed["short_volume"])
            dod_change = round((curr_vol - prev_vol) / prev_vol * 100, 1)
        except (TypeError, ZeroDivisionError):
            pass

    parsed["dod_change_pct"] = dod_change
    write_cache("short", key, parsed)
    return {**parsed, "available": True, "error": None}


def _error_state_msg() -> str:
    from src.data.jpx_client._common import get_error_status
    s = get_error_status()
    return s.get("message") or s.get("status") or "unknown error"
