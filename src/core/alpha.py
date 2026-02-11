"""Alpha signal: change score calculation (KIK-346).

Detects stocks with positive fundamental changes that the market
has not yet priced in.  Returns a composite "change score" (0-100)
based on four indicators: accruals quality, revenue growth
acceleration, FCF yield, and ROE improvement trend.
"""

import numpy as np
from typing import Optional


# ---------------------------------------------------------------------------
# 1. Accruals (earnings quality) -- 25 pts
# ---------------------------------------------------------------------------

def compute_accruals_score(stock_detail: dict) -> tuple[float, Optional[float]]:
    """Accruals score.  Returns (score, raw_accruals).

    accruals = (net_income - operating_cf) / total_assets
    Lower values indicate higher-quality earnings backed by cash.
    """
    net_income = stock_detail.get("net_income_stmt")
    operating_cf = stock_detail.get("operating_cashflow")
    total_assets = stock_detail.get("total_assets")

    if net_income is None or operating_cf is None or total_assets is None:
        return 0.0, None
    if total_assets == 0:
        return 0.0, None

    accruals = (net_income - operating_cf) / total_assets

    if accruals < -0.05:
        score = 25.0
    elif accruals < 0.0:
        score = 20.0
    elif accruals < 0.05:
        score = 15.0
    elif accruals < 0.10:
        score = 10.0
    else:
        score = 0.0

    return score, accruals


# ---------------------------------------------------------------------------
# 2. Revenue growth acceleration -- 25 pts
# ---------------------------------------------------------------------------

def compute_revenue_acceleration_score(stock_detail: dict) -> tuple[float, Optional[float]]:
    """Revenue growth acceleration score.  Returns (score, raw_acceleration).

    Compares current-period revenue growth rate with the prior period's
    growth rate.  A positive acceleration means growth is speeding up.
    """
    rev = stock_detail.get("revenue_history")

    if not rev or len(rev) < 3:
        return 0.0, None

    # rev[0]=latest, rev[1]=one period ago, rev[2]=two periods ago
    rev0, rev1, rev2 = rev[0], rev[1], rev[2]

    if rev0 is None or rev1 is None or rev2 is None:
        return 0.0, None
    if rev1 == 0 or rev2 == 0:
        return 0.0, None

    current_growth = (rev0 - rev1) / abs(rev1)
    previous_growth = (rev1 - rev2) / abs(rev2)
    acceleration = current_growth - previous_growth

    if acceleration > 0.10:
        score = 25.0
    elif acceleration > 0.05:
        score = 20.0
    elif acceleration > 0.0:
        score = 15.0
    elif acceleration > -0.05:
        score = 10.0
    else:
        score = 0.0

    return score, acceleration


# ---------------------------------------------------------------------------
# 3. FCF yield -- 25 pts
# ---------------------------------------------------------------------------

def compute_fcf_yield_score(stock_detail: dict) -> tuple[float, Optional[float]]:
    """FCF yield score.  Returns (score, raw_fcf_yield).

    fcf_yield = fcf / market_cap
    """
    fcf = stock_detail.get("fcf")
    market_cap = stock_detail.get("market_cap")

    if fcf is None or market_cap is None:
        return 0.0, None
    if market_cap == 0:
        return 0.0, None

    fcf_yield = fcf / market_cap

    if fcf_yield > 0.10:
        score = 25.0
    elif fcf_yield > 0.06:
        score = 20.0
    elif fcf_yield > 0.03:
        score = 15.0
    elif fcf_yield > 0.0:
        score = 10.0
    else:
        score = 0.0

    return score, fcf_yield


# ---------------------------------------------------------------------------
# 4. ROE improvement trend -- 25 pts
# ---------------------------------------------------------------------------

def compute_roe_trend_score(stock_detail: dict) -> tuple[float, Optional[float]]:
    """ROE improvement trend score.  Returns (score, raw_slope).

    Calculates ROE for three periods and fits a linear regression to
    determine if ROE is improving over time.
    """
    ni_hist = stock_detail.get("net_income_history")
    eq_hist = stock_detail.get("equity_history")

    if not ni_hist or not eq_hist:
        return 0.0, None
    if len(ni_hist) < 3 or len(eq_hist) < 3:
        return 0.0, None

    # Compute ROE for latest 3 periods
    roes = []
    for i in range(3):
        ni = ni_hist[i]
        eq = eq_hist[i]
        if ni is None or eq is None or eq == 0:
            return 0.0, None
        roes.append(ni / eq)

    # roes[0]=latest, roes[1]=mid, roes[2]=oldest
    # polyfit expects x in chronological order: oldest -> newest
    y = [roes[2], roes[1], roes[0]]
    x = [0, 1, 2]

    coeffs = np.polyfit(x, y, deg=1)
    slope = float(coeffs[0])

    if slope > 0.03:
        score = 25.0
    elif slope > 0.01:
        score = 20.0
    elif slope > 0.0:
        score = 15.0
    elif slope > -0.01:
        score = 10.0
    else:
        score = 0.0

    return score, slope


# ---------------------------------------------------------------------------
# Composite change score
# ---------------------------------------------------------------------------

_PASS_THRESHOLD = 15.0


def compute_change_score(stock_detail: dict) -> dict:
    """Compute composite change score across all four indicators.

    Returns:
        dict with keys:
            change_score     -- aggregate score 0-100
            accruals         -- {"score": float, "raw": Optional[float]}
            revenue_acceleration -- {"score": float, "raw": Optional[float]}
            fcf_yield        -- {"score": float, "raw": Optional[float]}
            roe_trend        -- {"score": float, "raw": Optional[float]}
            passed_count     -- number of indicators scoring >= 15
            quality_pass     -- True if passed_count >= 3
    """
    acc_score, acc_raw = compute_accruals_score(stock_detail)
    rev_score, rev_raw = compute_revenue_acceleration_score(stock_detail)
    fcf_score, fcf_raw = compute_fcf_yield_score(stock_detail)
    roe_score, roe_raw = compute_roe_trend_score(stock_detail)

    total = acc_score + rev_score + fcf_score + roe_score

    passed = sum(
        1 for s in [acc_score, rev_score, fcf_score, roe_score]
        if s >= _PASS_THRESHOLD
    )

    return {
        "change_score": total,
        "accruals": {"score": acc_score, "raw": acc_raw},
        "revenue_acceleration": {"score": rev_score, "raw": rev_raw},
        "fcf_yield": {"score": fcf_score, "raw": fcf_raw},
        "roe_trend": {"score": roe_score, "raw": roe_raw},
        "passed_count": passed,
        "quality_pass": passed >= 3,
    }
