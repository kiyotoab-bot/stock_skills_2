"""What-If portfolio simulation (KIK-376).

Temporarily adds proposed stocks to the portfolio and compares
before/after metrics (snapshot, concentration, forecast, health).
Uses a temp CSV approach to leverage existing csv_path-based functions.
"""

import os
import tempfile

from src.core.portfolio_manager import (
    get_fx_rates,
    get_snapshot,
    get_structure_analysis,
    load_portfolio,
    merge_positions,
    save_portfolio,
)
from src.core.return_estimate import estimate_portfolio_return
from src.core.ticker_utils import infer_currency


def parse_add_arg(add_str: str) -> list[dict]:
    """Parse --add argument into a list of proposed positions.

    Format: "SYMBOL:SHARES:PRICE,SYMBOL:SHARES:PRICE,..."

    Parameters
    ----------
    add_str : str
        Comma-separated entries of "SYMBOL:SHARES:PRICE".

    Returns
    -------
    list[dict]
        Each dict has: symbol, shares, cost_price, cost_currency.

    Raises
    ------
    ValueError
        If format is invalid.
    """
    if not add_str or not add_str.strip():
        raise ValueError("--add の値が空です。形式: SYMBOL:SHARES:PRICE")

    results: list[dict] = []
    entries = [e.strip() for e in add_str.split(",") if e.strip()]

    for entry in entries:
        parts = entry.split(":")
        if len(parts) != 3:
            raise ValueError(
                f"不正な形式: '{entry}' — SYMBOL:SHARES:PRICE の形式で指定してください"
            )

        symbol = parts[0].strip()
        if not symbol:
            raise ValueError(f"銘柄シンボルが空です: '{entry}'")

        try:
            shares = int(parts[1].strip())
        except ValueError:
            raise ValueError(
                f"株数が不正です: '{parts[1].strip()}' in '{entry}'"
            )
        if shares <= 0:
            raise ValueError(
                f"株数は正の整数を指定してください: {shares} in '{entry}'"
            )

        try:
            price = float(parts[2].strip())
        except ValueError:
            raise ValueError(
                f"価格が不正です: '{parts[2].strip()}' in '{entry}'"
            )
        if price <= 0:
            raise ValueError(
                f"価格は正の数を指定してください: {price} in '{entry}'"
            )

        cost_currency = infer_currency(symbol)

        results.append({
            "symbol": symbol,
            "shares": shares,
            "cost_price": price,
            "cost_currency": cost_currency,
        })

    return results


def _extract_metrics(snapshot: dict, structure: dict, forecast: dict) -> dict:
    """Extract flat comparison metrics from analysis results."""
    portfolio_return = forecast.get("portfolio", {})

    return {
        "total_value_jpy": snapshot.get("total_value_jpy", 0),
        "total_cost_jpy": snapshot.get("total_cost_jpy", 0),
        "total_pnl_jpy": snapshot.get("total_pnl_jpy", 0),
        "total_pnl_pct": snapshot.get("total_pnl_pct", 0),
        "sector_hhi": structure.get("sector_hhi", 0),
        "region_hhi": structure.get("region_hhi", 0),
        "currency_hhi": structure.get("currency_hhi", 0),
        "concentration_multiplier": structure.get(
            "concentration_multiplier", 1.0
        ),
        "risk_level": structure.get("risk_level", "分散"),
        "forecast_optimistic": portfolio_return.get("optimistic"),
        "forecast_base": portfolio_return.get("base"),
        "forecast_pessimistic": portfolio_return.get("pessimistic"),
    }


def _compute_required_cash(
    proposed: list[dict], fx_rates: dict
) -> float:
    """Compute total required cash in JPY for proposed positions."""
    total = 0.0
    for prop in proposed:
        currency = prop.get("cost_currency", "JPY")
        fx_rate = fx_rates.get(currency, 1.0)
        total += prop["shares"] * prop["cost_price"] * fx_rate
    return total


def _compute_judgment(
    before: dict, after: dict, proposed_health: list[dict]
) -> dict:
    """Compute recommendation judgment based on 3 axes.

    Axes:
    1. Diversification: HHI change (sector_hhi as primary)
    2. Return: forecast_base change
    3. Health: exit signals in proposed stocks

    Returns
    -------
    dict
        {"recommendation": str, "reasons": list[str]}
        recommendation is one of: "recommend", "caution", "not_recommended"
    """
    reasons: list[str] = []

    # 1. Diversification check
    before_hhi = max(
        before.get("sector_hhi", 0),
        before.get("region_hhi", 0),
    )
    after_hhi = max(
        after.get("sector_hhi", 0),
        after.get("region_hhi", 0),
    )
    hhi_improved = after_hhi < before_hhi
    hhi_worsened = after_hhi > before_hhi + 0.05  # threshold

    if hhi_improved:
        reasons.append(
            f"分散度改善: HHI {before_hhi:.2f} → {after_hhi:.2f}"
        )
    elif hhi_worsened:
        reasons.append(
            f"集中度悪化: HHI {before_hhi:.2f} → {after_hhi:.2f}"
        )

    # 2. Return check
    before_ret = before.get("forecast_base")
    after_ret = after.get("forecast_base")
    ret_improved = False
    ret_worsened = False

    if before_ret is not None and after_ret is not None:
        diff_pp = (after_ret - before_ret) * 100  # percentage points
        if diff_pp > 0.1:
            ret_improved = True
            reasons.append(f"期待リターン改善: {diff_pp:+.1f}pp")
        elif diff_pp < -0.5:
            ret_worsened = True
            reasons.append(f"期待リターン悪化: {diff_pp:+.1f}pp")

    # 3. Health check for proposed stocks
    has_exit = False
    has_warning = False

    for ph in proposed_health:
        alert = ph.get("alert", {})
        level = alert.get("level", "none")
        symbol = ph.get("symbol", "")
        if level == "exit":
            has_exit = True
            reasons.append(f"撤退シグナル: {symbol}")
        elif level in ("caution", "early_warning"):
            has_warning = True
            alert_label = alert.get("label", level)
            reasons.append(f"注意シグナル: {symbol} ({alert_label})")

    # Judgment logic
    if has_exit or (hhi_worsened and ret_worsened):
        recommendation = "not_recommended"
    elif hhi_improved and ret_improved and not has_exit:
        recommendation = "recommend"
    elif has_warning or hhi_worsened or ret_worsened:
        recommendation = "caution"
    elif hhi_improved or ret_improved:
        recommendation = "recommend"
    else:
        recommendation = "caution"

    if not reasons:
        reasons.append("大きな変化なし")

    return {
        "recommendation": recommendation,
        "reasons": reasons,
    }


def run_what_if_simulation(
    csv_path: str,
    proposed: list[dict],
    client,
) -> dict:
    """Run What-If simulation comparing before/after portfolio metrics.

    Uses a temp CSV file to leverage existing csv_path-based analysis
    functions without modifying the original portfolio.

    Parameters
    ----------
    csv_path : str
        Path to the current portfolio CSV.
    proposed : list[dict]
        Proposed positions (from parse_add_arg).
    client
        yahoo_client module.

    Returns
    -------
    dict
        Simulation result with before/after comparison.
    """
    # 1. Load current portfolio
    current = load_portfolio(csv_path)

    # 2. Before analysis (uses cache for subsequent calls)
    before_snapshot = get_snapshot(csv_path, client)
    before_structure = get_structure_analysis(csv_path, client)
    before_forecast = estimate_portfolio_return(csv_path, client)
    before_metrics = _extract_metrics(
        before_snapshot, before_structure, before_forecast
    )

    # 3. Merge positions
    merged = merge_positions(current, proposed)

    # 4. Write to temp CSV
    temp_fd, temp_path = tempfile.mkstemp(suffix=".csv", prefix="whatif_")
    os.close(temp_fd)

    try:
        save_portfolio(merged, temp_path)

        # 5. After analysis (new stocks will need API calls,
        #    existing stocks hit yahoo_client's 24h cache)
        after_snapshot = get_snapshot(temp_path, client)
        after_structure = get_structure_analysis(temp_path, client)
        after_forecast = estimate_portfolio_return(temp_path, client)
        after_metrics = _extract_metrics(
            after_snapshot, after_structure, after_forecast
        )

        # 6. Health check on proposed stocks only
        proposed_health: list[dict] = []
        try:
            from src.core.health_check import run_health_check

            health_data = run_health_check(temp_path, client)
            proposed_symbols = {
                p["symbol"].upper() for p in proposed
            }
            for pos in health_data.get("positions", []):
                if pos.get("symbol", "").upper() in proposed_symbols:
                    proposed_health.append(pos)
        except ImportError:
            pass

        # 7. FX rates and required cash
        fx_rates = before_snapshot.get("fx_rates", {"JPY": 1.0})
        required_cash = _compute_required_cash(proposed, fx_rates)

        # 8. Judgment
        judgment = _compute_judgment(
            before_metrics, after_metrics, proposed_health
        )

    finally:
        # 9. Cleanup temp CSV
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return {
        "proposed": proposed,
        "before": before_metrics,
        "after": after_metrics,
        "proposed_health": proposed_health,
        "required_cash_jpy": required_cash,
        "judgment": judgment,
    }
