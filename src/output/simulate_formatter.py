"""Simulation and what-if output formatters (KIK-447, split from portfolio_formatter.py)."""

from src.output._format_helpers import fmt_pct_sign as _fmt_pct_sign
from src.output._format_helpers import fmt_float as _fmt_float
from src.output._portfolio_utils import _fmt_jpy, _fmt_currency_value, _fmt_k


_JUDGMENT_EMOJI = {
    "recommend": "\u2705",       # ✅
    "caution": "\u26a0\ufe0f",   # ⚠️
    "not_recommended": "\U0001f6a8",  # 🚨
}

_JUDGMENT_LABEL = {
    "recommend": "この追加は推奨",
    "caution": "注意して検討",
    "not_recommended": "この追加は非推奨",
}


def format_simulation(result) -> str:
    """Format compound interest simulation results as Markdown.

    Parameters
    ----------
    result : SimulationResult or dict
        Output from simulator.simulate_portfolio().

    Returns
    -------
    str
        Markdown-formatted simulation report.
    """
    # Support both SimulationResult and dict
    if hasattr(result, "to_dict"):
        d = result.to_dict()
    else:
        d = result

    scenarios = d.get("scenarios", {})
    years = d.get("years", 0)
    monthly_add = d.get("monthly_add", 0.0)
    reinvest_dividends = d.get("reinvest_dividends", True)
    target = d.get("target")

    lines: list[str] = []

    # Empty scenarios
    if not scenarios:
        lines.append("## \u8907\u5229\u30b7\u30df\u30e5\u30ec\u30fc\u30b7\u30e7\u30f3")
        lines.append("")
        lines.append(
            "\u63a8\u5b9a\u30ea\u30bf\u30fc\u30f3\u304c\u53d6\u5f97\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002"
            "\u5148\u306b /stock-portfolio forecast \u3092\u5b9f\u884c\u3057\u3066\u304f\u3060\u3055\u3044\u3002"
        )
        return "\n".join(lines)

    # Header
    if monthly_add > 0:
        add_str = f"\u6708{monthly_add:,.0f}\u5186\u7a4d\u7acb"
    else:
        add_str = "\u7a4d\u7acb\u306a\u3057"
    lines.append(f"## {years}\u5e74\u30b7\u30df\u30e5\u30ec\u30fc\u30b7\u30e7\u30f3\uff08{add_str}\uff09")
    lines.append("")

    # Base scenario table
    base_snapshots = scenarios.get("base", [])
    if base_snapshots:
        base_return = d.get("portfolio_return_base")
        if base_return is not None:
            ret_str = f"{base_return * 100:+.2f}%"
        else:
            ret_str = "-"
        lines.append(f"### \u30d9\u30fc\u30b9\u30b7\u30ca\u30ea\u30aa\uff08\u5e74\u5229 {ret_str}\uff09")
        lines.append("")
        lines.append("| \u5e74 | \u8a55\u4fa1\u984d | \u7d2f\u8a08\u6295\u5165 | \u904b\u7528\u76ca | \u914d\u5f53\u7d2f\u8a08 |")
        lines.append("|----|--------|----------|--------|----------|")

        for snap in base_snapshots:
            yr = snap.get("year", 0) if isinstance(snap, dict) else snap.year
            value = snap.get("value", 0) if isinstance(snap, dict) else snap.value
            cum_input = snap.get("cumulative_input", 0) if isinstance(snap, dict) else snap.cumulative_input
            cap_gain = snap.get("capital_gain", 0) if isinstance(snap, dict) else snap.capital_gain
            cum_div = snap.get("cumulative_dividends", 0) if isinstance(snap, dict) else snap.cumulative_dividends

            if yr == 0:
                lines.append(
                    f"| {yr} | {_fmt_k(value)} | {_fmt_k(cum_input)} | - | - |"
                )
            else:
                lines.append(
                    f"| {yr} | {_fmt_k(value)} | {_fmt_k(cum_input)} "
                    f"| {_fmt_k(cap_gain)} | {_fmt_k(cum_div)} |"
                )

        lines.append("")

    # Scenario comparison (final year)
    scenario_labels = {
        "optimistic": "\u697d\u89b3",
        "base": "\u30d9\u30fc\u30b9",
        "pessimistic": "\u60b2\u89b3",
    }

    has_comparison = len(scenarios) > 1 or (len(scenarios) == 1 and "base" in scenarios)
    if has_comparison:
        lines.append(
            "### \u30b7\u30ca\u30ea\u30aa\u6bd4\u8f03\uff08\u6700\u7d42\u5e74\uff09"
        )
        lines.append("")
        lines.append("| \u30b7\u30ca\u30ea\u30aa | \u6700\u7d42\u8a55\u4fa1\u984d | \u904b\u7528\u76ca |")
        lines.append("|:---------|----------:|-------:|")

        for key in ["optimistic", "base", "pessimistic"]:
            snaps = scenarios.get(key)
            if not snaps:
                continue
            last = snaps[-1]
            value = last.get("value", 0) if isinstance(last, dict) else last.value
            cap_gain = last.get("capital_gain", 0) if isinstance(last, dict) else last.capital_gain
            label = scenario_labels.get(key, key)
            lines.append(
                f"| {label} | {_fmt_k(value)} | {_fmt_k(cap_gain)} |"
            )

        lines.append("")

    # Target analysis
    if target is not None:
        lines.append("### \u76ee\u6a19\u9054\u6210\u5206\u6790")
        lines.append("")
        lines.append(f"- \u76ee\u6a19\u984d: {_fmt_k(target)}")

        target_year_base = d.get("target_year_base")
        target_year_opt = d.get("target_year_optimistic")
        target_year_pess = d.get("target_year_pessimistic")

        if target_year_base is not None:
            lines.append(
                f"- \u30d9\u30fc\u30b9\u30b7\u30ca\u30ea\u30aa: "
                f"**{target_year_base:.1f}\u5e74\u3067\u9054\u6210\u898b\u8fbc\u307f**"
            )
        else:
            lines.append(
                "- \u30d9\u30fc\u30b9\u30b7\u30ca\u30ea\u30aa: \u671f\u9593\u5185\u672a\u9054"
            )

        if target_year_opt is not None:
            lines.append(
                f"- \u697d\u89b3\u30b7\u30ca\u30ea\u30aa: "
                f"{target_year_opt:.1f}\u5e74\u3067\u9054\u6210\u898b\u8fbc\u307f"
            )
        elif "optimistic" in scenarios:
            lines.append(
                "- \u697d\u89b3\u30b7\u30ca\u30ea\u30aa: \u671f\u9593\u5185\u672a\u9054"
            )

        if target_year_pess is not None:
            lines.append(
                f"- \u60b2\u89b3\u30b7\u30ca\u30ea\u30aa: "
                f"{target_year_pess:.1f}\u5e74\u3067\u9054\u6210\u898b\u8fbc\u307f"
            )
        elif "pessimistic" in scenarios:
            lines.append(
                "- \u60b2\u89b3\u30b7\u30ca\u30ea\u30aa: \u671f\u9593\u5185\u672a\u9054"
            )

        required_monthly = d.get("required_monthly")
        if required_monthly is not None and required_monthly > 0:
            lines.append("")
            lines.append(
                f"- \u76ee\u6a19\u9054\u6210\u306b\u5fc5\u8981\u306a\u6708\u984d\u7a4d\u7acb: "
                f"\u00a5{required_monthly:,.0f}"
            )

        lines.append("")

    # Dividend reinvestment effect
    dividend_effect = d.get("dividend_effect", 0)
    dividend_effect_pct = d.get("dividend_effect_pct", 0)

    lines.append(
        "### \u914d\u5f53\u518d\u6295\u8cc7\u306e\u52b9\u679c"
    )
    lines.append("")

    if not reinvest_dividends:
        lines.append("- \u914d\u5f53\u518d\u6295\u8cc7: OFF")
    else:
        lines.append(
            f"- \u914d\u5f53\u518d\u6295\u8cc7\u306b\u3088\u308b\u8907\u5229\u52b9\u679c: "
            f"+{_fmt_k(dividend_effect)}"
        )
        lines.append(
            f"- \u914d\u5f53\u306a\u3057\u6bd4: "
            f"+{dividend_effect_pct * 100:.1f}%"
        )

    lines.append("")

    return "\n".join(lines)


def format_what_if(result: dict) -> str:
    """Format What-If simulation result as Markdown.

    Parameters
    ----------
    result : dict
        Output from portfolio_simulation.run_what_if_simulation().

    Returns
    -------
    str
        Markdown-formatted What-If report.
    """
    lines: list[str] = []

    proposed = result.get("proposed", [])
    before = result.get("before", {})
    after = result.get("after", {})
    proposed_health = result.get("proposed_health", [])
    required_cash = result.get("required_cash_jpy", 0)
    judgment = result.get("judgment", {})

    lines.append("## What-If \u30b7\u30df\u30e5\u30ec\u30fc\u30b7\u30e7\u30f3")
    lines.append("")

    # --- Proposed stocks ---
    lines.append("### \u8ffd\u52a0\u9298\u67c4")
    lines.append("")
    lines.append(
        "| \u9298\u67c4 | \u682a\u6570 | \u5358\u4fa1 | \u901a\u8ca8 "
        "| \u91d1\u984d |"
    )
    lines.append("|:-----|-----:|------:|:-----|------:|")

    for prop in proposed:
        symbol = prop.get("symbol", "-")
        shares = prop.get("shares", 0)
        price = prop.get("cost_price", 0)
        currency = prop.get("cost_currency", "JPY")
        amount = shares * price
        price_str = _fmt_currency_value(price, currency)
        amount_str = _fmt_currency_value(amount, currency)
        lines.append(
            f"| {symbol} | {shares:,} | {price_str} "
            f"| {currency} | {amount_str} |"
        )

    lines.append("")
    lines.append(
        f"\u5fc5\u8981\u8cc7\u91d1\u5408\u8a08: {_fmt_jpy(required_cash)}"
    )
    lines.append("")

    # --- Portfolio change comparison ---
    lines.append("### \u30dd\u30fc\u30c8\u30d5\u30a9\u30ea\u30aa\u5909\u5316")
    lines.append("")
    lines.append(
        "| \u6307\u6a19 | \u73fe\u5728 | \u8ffd\u52a0\u5f8c | \u5909\u5316 |"
    )
    lines.append("|:-----|------:|------:|:------|")

    # Total value
    bv = before.get("total_value_jpy", 0)
    av = after.get("total_value_jpy", 0)
    if bv > 0:
        change_pct = (av - bv) / bv
        change_str = _fmt_pct_sign(change_pct)
    else:
        change_str = "-"
    lines.append(
        f"| \u7dcf\u8a55\u4fa1\u984d | {_fmt_jpy(bv)} "
        f"| {_fmt_jpy(av)} | {change_str} |"
    )

    # Sector HHI
    b_shhi = before.get("sector_hhi", 0)
    a_shhi = after.get("sector_hhi", 0)
    hhi_indicator = (
        "\u2705 \u6539\u5584" if a_shhi < b_shhi
        else "\u26a0\ufe0f \u60aa\u5316" if a_shhi > b_shhi
        else "\u2194\ufe0f \u5909\u5316\u306a\u3057"
    )
    lines.append(
        f"| \u30bb\u30af\u30bf\u30fcHHI | {_fmt_float(b_shhi, 2)} "
        f"| {_fmt_float(a_shhi, 2)} | {hhi_indicator} |"
    )

    # Region HHI
    b_rhhi = before.get("region_hhi", 0)
    a_rhhi = after.get("region_hhi", 0)
    rhhi_indicator = (
        "\u2705 \u6539\u5584" if a_rhhi < b_rhhi
        else "\u26a0\ufe0f \u60aa\u5316" if a_rhhi > b_rhhi
        else "\u2194\ufe0f \u5909\u5316\u306a\u3057"
    )
    lines.append(
        f"| \u5730\u57dfHHI | {_fmt_float(b_rhhi, 2)} "
        f"| {_fmt_float(a_rhhi, 2)} | {rhhi_indicator} |"
    )

    # Forecast base return
    b_ret = before.get("forecast_base")
    a_ret = after.get("forecast_base")
    if b_ret is not None and a_ret is not None:
        diff_pp = (a_ret - b_ret) * 100
        ret_indicator = (
            f"\u2705 +{diff_pp:.1f}pp" if diff_pp > 0
            else f"\u26a0\ufe0f {diff_pp:.1f}pp" if diff_pp < 0
            else "\u2194\ufe0f 0pp"
        )
        lines.append(
            f"| \u671f\u5f85\u30ea\u30bf\u30fc\u30f3(\u30d9\u30fc\u30b9) "
            f"| {_fmt_pct_sign(b_ret)} "
            f"| {_fmt_pct_sign(a_ret)} | {ret_indicator} |"
        )
    lines.append("")

    # --- Proposed stock health ---
    if proposed_health:
        lines.append(
            "### \u63d0\u6848\u9298\u67c4\u30d8\u30eb\u30b9\u30c1\u30a7\u30c3\u30af"
        )
        lines.append("")
        for ph in proposed_health:
            symbol = ph.get("symbol", "-")
            alert = ph.get("alert", {})
            level = alert.get("level", "none")
            label = alert.get("label", "\u306a\u3057")
            if level == "none":
                lines.append(f"\u2705 {symbol}: OK")
            elif level == "early_warning":
                lines.append(f"\u26a1 {symbol}: {label}")
            elif level == "caution":
                lines.append(f"\u26a0\ufe0f {symbol}: {label}")
            elif level == "exit":
                lines.append(f"\U0001f6a8 {symbol}: {label}")
        lines.append("")

    # --- Judgment ---
    lines.append("### \u7dcf\u5408\u5224\u5b9a")
    lines.append("")
    rec = judgment.get("recommendation", "caution")
    emoji = _JUDGMENT_EMOJI.get(rec, "")
    label = _JUDGMENT_LABEL.get(rec, rec)
    lines.append(f"{emoji} **{label}**")
    for reason in judgment.get("reasons", []):
        lines.append(f"- {reason}")
    lines.append("")

    return "\n".join(lines)
