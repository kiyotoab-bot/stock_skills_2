"""Rule-based portfolio recommendation engine (KIK-352).

Generates actionable recommendations from:
  - HHI concentration analysis
  - Correlation analysis
  - VaR analysis
  - Scenario stress test results
  - Shock sensitivity analysis
"""

from typing import Optional

# ---------------------------------------------------------------------------
# Thresholds for recommendation rules
# ---------------------------------------------------------------------------

HHI_DANGER = 0.50  # HHI above this is "danger"
HHI_MODERATE = 0.25  # HHI above this is "moderate concern"
CORR_VERY_HIGH = 0.85  # Very strong correlation
CORR_HIGH = 0.70  # High correlation
VAR_SEVERE = -0.15  # Monthly VaR(95%) severe threshold
VAR_WARNING = -0.10  # Monthly VaR(95%) warning threshold
VOLATILITY_HIGH = 0.30  # Annualized portfolio volatility threshold
STRESS_SEVERE_IMPACT = -0.30  # Individual stock stress impact threshold


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_recommendations(
    concentration: dict,
    correlation_pairs: Optional[list[dict]] = None,
    var_result: Optional[dict] = None,
    scenario_result: Optional[dict] = None,
    sensitivities: Optional[list[dict]] = None,
) -> list[dict]:
    """Generate rule-based portfolio recommendations.

    Parameters
    ----------
    concentration : dict
        Output of ``analyze_concentration()``.
    correlation_pairs : list[dict] or None
        Output of ``find_high_correlation_pairs()``.
    var_result : dict or None
        Output of ``compute_var()``.
    scenario_result : dict or None
        Output of ``analyze_portfolio_scenario()``.
    sensitivities : list[dict] or None
        Per-stock sensitivity analysis results from ``analyze_stock_sensitivity()``.

    Returns
    -------
    list[dict]
        Each recommendation: {
            "priority": str ("high", "medium", "low"),
            "category": str,
            "title": str,
            "detail": str,
            "action": str,
        }
        Sorted by priority (high first).
    """
    recs: list[dict] = []

    recs.extend(_check_concentration(concentration))

    if correlation_pairs:
        recs.extend(_check_correlations(correlation_pairs))

    if var_result:
        recs.extend(_check_var(var_result))

    if scenario_result is not None:
        recs.extend(_check_stress(scenario_result))

    if sensitivities:
        recs.extend(_check_sensitivities(sensitivities))

    # Sort by priority
    priority_order = {"high": 0, "medium": 1, "low": 2}
    recs.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 3))

    return recs


# ---------------------------------------------------------------------------
# Concentration checks
# ---------------------------------------------------------------------------

_ALL_SECTORS = [
    "Technology", "Healthcare", "Financial Services",
    "Consumer Defensive", "Industrials", "Energy",
    "Basic Materials", "Utilities", "Real Estate",
    "Communication Services", "Consumer Cyclical",
]


def _suggest_diversification_sector(sector_breakdown: dict) -> str:
    """Suggest sectors not present in the portfolio."""
    missing = [s for s in _ALL_SECTORS if s not in sector_breakdown]
    if missing:
        return ", ".join(missing[:3])
    return "他セクター"


def _check_concentration(concentration: dict) -> list[dict]:
    """Generate recommendations from concentration analysis."""
    recs: list[dict] = []

    # Sector concentration
    sector_hhi = concentration.get("sector_hhi", 0)
    sector_breakdown = concentration.get("sector_breakdown", {})
    if sector_hhi > HHI_DANGER and sector_breakdown:
        top_sector = max(sector_breakdown, key=sector_breakdown.get)
        top_weight = sector_breakdown.get(top_sector, 0)
        suggestion = _suggest_diversification_sector(sector_breakdown)
        recs.append({
            "priority": "high",
            "category": "concentration",
            "title": f"セクター集中リスク: {top_sector} {top_weight*100:.0f}%",
            "detail": (
                f"セクターHHI={sector_hhi:.4f}（危険水準）。"
                f"{top_sector}への依存度が高すぎます。"
            ),
            "action": f"異なるセクター（例: {suggestion}）の銘柄追加を検討",
        })
    elif sector_hhi > HHI_MODERATE and sector_breakdown:
        top_sector = max(sector_breakdown, key=sector_breakdown.get)
        recs.append({
            "priority": "medium",
            "category": "concentration",
            "title": f"セクターがやや集中: {top_sector}",
            "detail": f"セクターHHI={sector_hhi:.4f}。分散は十分ではありません。",
            "action": "セクター分散の改善を検討",
        })

    # Region concentration
    region_hhi = concentration.get("region_hhi", 0)
    region_breakdown = concentration.get("region_breakdown", {})
    if region_hhi > HHI_DANGER and region_breakdown:
        top_region = max(region_breakdown, key=region_breakdown.get)
        top_weight = region_breakdown.get(top_region, 0)
        recs.append({
            "priority": "high",
            "category": "concentration",
            "title": f"地域集中リスク: {top_region} {top_weight*100:.0f}%",
            "detail": (
                f"地域HHI={region_hhi:.4f}（危険水準）。"
                f"{top_region}への依存度が高すぎます。"
            ),
            "action": "他の地域（米国/ASEAN/欧州）の銘柄追加を検討",
        })
    elif region_hhi > HHI_MODERATE:
        recs.append({
            "priority": "low",
            "category": "concentration",
            "title": "地域配分がやや偏り",
            "detail": f"地域HHI={region_hhi:.4f}。",
            "action": "地域分散の改善を検討",
        })

    # Currency concentration
    currency_hhi = concentration.get("currency_hhi", 0)
    currency_breakdown = concentration.get("currency_breakdown", {})
    if currency_hhi > HHI_DANGER and currency_breakdown:
        top_currency = max(currency_breakdown, key=currency_breakdown.get)
        recs.append({
            "priority": "medium",
            "category": "concentration",
            "title": f"通貨集中: {top_currency}",
            "detail": f"通貨HHI={currency_hhi:.4f}。為替リスクが偏っています。",
            "action": "異なる通貨圏の銘柄追加で為替リスクを分散",
        })

    return recs


# ---------------------------------------------------------------------------
# Correlation checks
# ---------------------------------------------------------------------------

def _check_correlations(pairs: list[dict]) -> list[dict]:
    """Generate recommendations from high correlation pairs."""
    recs: list[dict] = []
    for pair_info in pairs:
        pair = pair_info.get("pair", ["?", "?"])
        corr = pair_info.get("correlation", 0)
        if abs(corr) >= CORR_VERY_HIGH:
            recs.append({
                "priority": "high",
                "category": "correlation",
                "title": f"強い連動: {pair[0]} x {pair[1]} (r={corr:.2f})",
                "detail": "両銘柄の価格が非常に強く連動しており、分散効果が限定的です。",
                "action": "片方のポジションを縮小し、非連動セクターへの分散を検討",
            })
        elif abs(corr) >= CORR_HIGH:
            recs.append({
                "priority": "medium",
                "category": "correlation",
                "title": f"高相関ペア: {pair[0]} x {pair[1]} (r={corr:.2f})",
                "detail": "価格連動性が高く、ショック時に同時下落のリスクがあります。",
                "action": "相関の原因を確認し、リスク分散を検討",
            })
    return recs


# ---------------------------------------------------------------------------
# VaR checks
# ---------------------------------------------------------------------------

def _check_var(var_result: dict) -> list[dict]:
    """Generate recommendations from VaR analysis."""
    recs: list[dict] = []
    monthly_var = var_result.get("monthly_var", {})
    var_95 = monthly_var.get(0.95, 0)

    if var_95 < VAR_SEVERE:
        recs.append({
            "priority": "high",
            "category": "var",
            "title": f"月次VaR(95%)が高水準: {var_95*100:.1f}%",
            "detail": "月間で15%超の損失が統計的に5%の確率で発生し得ます。",
            "action": "ポジションサイズの縮小またはヘッジ手段の導入を検討",
        })
    elif var_95 < VAR_WARNING:
        recs.append({
            "priority": "medium",
            "category": "var",
            "title": f"月次VaR(95%): {var_95*100:.1f}%",
            "detail": "月間で10%超の損失が統計的に5%の確率で発生し得ます。",
            "action": "リスク許容度に照らしてポジション見直しを検討",
        })

    portfolio_vol = var_result.get("portfolio_volatility", 0)
    if portfolio_vol > VOLATILITY_HIGH:
        recs.append({
            "priority": "medium",
            "category": "var",
            "title": f"PFボラティリティ: {portfolio_vol*100:.1f}%",
            "detail": "年間ボラティリティが30%を超えています。",
            "action": "低ボラティリティ銘柄やディフェンシブ銘柄の追加を検討",
        })

    return recs


# ---------------------------------------------------------------------------
# Stress test checks
# ---------------------------------------------------------------------------

def _check_stress(scenario_result: dict) -> list[dict]:
    """Generate recommendations from stress test results."""
    recs: list[dict] = []
    judgment = scenario_result.get("judgment", "")
    pf_impact = scenario_result.get("portfolio_impact", 0)

    if judgment == "要対応":
        recs.append({
            "priority": "high",
            "category": "stress",
            "title": f"ストレステスト要対応: PF影響 {pf_impact*100:+.1f}%",
            "detail": (
                f"シナリオ「{scenario_result.get('scenario_name', '不明')}」で"
                f"PF全体が30%超の損失想定。"
            ),
            "action": "ヘッジポジションの構築またはエクスポージャーの削減を検討",
        })

    # Check individual stock impacts
    stock_impacts = scenario_result.get("stock_impacts", [])
    for si in stock_impacts:
        total_impact = si.get("total_impact", 0)
        if total_impact < STRESS_SEVERE_IMPACT:
            sym = si.get("symbol", "?")
            recs.append({
                "priority": "high",
                "category": "stress",
                "title": f"{sym}がシナリオで{total_impact*100:+.1f}%",
                "detail": f"{sym}のストレス時損失が-30%超。",
                "action": (
                    f"{sym}のポジション縮小または"
                    f"プットオプションでのヘッジを検討"
                ),
            })

    return recs


# ---------------------------------------------------------------------------
# Sensitivity checks
# ---------------------------------------------------------------------------

def _check_sensitivities(sensitivities: list[dict]) -> list[dict]:
    """Generate recommendations from sensitivity analysis."""
    recs: list[dict] = []
    for sens in sensitivities:
        integrated = sens.get("integrated", {})
        quadrant = integrated.get("quadrant", {})
        quad_name = quadrant.get("quadrant", "")
        sym = sens.get("symbol", "?")

        if quad_name == "最危険":
            recs.append({
                "priority": "high",
                "category": "sensitivity",
                "title": f"{sym}: ファンダ脆弱+テクニカル過熱",
                "detail": quadrant.get("description", ""),
                "action": f"{sym}の利益確定または縮小を検討",
            })
        elif quad_name == "底抜けリスク":
            recs.append({
                "priority": "medium",
                "category": "sensitivity",
                "title": f"{sym}: 底抜けリスク",
                "detail": quadrant.get("description", ""),
                "action": f"{sym}のポジション見直しを検討（損切りライン設定）",
            })
    return recs
