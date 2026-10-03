"""Rates Tool — 米国債利回りのファサード（KIK-779）。

tools/ 層は外部 API 接続のみを担う。判断ロジックは含めない。
src/data/treasury_yields.py の取得関数を re-export する。

長短金利差（10Y-2Y）はここから取る。yfinance の 2YY=F（先物）は限月の乗り換えで
財務省の値から 20bp ずれることがあるので使わない。
"""

import sys
from pathlib import Path

_root = str(Path(__file__).resolve().parent.parent)
if _root not in sys.path:
    sys.path.insert(0, _root)

try:
    from src.data.treasury_yields import get_treasury_curve  # noqa: E402
    HAS_RATES = True
except ImportError:
    HAS_RATES = False

    def get_treasury_curve(today=None, fetch=None) -> dict:
        return {"available": False, "source": None, "date": None, "y2": None, "y10": None,
                "spread": None, "history": [], "warning": None,
                "error": "treasury_yields not installed"}

__all__ = ["get_treasury_curve", "HAS_RATES"]
