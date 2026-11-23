"""Value Types Tool — 3類型バリュー（資産・収益・シクリカル）ファサード (KIK-786).

tools/ 層は薄いファサード。src/data/value_formulas.py（式）と src/data/value_types.py
（機械チェックの判定）を re-export するだけ。入力は get_stock_detail() の dict。
売買判断はエージェントが行う。
"""

import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.data.value_formulas import (  # noqa: E402
    book_fcf,
    compute_metrics,
    cyclical_target_price,
    dcf_bear,
    dcf_bull,
    depletion_years,
    graham_index,
    liquidation_value,
    net_cash,
    peak_profile,
)
from src.data.value_types import (  # noqa: E402
    check_asset_value,
    check_cyclical_peak,
    check_earnings_value,
    check_peak_trap,
)

__all__ = [
    # 機械チェック
    "check_asset_value",
    "check_earnings_value",
    "check_peak_trap",
    "check_cyclical_peak",
    # 式
    "compute_metrics",
    "book_fcf",
    "cyclical_target_price",
    "dcf_bear",
    "dcf_bull",
    "depletion_years",
    "graham_index",
    "liquidation_value",
    "net_cash",
    "peak_profile",
]
