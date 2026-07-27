"""JPX Tool — JPX公開データファサード。

tools/ 層は外部 API 接続のみを担う。判断ロジックは含めない。
src/data/jpx_client/ の純粋なデータ取得関数を re-export する。
"""

import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

try:
    from src.data.jpx_client import (  # noqa: E402
        get_demand_supply,
        get_error_status,
        get_investor_type,
        get_margin,
        get_short_selling,
        is_available,
    )
    HAS_JPX = True
except ImportError:
    HAS_JPX = False

    def get_demand_supply() -> dict:
        return {"available": False, "error": "jpx_client not installed", "margin": {}, "investor_type": {}, "short_selling": {}}

    def get_margin() -> dict:
        return {"available": False, "error": "jpx_client not installed"}

    def get_investor_type() -> dict:
        return {"available": False, "error": "jpx_client not installed"}

    def get_short_selling() -> dict:
        return {"available": False, "error": "jpx_client not installed"}

    def is_available() -> bool:
        return False

    def get_error_status() -> dict:
        return {"status": "unavailable", "message": "jpx_client not installed"}


__all__ = [
    "get_demand_supply",
    "get_margin",
    "get_investor_type",
    "get_short_selling",
    "is_available",
    "get_error_status",
    "HAS_JPX",
]
