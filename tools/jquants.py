"""J-Quants Tool — 個別銘柄需給データファサード。

tools/ 層は外部 API 接続のみを担う。判断ロジックは含めない。
src/data/jquants_client/ の純粋なデータ取得関数を re-export する。
"""

import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(Path(_root) / ".env", override=False)
except Exception:
    pass

try:
    from src.data.jquants_client import (  # noqa: E402
        get_stock_margin,
        is_available,
    )
    HAS_JQUANTS = True
except ImportError:
    HAS_JQUANTS = False

    def get_stock_margin(symbol: str) -> dict:
        return {"available": False, "error": "jquants-api-client not installed"}

    def is_available() -> bool:
        return False


__all__ = [
    "get_stock_margin",
    "is_available",
    "HAS_JQUANTS",
]
