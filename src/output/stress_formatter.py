"""Output formatters for stress test results (KIK-339/340/341/352)."""

import math
from typing import Optional

from src.output._format_helpers import fmt_pct as _fmt_pct
from src.output._format_helpers import fmt_pct_sign as _fmt_pct_sign
from src.output._format_helpers import fmt_float as _fmt_float
from src.output._format_helpers import fmt_float_sign as _fmt_float_sign
from src.output._format_helpers import hhi_bar as _hhi_bar


def _fmt_currency(value: Optional[float]) -> str:
    """Format a currency value with commas."""
    if value is None:
        return "-"
    if abs(value) >= 1_000_000:
        return f"{value:+,.0f}"
    return f"{value:+,.2f}"


# ---------------------------------------------------------------------------
# 集中度分析レポート
# ---------------------------------------------------------------------------

def format_concentration_report(concentration: dict) -> str:
    """集中度分析のMarkdownレポート。

    Parameters
    ----------
    concentration : dict
        concentration.analyze_concentration() の結果。

    Returns
    -------
    str
        Markdown形式のレポート文字列。
    """
    lines: list[str] = []
    lines.append("### Step 2: 集中度分析")
    lines.append("")

    risk_level = concentration.get("risk_level", "-")
    max_hhi = concentration.get("max_hhi", 0.0)
    max_axis = concentration.get("max_hhi_axis", "-")
    multiplier = concentration.get("concentration_multiplier", 1.0)

    lines.append(f"**総合判定: {risk_level}** (最大HHI: {_fmt_float(max_hhi, 4)} / 軸: {max_axis})")
    lines.append(f"集中度倍率: x{_fmt_float(multiplier, 2)}")
    lines.append("")

    # セクター内訳
    lines.append("#### セクター配分")
    sector_hhi = concentration.get("sector_hhi", 0.0)
    lines.append(f"HHI: {_fmt_float(sector_hhi, 4)} {_hhi_bar(sector_hhi)}")
    lines.append("")
    lines.append("| セクター | 比率 |")
    lines.append("|:---------|-----:|")
    sector_breakdown = concentration.get("sector_breakdown", {})
    for sector, weight in sorted(sector_breakdown.items(), key=lambda x: -x[1]):
        lines.append(f"| {sector} | {_fmt_pct(weight)} |")
    lines.append("")

    # 地域内訳
    lines.append("#### 地域配分")
    region_hhi = concentration.get("region_hhi", 0.0)
    lines.append(f"HHI: {_fmt_float(region_hhi, 4)} {_hhi_bar(region_hhi)}")
    lines.append("")
    lines.append("| 地域 | 比率 |")
    lines.append("|:-----|-----:|")
    region_breakdown = concentration.get("region_breakdown", {})
    for region, weight in sorted(region_breakdown.items(), key=lambda x: -x[1]):
        lines.append(f"| {region} | {_fmt_pct(weight)} |")
    lines.append("")

    # 通貨内訳
    lines.append("#### 通貨配分")
    currency_hhi = concentration.get("currency_hhi", 0.0)
    lines.append(f"HHI: {_fmt_float(currency_hhi, 4)} {_hhi_bar(currency_hhi)}")
    lines.append("")
    lines.append("| 通貨 | 比率 |")
    lines.append("|:-----|-----:|")
    currency_breakdown = concentration.get("currency_breakdown", {})
    for currency, weight in sorted(currency_breakdown.items(), key=lambda x: -x[1]):
        lines.append(f"| {currency} | {_fmt_pct(weight)} |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ショック感応度レポート
# ---------------------------------------------------------------------------

def format_sensitivity_report(sensitivities: list[dict]) -> str:
    """ショック感応度のMarkdown表。

    Parameters
    ----------
    sensitivities : list[dict]
        各銘柄の感応度分析結果。想定キー:
        - "symbol", "name"
        - "fundamental_score", "technical_score"
        - "quadrant" (象限ラベル)
        - "composite_shock"

    Returns
    -------
    str
        Markdown形式の表。
    """
    lines: list[str] = []
    lines.append("### Step 3: ショック感応度")
    lines.append("")

    if not sensitivities:
        lines.append("感応度データがありません。")
        return "\n".join(lines)

    lines.append("| 銘柄 | ファンダ | テクニカル | 象限 | 統合ショック |")
    lines.append("|:-----|-------:|----------:|:-----|----------:|")

    for s in sensitivities:
        symbol = s.get("symbol", "-")
        name = s.get("name", "")
        label = f"{symbol} {name}".strip() if name else symbol
        fund_score = _fmt_float(s.get("fundamental_score"))
        tech_score = _fmt_float(s.get("technical_score"))
        quadrant = s.get("quadrant", "-")
        composite = _fmt_pct_sign(s.get("composite_shock"))
        lines.append(f"| {label} | {fund_score} | {tech_score} | {quadrant} | {composite} |")

    lines.append("")

    # 4象限マトリクス（テキストベース）
    lines.append("#### 4象限マトリクス")
    lines.append("```")
    lines.append("          ファンダ弱              ファンダ強")
    lines.append("        +-----------+-----------+")
    lines.append("テクニカル |  要注意    |  堅実     |")
    lines.append("  強    |  (高リスク) |  (低リスク) |")
    lines.append("        +-----------+-----------+")
    lines.append("テクニカル |  危険     |  回復期待  |")
    lines.append("  弱    |  (最高リスク)|  (中リスク) |")
    lines.append("        +-----------+-----------+")
    lines.append("```")
    lines.append("")

    # 象限別の銘柄リスト
    quadrant_map: dict[str, list[str]] = {}
    for s in sensitivities:
        q = s.get("quadrant", "不明")
        sym = s.get("symbol", "?")
        quadrant_map.setdefault(q, []).append(sym)

    if quadrant_map:
        for q, symbols in quadrant_map.items():
            lines.append(f"- **{q}**: {', '.join(symbols)}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# シナリオ因果連鎖レポート
# ---------------------------------------------------------------------------

def format_scenario_report(scenario_result: dict) -> str:
    """シナリオ分析のMarkdownレポート。

    Parameters
    ----------
    scenario_result : dict
        scenario_analysis.analyze_portfolio_scenario() の結果。

    Returns
    -------
    str
        Markdown形式のレポート文字列。
    """
    lines: list[str] = []

    scenario_name = scenario_result.get("scenario_name", "不明")
    trigger = scenario_result.get("trigger", "不明")
    pf_impact = scenario_result.get("portfolio_impact", 0.0)
    pf_value_change = scenario_result.get("portfolio_value_change", 0.0)
    judgment = scenario_result.get("judgment", "-")

    lines.append(f"### Step 4-5: シナリオ因果連鎖分析 - {scenario_name}")
    lines.append("")
    lines.append(f"**トリガー:** {trigger}")
    lines.append("")

    # 因果連鎖図
    lines.append("#### 因果連鎖")
    lines.append("```")
    chain_summary = scenario_result.get("causal_chain_summary", "")
    if chain_summary:
        lines.append(chain_summary)
    lines.append("```")
    lines.append("")

    # 銘柄別影響テーブル
    stock_impacts = scenario_result.get("stock_impacts", [])
    if stock_impacts:
        lines.append("#### 銘柄別影響")
        lines.append("")
        lines.append("| 銘柄 | 比率 | 直接影響 | 通貨効果 | 合計 | PF寄与 |")
        lines.append("|:-----|-----:|-------:|-------:|-----:|------:|")

        for si in stock_impacts:
            symbol = si.get("symbol", "-")
            name = si.get("name", "")
            label = f"{symbol} {name}".strip() if name else symbol
            weight = _fmt_pct(si.get("weight"))
            direct = _fmt_pct_sign(si.get("direct_impact"))
            currency = _fmt_pct_sign(si.get("currency_impact"))
            total = _fmt_pct_sign(si.get("total_impact"))
            pf_contrib = _fmt_pct_sign(si.get("pf_contribution"))
            lines.append(f"| {label} | {weight} | {direct} | {currency} | {total} | {pf_contrib} |")

        lines.append("")

    # 相殺要因
    offset_factors = scenario_result.get("offset_factors", [])
    if offset_factors:
        lines.append("#### 相殺要因")
        for factor in offset_factors:
            lines.append(f"- {factor}")
        lines.append("")

    # 時間軸
    time_axis = scenario_result.get("time_axis", "")
    if time_axis:
        lines.append(f"**時間軸:** {time_axis}")
        lines.append("")

    # 判定
    if judgment == "要対応":
        judgment_display = "要対応"
    elif judgment == "認識":
        judgment_display = "認識"
    else:
        judgment_display = "継続"

    lines.append(f"### Step 6: 定量結果")
    lines.append("")
    lines.append(f"- **PF影響率:** {_fmt_pct_sign(pf_impact)}")
    lines.append(f"- **評価額変動:** {_fmt_currency(pf_value_change)}")
    lines.append(f"- **判定:** {judgment_display}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 相関分析レポート (KIK-352)
# ---------------------------------------------------------------------------

def format_correlation_report(
    corr_result: dict,
    high_pairs: list[dict],
    factor_results: Optional[list[dict]] = None,
) -> str:
    """相関分析のMarkdownレポート。

    Parameters
    ----------
    corr_result : dict
        compute_correlation_matrix() の結果。
    high_pairs : list[dict]
        find_high_correlation_pairs() の結果。
    factor_results : list[dict] or None
        decompose_factors() の結果。

    Returns
    -------
    str
        Markdown形式のレポート文字列。
    """
    lines: list[str] = []
    lines.append("### 相関分析")
    lines.append("")

    symbols = corr_result.get("symbols", [])
    matrix = corr_result.get("matrix", [])
    n = len(symbols)

    if n < 2:
        lines.append("銘柄が2つ未満のため相関分析をスキップしました。")
        lines.append("")
        return "\n".join(lines)

    # 相関行列テーブル
    lines.append("#### 相関行列")
    lines.append("")
    header = "| |" + "|".join(f" {s} " for s in symbols) + "|"
    lines.append(header)
    sep = "|:-----|" + "|".join("-----:" for _ in symbols) + "|"
    lines.append(sep)
    for i in range(n):
        row_vals = []
        for j in range(n):
            v = matrix[i][j]
            if i == j:
                row_vals.append(" 1.00 ")
            elif isinstance(v, (int, float)) and not math.isnan(v):
                row_vals.append(f" {v:+.2f} ")
            else:
                row_vals.append(" - ")
        lines.append(f"| {symbols[i]} |" + "|".join(row_vals) + "|")
    lines.append("")

    # 高相関ペア
    if high_pairs:
        lines.append("#### 高相関ペア")
        lines.append("")
        lines.append("| ペア | 相関係数 | 判定 |")
        lines.append("|:-----|-------:|:-----|")
        for p in high_pairs:
            pair = p.get("pair", ["?", "?"])
            corr = p.get("correlation", 0)
            label = p.get("label", "-")
            lines.append(f"| {pair[0]} x {pair[1]} | {corr:+.4f} | {label} |")
        lines.append("")
    else:
        lines.append("高相関ペア（|r| >= 0.7）は検出されませんでした。")
        lines.append("")

    # ファクター分解
    if factor_results:
        lines.append("#### ファクター分解")
        lines.append("")
        for fr in factor_results:
            sym = fr.get("symbol", "?")
            r2 = fr.get("r_squared", 0)
            factors = fr.get("factors", [])
            if not factors:
                continue
            lines.append(f"**{sym}** (R²={_fmt_float(r2, 4)})")
            lines.append("")
            lines.append("| ファクター | Beta | 寄与度 |")
            lines.append("|:---------|-----:|------:|")
            for f in factors[:5]:  # top 5
                lines.append(
                    f"| {f['name']} | {_fmt_float_sign(f.get('beta'), 4)} "
                    f"| {_fmt_float(f.get('contribution'), 4)} |"
                )
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# VaRレポート (KIK-352)
# ---------------------------------------------------------------------------

def format_var_report(var_result: dict) -> str:
    """VaR分析のMarkdownレポート。

    Parameters
    ----------
    var_result : dict
        compute_var() の結果。

    Returns
    -------
    str
        Markdown形式のレポート文字列。
    """
    lines: list[str] = []
    lines.append("### リスク指標（過去実績ベース）")
    lines.append("")

    obs = var_result.get("observation_days", 0)
    if obs < 30:
        lines.append("データ不足のためVaR算出をスキップしました。")
        lines.append("")
        return "\n".join(lines)

    daily_var = var_result.get("daily_var", {})
    monthly_var = var_result.get("monthly_var", {})
    daily_var_amount = var_result.get("daily_var_amount", {})
    monthly_var_amount = var_result.get("monthly_var_amount", {})
    portfolio_vol = var_result.get("portfolio_volatility", 0)

    lines.append(f"観測期間: {obs}営業日")
    lines.append(f"PFボラティリティ（年率）: {_fmt_pct(portfolio_vol)}")
    lines.append("")

    lines.append("| 指標 | 損失率 | 損失額 |")
    lines.append("|:-----|------:|------:|")

    for cl in [0.95, 0.99]:
        cl_label = f"{int(cl*100)}%"

        d_var = daily_var.get(cl)
        d_amt = daily_var_amount.get(cl)
        d_var_str = _fmt_pct_sign(d_var) if d_var is not None else "-"
        d_amt_str = _fmt_currency(d_amt) if d_amt is not None else "-"
        lines.append(f"| 日次VaR ({cl_label}) | {d_var_str} | {d_amt_str} |")

        m_var = monthly_var.get(cl)
        m_amt = monthly_var_amount.get(cl)
        m_var_str = _fmt_pct_sign(m_var) if m_var is not None else "-"
        m_amt_str = _fmt_currency(m_amt) if m_amt is not None else "-"
        lines.append(f"| 月次VaR ({cl_label}) | {m_var_str} | {m_amt_str} |")

    lines.append("")
    lines.append(
        "*VaRは通常変動の上限であり、テールリスク（トリプル安等）は"
        "シナリオ分析でカバー*"
    )
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 推奨アクションレポート (KIK-352)
# ---------------------------------------------------------------------------

def format_recommendations_report(recommendations: list[dict]) -> str:
    """推奨アクションのMarkdownレポート。

    Parameters
    ----------
    recommendations : list[dict]
        generate_recommendations() の結果。

    Returns
    -------
    str
        Markdown形式のレポート文字列。
    """
    lines: list[str] = []
    lines.append("### 推奨アクション（自動生成）")
    lines.append("")

    if not recommendations:
        lines.append("特筆すべき推奨アクションはありません。")
        lines.append("")
        return "\n".join(lines)

    _PRIORITY_EMOJI = {"high": "!!!", "medium": "!!", "low": "!"}
    _CATEGORY_LABELS = {
        "concentration": "集中度",
        "correlation": "相関",
        "var": "VaR",
        "stress": "ストレス",
        "sensitivity": "感応度",
    }

    for i, rec in enumerate(recommendations, 1):
        priority = rec.get("priority", "low")
        category = _CATEGORY_LABELS.get(rec.get("category", ""), rec.get("category", ""))
        title = rec.get("title", "")
        detail = rec.get("detail", "")
        action = rec.get("action", "")
        priority_mark = _PRIORITY_EMOJI.get(priority, "!")

        lines.append(f"**{i}. [{priority_mark}] [{category}] {title}**")
        if detail:
            lines.append(f"   {detail}")
        if action:
            lines.append(f"   -> {action}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 全体統合レポート
# ---------------------------------------------------------------------------

def format_full_stress_report(
    portfolio_summary: dict,
    concentration: dict,
    sensitivities: list[dict],
    scenario_result: dict,
    *,
    correlation: Optional[dict] = None,
    high_correlation_pairs: Optional[list[dict]] = None,
    factor_decomposition: Optional[list[dict]] = None,
    var_result: Optional[dict] = None,
    recommendations: Optional[list[dict]] = None,
) -> str:
    """ストレステスト全体のMarkdownレポート。

    Step 1: PF概要
    Step 2: 集中度分析
    Step 3: ショック感応度
    Step 4-5: シナリオ因果連鎖
    Step 6: 定量結果
    Step 6b: 相関分析 (KIK-352)
    Step 6c: VaR (KIK-352)
    Step 7: 過去事例（Claudeが後から追加）
    Step 8: 総合判定
    Step 8b: 推奨アクション (KIK-352)

    Parameters
    ----------
    portfolio_summary : dict
        PFの概要情報。想定キー:
        - "total_value": float (PF総額)
        - "stock_count": int (銘柄数)
        - "stocks": list[dict] (各銘柄のsymbol, name, weight, price等)
    concentration : dict
        concentration.analyze_concentration() の結果
    sensitivities : list[dict]
        各銘柄の感応度分析結果
    scenario_result : dict
        scenario_analysis.analyze_portfolio_scenario() の結果
    correlation : dict or None
        compute_correlation_matrix() の結果 (KIK-352)
    high_correlation_pairs : list[dict] or None
        find_high_correlation_pairs() の結果 (KIK-352)
    factor_decomposition : list[dict] or None
        decompose_factors() の結果 (KIK-352)
    var_result : dict or None
        compute_var() の結果 (KIK-352)
    recommendations : list[dict] or None
        generate_recommendations() の結果 (KIK-352)

    Returns
    -------
    str
        Markdown形式の全体レポート。
    """
    lines: list[str] = []

    # ===== Header =====
    scenario_name = scenario_result.get("scenario_name", "不明")
    lines.append(f"# ストレステストレポート: {scenario_name}")
    lines.append("")

    # ===== Step 1: PF概要 =====
    lines.append("### Step 1: ポートフォリオ概要")
    lines.append("")

    total_value = portfolio_summary.get("total_value")
    stock_count = portfolio_summary.get("stock_count", 0)
    if total_value is not None:
        lines.append(f"- **PF総額:** {total_value:,.0f}")
    lines.append(f"- **銘柄数:** {stock_count}")
    lines.append("")

    stocks = portfolio_summary.get("stocks", [])
    if stocks:
        lines.append("| 銘柄 | 比率 | 株価 | セクター |")
        lines.append("|:-----|-----:|-----:|:---------|")
        for s in stocks:
            symbol = s.get("symbol", "-")
            name = s.get("name", "")
            label = f"{symbol} {name}".strip() if name else symbol
            weight = _fmt_pct(s.get("weight"))
            price = _fmt_float(s.get("price"), decimals=0) if s.get("price") is not None else "-"
            sector = s.get("sector") or "-"
            lines.append(f"| {label} | {weight} | {price} | {sector} |")
        lines.append("")

    # ===== Step 2: 集中度分析 =====
    lines.append(format_concentration_report(concentration))

    # ===== Step 3: ショック感応度 =====
    lines.append(format_sensitivity_report(sensitivities))

    # ===== Step 4-5-6: シナリオ分析 =====
    lines.append(format_scenario_report(scenario_result))

    # ===== Step 6b: 相関分析 (KIK-352) =====
    if correlation is not None:
        lines.append(format_correlation_report(
            correlation,
            high_correlation_pairs or [],
            factor_decomposition,
        ))

    # ===== Step 6c: VaR (KIK-352) =====
    if var_result is not None:
        lines.append(format_var_report(var_result))

    # ===== Step 7: 過去事例 =====
    lines.append("### Step 7: 過去事例")
    lines.append("")
    lines.append("(類似シナリオの過去事例は別途Claudeが補足)")
    lines.append("")

    # ===== Step 8: 総合判定 =====
    lines.append("### Step 8: 総合判定")
    lines.append("")

    # 総合判定の集約
    risk_level = concentration.get("risk_level", "-")
    pf_impact = scenario_result.get("portfolio_impact", 0.0)
    judgment = scenario_result.get("judgment", "-")

    lines.append("| 項目 | 結果 |")
    lines.append("|:-----|:-----|")
    lines.append(f"| 集中度リスク | {risk_level} |")
    lines.append(f"| シナリオ影響 | {_fmt_pct_sign(pf_impact)} |")
    lines.append(f"| 判定 | {judgment} |")

    # VaR summary in judgment table
    if var_result and var_result.get("daily_var"):
        daily_95 = var_result.get("daily_var", {}).get(0.95)
        if daily_95 is not None:
            lines.append(f"| 日次VaR(95%) | {_fmt_pct_sign(daily_95)} |")

    lines.append("")

    # ===== Step 8b: 推奨アクション (KIK-352) =====
    if recommendations:
        lines.append(format_recommendations_report(recommendations))
    else:
        # Fallback to old-style recommendations
        lines.append("#### 推奨アクション")
        if judgment == "要対応":
            lines.append("- PF影響が-30%超。リスク対応が必要です。")
            lines.append("- ヘッジポジションの構築を検討してください。")
            lines.append("- 集中しているセクター/地域の比率を見直してください。")
        elif judgment == "認識":
            lines.append("- PF影響が-15%超。リスクを認識の上、モニタリングを継続してください。")
            lines.append("- トリガーイベントの兆候に注意してください。")
            if risk_level == "危険な集中" or risk_level == "やや集中":
                lines.append(f"- 集中度が「{risk_level}」です。分散を検討してください。")
        else:
            lines.append("- 現時点では大きなリスクは検出されていません。")
            lines.append("- 定期的なモニタリングを継続してください。")
        lines.append("")

    return "\n".join(lines)
