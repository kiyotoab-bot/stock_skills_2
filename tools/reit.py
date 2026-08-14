"""J-REIT 評価指標ファサード（KIK-760）。

判断ロジックは持たない。src/data/reit_metrics.py を re-export するだけ。
"""

import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

try:
    from src.data.reit_metrics import (  # noqa: F401
        get_reit_metrics,
        is_reit,
        LTV_WARN,
        LTV_LIMIT,
        NAV_CHEAP,
        NAV_RICH,
    )
    HAS_REIT = True
except ImportError:  # pragma: no cover - graceful degradation
    HAS_REIT = False

    def is_reit(symbol: str) -> bool:
        return False

    def get_reit_metrics(symbol: str, price=None) -> dict:
        return {"is_reit": False, "label": "reit_metrics を読み込めない"}
