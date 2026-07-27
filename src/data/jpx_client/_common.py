"""JPX公開データクライアント共通モジュール。"""

import re
import sys
from typing import Optional

import requests

JPX_BASE = "https://www.jpx.co.jp"

MARGIN_PAGE_URL = f"{JPX_BASE}/markets/statistics-equities/margin/index.html"
INVESTOR_TYPE_PAGE_URL = f"{JPX_BASE}/markets/statistics-equities/investor-type/index.html"
SHORT_SELLING_PAGE_URL = f"{JPX_BASE}/markets/statistics-equities/short-selling/index.html"

TTL_WEEKLY = 168
TTL_DAILY = 24

_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; stock-skills-jpx-client/1.0)"
}
_REQUEST_TIMEOUT = 30

_error_state: dict = {
    "status": "ok",
    "message": "",
    "source": None,
}


def get_error_status() -> dict:
    return dict(_error_state)


def reset_error_state() -> None:
    _error_state.update({"status": "ok", "message": "", "source": None})


def is_available() -> bool:
    return True


def _set_error(status: str, message: str, source: Optional[str] = None) -> None:
    _error_state["status"] = status
    _error_state["message"] = message
    _error_state["source"] = source


def _fetch_page(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, headers=_HTTP_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text
    except Exception as e:
        _set_error("fetch_error", str(e))
        print(f"[jpx_client] HTTP fetch failed: {e}", file=sys.stderr)
        return None


def _fetch_bytes(url: str) -> Optional[bytes]:
    try:
        resp = requests.get(url, headers=_HTTP_HEADERS, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        _set_error("fetch_error", str(e))
        print(f"[jpx_client] Binary fetch failed: {e}", file=sys.stderr)
        return None


def _extract_first_href(html: str, pattern: str) -> Optional[str]:
    """HTML から正規表現パターンで最初の href を返す。相対 URL は絶対に変換。"""
    match = re.search(pattern, html)
    if not match:
        return None
    href = match.group(1)
    return JPX_BASE + href if href.startswith("/") else href


def _detect_xls_engine(data: bytes) -> str:
    """magic bytes から Excel エンジンを判定する。"""
    if data[:4] == b"\xd0\xcf\x11\xe0":
        return "xlrd"
    return "openpyxl"
