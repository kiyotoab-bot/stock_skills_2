"""Dashboard Tool — 資産推移の記録とローカル HTML ダッシュボード（KIK-789）.

tools/ 層は薄いファサード。src/data/asset_history.py と src/data/dashboard.py を re-export するだけ。
"""

import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.data.asset_history import (  # noqa: E402
    backfill_from_reports,
    load_asset_history,
    record_snapshot,
)
from src.data.dashboard import build_dashboard, open_dashboard  # noqa: E402

__all__ = ["build_dashboard", "open_dashboard", "record_snapshot", "load_asset_history",
           "backfill_from_reports"]
