"""EDINET API v2 クライアント共通モジュール。"""

import os
import sys
from typing import Optional

import requests

EDINET_BASE = "https://api.edinet-fsa.go.jp/api/v2"
COMPANY_LIST_ZIP_URL = "https://disclosure2.edinet-fsa.go.jp/AEDI_010000.zip"

TTL_DOCUMENTS = 24   # 書類一覧: 24h
TTL_COMPANY   = 168  # 会社リスト: 7日

_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; stock-skills-edinet-client/1.0)"
}
_REQUEST_TIMEOUT = 30

_error_state: dict = {"status": "ok", "message": "", "source": None}


def get_api_key() -> str:
    return os.environ.get("EDINET_API_KEY", "")


def is_available() -> bool:
    return bool(get_api_key())


def get_error_status() -> dict:
    return dict(_error_state)


def _set_error(status: str, message: str, source: Optional[str] = None) -> None:
    _error_state["status"] = status
    _error_state["message"] = message
    _error_state["source"] = source


def reset_error_state() -> None:
    _error_state.update({"status": "ok", "message": "", "source": None})


def _build_params(extra: Optional[dict] = None) -> dict:
    params: dict = {}
    key = get_api_key()
    if key:
        params["Subscription-Key"] = key
    if extra:
        params.update(extra)
    return params


def _get_json(path: str, params: Optional[dict] = None) -> Optional[dict]:
    url = f"{EDINET_BASE}{path}"
    try:
        resp = requests.get(
            url,
            params=_build_params(params),
            headers=_HTTP_HEADERS,
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        _set_error("fetch_error", str(e), url)
        print(f"[edinet_client] HTTP GET failed ({url}): {e}", file=sys.stderr)
        return None


def _get_bytes(url: str, params: Optional[dict] = None) -> Optional[bytes]:
    try:
        resp = requests.get(
            url,
            params=_build_params(params),
            headers=_HTTP_HEADERS,
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        _set_error("fetch_error", str(e), url)
        print(f"[edinet_client] Binary GET failed ({url}): {e}", file=sys.stderr)
        return None
