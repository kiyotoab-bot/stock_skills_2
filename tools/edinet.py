"""EDINET Tool — 金融庁 EDINET API v2 ファサード。

tools/ 層は API 呼び出しのみを担う。判断ロジックは含めない。
src/data/edinet_client/ の関数を re-export する。
EDINET_API_KEY 未設定時は graceful degradation（各関数が空値を返す）。
"""

import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

try:
    from src.data.edinet_client import (  # noqa: E402
        is_available,
        get_error_status,
        clear_cache,
        get_large_shareholding,
        get_disclosures,
        get_document_list,
    )
    HAS_EDINET = True
except ImportError:
    HAS_EDINET = False

    def is_available() -> bool:
        return False

    def get_error_status() -> dict:
        return {"status": "unavailable", "message": "edinet_client not installed"}

    def clear_cache() -> None:
        pass

    def get_large_shareholding(target_date=None) -> dict:
        return {"date": target_date, "filings": [], "count": 0,
                "available": False, "error": "edinet_client not installed"}

    def get_disclosures(target_date=None, keyword=None, ticker=None) -> dict:
        return {"date": target_date, "filings": [], "count": 0,
                "available": False, "error": "edinet_client not installed"}

    def get_document_list(target_date=None) -> list:
        return []


__all__ = [
    "is_available",
    "get_error_status",
    "clear_cache",
    "get_large_shareholding",
    "get_disclosures",
    "get_document_list",
    "HAS_EDINET",
]
