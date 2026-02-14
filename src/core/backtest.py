"""Backtest engine -- verify returns of previously screened stocks."""

from datetime import date, timedelta
from statistics import median

from src.data.history_store import load_history


def _get_benchmark_return(yahoo_client_module, symbol: str, start_date: str) -> float | None:
    """Calculate benchmark return from start_date to today.

    Uses get_price_history to fetch historical prices, then computes
    the return between the closest available date to start_date and
    the most recent date.

    Returns None if data is unavailable.
    """
    df = yahoo_client_module.get_price_history(symbol, period="1y")
    if df is None or df.empty or "Close" not in df.columns:
        return None

    closes = df["Close"].dropna()
    if len(closes) < 2:
        return None

    # Find the closest date on or after start_date
    start_price = float(closes.iloc[0])
    end_price = float(closes.iloc[-1])

    if start_price <= 0:
        return None

    return (end_price - start_price) / start_price


def run_backtest(
    yahoo_client_module,
    category: str = "screen",
    preset: str | None = None,
    region: str | None = None,
    days_back: int = 90,
    base_dir: str = "data/history",
) -> dict:
    """Run return verification on accumulated screening data.

    Parameters
    ----------
    yahoo_client_module
        The yahoo_client module. Uses get_stock_info(symbol) to fetch
        current prices.
    category : str
        Category to verify. Currently only "screen" is supported.
    preset : str | None
        Filter: only include results from this preset. None for all.
    region : str | None
        Filter: only include results from this region. None for all.
    days_back : int
        How many days back to include. Default 90.
    base_dir : str
        Root history directory. Pass tmp_path in tests.

    Returns
    -------
    dict
        Backtest results with period, stocks, summary stats, and benchmarks.
    """
    # 1. Load screening history
    history = load_history(category, days_back=days_back, base_dir=base_dir)

    # 2. Filter by preset/region
    if preset is not None:
        history = [h for h in history if h.get("preset") == preset]
    if region is not None:
        history = [h for h in history if h.get("region") == region]

    if not history:
        return _empty_result(days_back)

    # 3. Expand stocks from all screening results, keeping earliest record
    # symbol -> {symbol, name, screen_date, score_at_screen, price_at_screen}
    seen: dict[str, dict] = {}
    total_screens = len(history)

    for record in history:
        screen_date = record.get("date", "")
        for stock in record.get("results", []):
            symbol = stock.get("symbol")
            if not symbol:
                continue
            price = stock.get("price")
            if price is None or price <= 0:
                continue

            if symbol not in seen or screen_date < seen[symbol]["screen_date"]:
                seen[symbol] = {
                    "symbol": symbol,
                    "name": stock.get("name", ""),
                    "screen_date": screen_date,
                    "score_at_screen": stock.get("value_score", 0),
                    "price_at_screen": price,
                }

    if not seen:
        return _empty_result(days_back)

    # 4. Get current prices and compute returns
    stocks = []
    for entry in seen.values():
        symbol = entry["symbol"]
        info = yahoo_client_module.get_stock_info(symbol)
        if info is None:
            continue
        price_now = info.get("price")
        if price_now is None or price_now <= 0:
            continue

        return_pct = (price_now - entry["price_at_screen"]) / entry["price_at_screen"]
        stocks.append({
            "symbol": symbol,
            "name": entry["name"],
            "screen_date": entry["screen_date"],
            "score_at_screen": entry["score_at_screen"],
            "price_at_screen": entry["price_at_screen"],
            "price_now": price_now,
            "return_pct": return_pct,
        })

    if not stocks:
        return _empty_result(days_back)

    # Sort by return descending
    stocks.sort(key=lambda s: s["return_pct"], reverse=True)

    # 5. Compute summary stats
    returns = [s["return_pct"] for s in stocks]
    avg_return = sum(returns) / len(returns)
    median_return = median(returns)
    win_rate = sum(1 for r in returns if r > 0) / len(returns)

    # 6. Determine period
    screen_dates = [s["screen_date"] for s in stocks]
    start_date = min(screen_dates)
    end_date = date.today().isoformat()

    # 7. Benchmark returns
    nikkei_return = _get_benchmark_return(yahoo_client_module, "^N225", start_date)
    sp500_return = _get_benchmark_return(yahoo_client_module, "^GSPC", start_date)

    benchmark = {
        "nikkei": nikkei_return,
        "sp500": sp500_return,
    }

    alpha_nikkei = (avg_return - nikkei_return) if nikkei_return is not None else None
    alpha_sp500 = (avg_return - sp500_return) if sp500_return is not None else None

    return {
        "period": {"start": start_date, "end": end_date},
        "total_screens": total_screens,
        "total_stocks": len(stocks),
        "stocks": stocks,
        "avg_return": avg_return,
        "median_return": median_return,
        "win_rate": win_rate,
        "benchmark": benchmark,
        "alpha_nikkei": alpha_nikkei,
        "alpha_sp500": alpha_sp500,
    }


def _empty_result(days_back: int) -> dict:
    """Return an empty result dict when no data is available."""
    end = date.today()
    start = end - timedelta(days=days_back)
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "total_screens": 0,
        "total_stocks": 0,
        "stocks": [],
        "avg_return": 0.0,
        "median_return": 0.0,
        "win_rate": 0.0,
        "benchmark": {"nikkei": None, "sp500": None},
        "alpha_nikkei": None,
        "alpha_sp500": None,
    }
