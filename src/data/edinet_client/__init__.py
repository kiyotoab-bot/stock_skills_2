"""EDINET API v2 クライアント。

大量保有報告書・有価証券報告書等の開示情報を取得する。
EDINET_API_KEY 未設定時は graceful degradation（空値を返す）。
"""

from src.data.edinet_client._common import is_available, get_error_status
from src.data.edinet_client._cache import clear as clear_cache
from src.data.edinet_client.documents import (
    get_large_shareholding,
    get_disclosures,
    get_document_list,
)

__all__ = [
    "is_available",
    "get_error_status",
    "clear_cache",
    "get_large_shareholding",
    "get_disclosures",
    "get_document_list",
]
