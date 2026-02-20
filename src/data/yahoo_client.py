"""Yahoo Finance API wrapper with JSON file-based caching."""

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import socket

import pandas as pd
import yfinance as yf
from yfinance import EquityQuery


CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "cache"
CACHE_TTL_HOURS = 24


def _cache_path(symbol: str) -> Path:
    """Return the cache file path for a given symbol."""
    safe_name = symbol.replace(".", "_").replace("/", "_")
    return CACHE_DIR / f"{safe_name}.json"


def _read_cache(symbol: str) -> Optional[dict]:
    """Read cached data if it exists and is still valid."""
    path = _cache_path(symbol)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cached_at = datetime.fromisoformat(data.get("_cached_at", ""))
        if datetime.now() - cached_at > timedelta(hours=CACHE_TTL_HOURS):
            return None
        return data
    except (json.JSONDecodeError, ValueError, KeyError):
        return None


def _write_cache(symbol: str, data: dict) -> None:
    """Write data to cache with a timestamp."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data["_cached_at"] = datetime.now().isoformat()
    path = _cache_path(symbol)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _safe_get(info: dict, key: str) -> Any:
    """Safely retrieve a value from the info dict, returning None on failure."""
    try:
        value = info.get(key)
        if value is None:
            return None
        # yfinance occasionally returns 'Infinity' or NaN
        if isinstance(value, float) and (value != value or abs(value) == float("inf")):
            return None
        return value
    except Exception:
        return None


def _normalize_ratio(value: Any) -> Optional[float]:
    """Convert yfinance percentage value to ratio.

    yfinance returns dividendYield as a percentage (e.g. 3.87 for 3.87%,
    0.41 for 0.41%).  Always divide by 100 to get ratio form.
    """
    if value is None:
        return None
    return value / 100.0


def _sanitize_anomalies(data: dict) -> dict:
    """Sanitize anomalous financial data values to None.

    Yahoo Finance occasionally returns extreme values (e.g. 78% dividend yield
    from special dividends, PBR 0.01 from accounting anomalies) that would
    distort screening results.
    """
    # dividend_yield: max 15%
    dy = data.get("dividend_yield")
    if dy is not None and dy > 0.15:
        data["dividend_yield"] = None

    # dividend_yield_trailing: max 15%
    dy_t = data.get("dividend_yield_trailing")
    if dy_t is not None and dy_t > 0.15:
        data["dividend_yield_trailing"] = None

    # pbr: min 0.05
    pbr = data.get("pbr")
    if pbr is not None and pbr < 0.05:
        data["pbr"] = None

    # per: min 1.0 (negative/zero already handled by scorers)
    per = data.get("per")
    if per is not None and 0 < per < 1.0:
        data["per"] = None

    # roe: -100% to 200%
    roe = data.get("roe")
    if roe is not None and (roe < -1.0 or roe > 2.0):
        data["roe"] = None

    return data


def get_stock_info(symbol: str) -> Optional[dict]:
    """Fetch basic stock information for a single symbol.

    Returns a dict with standardized keys, or None if the fetch fails entirely.
    Individual fields that are unavailable are set to None.
    """
    # Check cache first
    cached = _read_cache(symbol)
    if cached is not None:
        return cached

    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info

        if not info or info.get("regularMarketPrice") is None:
            return None

        result = {
            "symbol": symbol,
            "name": _safe_get(info, "shortName") or _safe_get(info, "longName"),
            "sector": _safe_get(info, "sector"),
            "industry": _safe_get(info, "industry"),
            "currency": _safe_get(info, "currency"),
            # Price
            "price": _safe_get(info, "regularMarketPrice"),
            "market_cap": _safe_get(info, "marketCap"),
            # Valuation
            "per": _safe_get(info, "trailingPE"),
            "forward_per": _safe_get(info, "forwardPE"),
            "pbr": _safe_get(info, "priceToBook"),
            "psr": _safe_get(info, "priceToSalesTrailing12Months"),
            # Profitability
            "roe": _safe_get(info, "returnOnEquity"),
            "roa": _safe_get(info, "returnOnAssets"),
            "profit_margin": _safe_get(info, "profitMargins"),
            "operating_margin": _safe_get(info, "operatingMargins"),
            # Dividend (yfinance returns percentage, e.g. 2.52 for 2.52%)
            "dividend_yield": _normalize_ratio(_safe_get(info, "dividendYield")),
            # Trailing dividend yield (already a ratio from yfinance, e.g. 0.025 = 2.5%)
            "dividend_yield_trailing": _safe_get(info, "trailingAnnualDividendYield"),
            "payout_ratio": _safe_get(info, "payoutRatio"),
            # Growth
            "revenue_growth": _safe_get(info, "revenueGrowth"),
            "earnings_growth": _safe_get(info, "earningsGrowth"),
            # Financial health
            "debt_to_equity": _safe_get(info, "debtToEquity"),
            "current_ratio": _safe_get(info, "currentRatio"),
            "free_cashflow": _safe_get(info, "freeCashflow"),
            # Other
            "beta": _safe_get(info, "beta"),
            "fifty_two_week_high": _safe_get(info, "fiftyTwoWeekHigh"),
            "fifty_two_week_low": _safe_get(info, "fiftyTwoWeekLow"),
        }

        _sanitize_anomalies(result)
        _write_cache(symbol, result)
        return result

    except (TimeoutError, socket.timeout) as e:
        print(
            f"⚠️  Yahoo Financeへの接続がタイムアウトしました ({symbol})\n"
            "    原因: ネットワーク接続が不安定、またはYahoo Financeが一時的に応答していません\n"
            "    対処: ネットワーク接続を確認し、再試行してください"
        )
        return None
    except Exception as e:
        if "timed out" in str(e).lower() or "timeout" in str(e).lower():
            print(
                f"⚠️  Yahoo Financeへの接続がタイムアウトしました ({symbol})\n"
                "    原因: ネットワーク接続が不安定、またはYahoo Financeが一時的に応答していません\n"
                "    対処: ネットワーク接続を確認し、再試行してください"
            )
        else:
            print(f"[yahoo_client] Error fetching {symbol}: {e}")
        return None


def get_multiple_stocks(symbols: list[str]) -> dict[str, Optional[dict]]:
    """Fetch stock info for multiple symbols with a 1-second delay between requests.

    Returns a dict mapping symbol -> stock info (or None on failure).
    """
    results: dict[str, Optional[dict]] = {}
    for i, symbol in enumerate(symbols):
        results[symbol] = get_stock_info(symbol)
        # Wait 1 second between requests (skip after the last one)
        if i < len(symbols) - 1:
            time.sleep(1)
    return results


# ---------------------------------------------------------------------------
# Detail cache helpers
# ---------------------------------------------------------------------------

def _detail_cache_path(symbol: str) -> Path:
    """Return the detail-cache file path for a given symbol."""
    safe_name = symbol.replace(".", "_").replace("/", "_")
    return CACHE_DIR / f"{safe_name}_detail.json"


def _read_detail_cache(symbol: str) -> Optional[dict]:
    """Read detail-cached data if it exists and is still valid (24h TTL)."""
    path = _detail_cache_path(symbol)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cached_at = datetime.fromisoformat(data.get("_cached_at", ""))
        if datetime.now() - cached_at > timedelta(hours=CACHE_TTL_HOURS):
            return None
        return data
    except (json.JSONDecodeError, ValueError, KeyError):
        return None


def _write_detail_cache(symbol: str, data: dict) -> None:
    """Write detail data to cache with a timestamp."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data["_cached_at"] = datetime.now().isoformat()
    path = _detail_cache_path(symbol)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _try_get_field(df: Any, field_names: list[str]) -> Optional[float]:
    """Try to extract a numeric value from a DataFrame row using multiple
    possible field names.  Returns None if the DataFrame is empty or none of
    the names exist.
    """
    try:
        if df is None or df.empty:
            return None
        for name in field_names:
            if name in df.index:
                value = df.loc[name].iloc[0]
                # Convert numpy / pandas types to plain Python float
                if value is not None and value == value:  # NaN check
                    return float(value)
        return None
    except Exception:
        return None


def _try_get_history(df, field_names: list[str], max_periods: int = 4) -> list[float]:
    """Try to extract multiple periods of data from a DataFrame row.

    Returns a list of floats in latest-to-oldest order.  Stops at the first
    NaN / None so that only contiguous data is returned.
    """
    try:
        if df is None or df.empty:
            return []
        for name in field_names:
            if name in df.index:
                values: list[float] = []
                row = df.loc[name]
                for i in range(min(len(row), max_periods)):
                    val = row.iloc[i]
                    if val is not None and val == val:  # NaN check
                        values.append(float(val))
                    else:
                        break  # contiguous data required
                if values:
                    return values
        return []
    except Exception:
        return []


def _build_dividend_history_from_actions(
    ticker, shares_outstanding, max_years: int = 4
) -> tuple:
    """Build dividend history from ticker.dividends as a fallback (KIK-388).

    When cashflow does not contain dividend payment history, use per-share
    dividend actions grouped by calendar year and multiplied by
    shares_outstanding to estimate total amounts.

    Returns
    -------
    tuple[list[float], list[int]]
        (dividend_amounts, fiscal_years) both in latest-first order.
        Amounts are negative (cash outflow convention matching cashflow).
        Returns ([], []) if data is insufficient.
    """
    try:
        if shares_outstanding is None or shares_outstanding <= 0:
            return [], []

        divs = ticker.dividends
        if divs is None or len(divs) == 0:
            return [], []

        # Group by calendar year, sum per-share dividends
        yearly = divs.groupby(divs.index.year).sum()
        if len(yearly) == 0:
            return [], []

        # Take most recent max_years, sorted latest-first
        years_sorted = sorted(yearly.index, reverse=True)[:max_years]

        amounts: list = []
        fiscal_years: list = []
        for year in years_sorted:
            per_share_total = float(yearly.loc[year])
            if per_share_total > 0:
                # Negative convention (cash outflow) to match cashflow format
                amounts.append(-(per_share_total * shares_outstanding))
                fiscal_years.append(int(year))

        return amounts, fiscal_years
    except Exception:
        return [], []


# ---------------------------------------------------------------------------
# get_stock_detail
# ---------------------------------------------------------------------------

def get_stock_detail(symbol: str) -> Optional[dict]:
    """Fetch detailed stock information including financial statements.

    Extends the base data from ``get_stock_info`` with price history,
    balance-sheet ratios, cash-flow, EPS growth, and debt/EBITDA figures.

    Returns a merged dict or None if the base data cannot be fetched.
    """
    # 1. Get base data first
    base = get_stock_info(symbol)
    if base is None:
        return None

    # 2. Check detail cache
    cached = _read_detail_cache(symbol)
    if cached is not None:
        return cached

    # 3. Fetch additional data from yfinance
    try:
        time.sleep(1)  # rate-limit consistent with existing pattern
        ticker = yf.Ticker(symbol)

        # --- Price history (2 years for ~24 monthly returns) ---
        price_history: Optional[list[float]] = None
        try:
            hist = ticker.history(period="2y")
            if hist is not None and not hist.empty and "Close" in hist.columns:
                price_history = [float(v) for v in hist["Close"].tolist()]
        except Exception:
            pass

        # --- Balance sheet: equity ratio, total_assets, equity_history ---
        equity_ratio: Optional[float] = None
        total_assets: Optional[float] = None
        equity_history: list[float] = []
        try:
            bs = ticker.balance_sheet
            if bs is not None and not bs.empty:
                col = bs.iloc[:, 0]  # most recent column
                equity = _try_get_field(bs, [
                    "Stockholders Equity",
                    "Total Stockholder Equity",
                    "Stockholders' Equity",
                    "StockholdersEquity",
                    "Total Equity Gross Minority Interest",
                ])
                total_assets = _try_get_field(bs, [
                    "Total Assets",
                    "TotalAssets",
                ])
                if equity is not None and total_assets is not None and total_assets != 0:
                    equity_ratio = float(equity / total_assets)

                # Multi-period equity history for ROE trend analysis
                equity_history = _try_get_history(bs, [
                    "Stockholders Equity",
                    "Total Stockholder Equity",
                    "Stockholders' Equity",
                    "StockholdersEquity",
                    "Total Equity Gross Minority Interest",
                ])
        except Exception:
            pass

        # --- Cash flow ---
        operating_cashflow: Optional[float] = None
        fcf: Optional[float] = None
        dividend_paid: Optional[float] = None
        stock_repurchase: Optional[float] = None
        try:
            cf = ticker.cashflow
            operating_cashflow = _try_get_field(cf, [
                "Operating Cash Flow",
                "Total Cash From Operating Activities",
                "Cash Flow From Continuing Operating Activities",
            ])
            fcf = _try_get_field(cf, [
                "Free Cash Flow",
                "FreeCashFlow",
            ])
            # KIK-375: Shareholder return data
            dividend_paid = _try_get_field(cf, [
                "Common Stock Dividend Paid",
                "Cash Dividends Paid",
                "Payment Of Dividends",
            ])
            stock_repurchase = _try_get_field(cf, [
                "Repurchase Of Capital Stock",
                "Common Stock Payments",
            ])
            if stock_repurchase is None:
                net_issuance = _try_get_field(cf, [
                    "Net Common Stock Issuance",
                ])
                if net_issuance is not None and net_issuance < 0:
                    stock_repurchase = net_issuance

            # KIK-380: Shareholder return 3-year history
            dividend_paid_history: list[float] = []
            stock_repurchase_history: list[float] = []
            cashflow_fiscal_years: list[int] = []
            div_field_names = [
                "Common Stock Dividend Paid",
                "Cash Dividends Paid",
                "Payment Of Dividends",
            ]
            rep_field_names = [
                "Repurchase Of Capital Stock",
                "Common Stock Payments",
            ]
            dividend_paid_history = _try_get_history(cf, div_field_names)
            stock_repurchase_history = _try_get_history(cf, rep_field_names)
            # Fallback: Net Common Stock Issuance (negative = repurchase)
            if not stock_repurchase_history:
                net_iss_hist = _try_get_history(cf, ["Net Common Stock Issuance"])
                stock_repurchase_history = [v for v in net_iss_hist if v < 0]
            # Extract fiscal year labels from cashflow column dates
            try:
                if cf is not None and not cf.empty:
                    for i in range(min(len(cf.columns), 4)):
                        col = cf.columns[i]
                        if hasattr(col, "year"):
                            cashflow_fiscal_years.append(int(col.year))
            except Exception:
                pass
        except Exception:
            pass

        # KIK-388: Fallback to ticker.dividends when cashflow dividend history is sparse
        if len(dividend_paid_history) < 2:
            shares_out = _safe_get(ticker.info, "sharesOutstanding")
            fb_amounts, fb_years = _build_dividend_history_from_actions(
                ticker, shares_out
            )
            if len(fb_amounts) >= 2:
                dividend_paid_history = fb_amounts
                if not cashflow_fiscal_years:
                    cashflow_fiscal_years = fb_years

        # --- Income statement: EPS, net income, revenue/NI history ---
        eps_current: Optional[float] = None
        eps_previous: Optional[float] = None
        eps_growth: Optional[float] = None
        net_income_stmt: Optional[float] = None
        revenue_history: list[float] = []
        net_income_history: list[float] = []
        try:
            inc = ticker.income_stmt
            if inc is not None and not inc.empty:
                # Net income from most recent period
                net_income_stmt = _try_get_field(inc, [
                    "Net Income",
                    "NetIncome",
                    "Net Income Common Stockholders",
                ])

                # Multi-period revenue history for acceleration analysis
                revenue_history = _try_get_history(inc, [
                    "Total Revenue",
                    "Revenue",
                ])

                # Multi-period net income history for ROE trend analysis
                net_income_history = _try_get_history(inc, [
                    "Net Income",
                    "NetIncome",
                    "Net Income Common Stockholders",
                ])

                # Diluted EPS – latest two years for growth calculation
                eps_field_name = None
                for candidate in ["Diluted EPS", "DilutedEPS"]:
                    if candidate in inc.index:
                        eps_field_name = candidate
                        break

                if eps_field_name is not None:
                    eps_row = inc.loc[eps_field_name]
                    if len(eps_row) >= 1:
                        val = eps_row.iloc[0]
                        if val is not None and val == val:
                            eps_current = float(val)
                    if len(eps_row) >= 2:
                        val = eps_row.iloc[1]
                        if val is not None and val == val:
                            eps_previous = float(val)
                    if (
                        eps_current is not None
                        and eps_previous is not None
                        and eps_previous != 0
                    ):
                        eps_growth = float(
                            (eps_current - eps_previous) / abs(eps_previous)
                        )
        except Exception:
            pass

        # --- Additional info fields ---
        total_debt: Optional[float] = None
        ebitda: Optional[float] = None
        target_high_price: Optional[float] = None
        target_low_price: Optional[float] = None
        target_mean_price: Optional[float] = None
        number_of_analyst_opinions: Optional[int] = None
        recommendation_mean: Optional[float] = None
        forward_eps: Optional[float] = None
        try:
            info = ticker.info
            total_debt = _safe_get(info, "totalDebt")
            ebitda = _safe_get(info, "ebitda")
            target_high_price = _safe_get(info, "targetHighPrice")
            target_low_price = _safe_get(info, "targetLowPrice")
            target_mean_price = _safe_get(info, "targetMeanPrice")
            number_of_analyst_opinions_val = _safe_get(info, "numberOfAnalystOpinions")
            number_of_analyst_opinions = int(number_of_analyst_opinions_val) if number_of_analyst_opinions_val is not None else None
            recommendation_mean = _safe_get(info, "recommendationMean")
            forward_eps = _safe_get(info, "forwardEps")
        except Exception:
            pass

        # 4. Merge into base dict
        result = dict(base)  # shallow copy to avoid mutating cached base
        result.update({
            "price_history": price_history,
            "equity_ratio": equity_ratio,
            "operating_cashflow": operating_cashflow,
            "net_income_stmt": net_income_stmt,
            "fcf": fcf,
            "total_debt": total_debt,
            "ebitda": ebitda,
            # Analyst fields (KIK-359)
            "target_high_price": target_high_price,
            "target_low_price": target_low_price,
            "target_mean_price": target_mean_price,
            "number_of_analyst_opinions": number_of_analyst_opinions,
            "recommendation_mean": recommendation_mean,
            "forward_eps": forward_eps,
            "eps_current": eps_current,
            "eps_previous": eps_previous,
            "eps_growth": eps_growth,
            # Alpha signal fields (KIK-346)
            "total_assets": total_assets,
            "revenue_history": revenue_history,
            "net_income_history": net_income_history,
            # Shareholder return fields (KIK-375)
            "dividend_paid": dividend_paid,
            "stock_repurchase": stock_repurchase,
            "equity_history": equity_history,
            # Shareholder return history (KIK-380)
            "dividend_paid_history": dividend_paid_history,
            "stock_repurchase_history": stock_repurchase_history,
            "cashflow_fiscal_years": cashflow_fiscal_years,
        })

        # 5. Cache the result
        _write_detail_cache(symbol, result)
        return result

    except (TimeoutError, socket.timeout) as e:
        print(
            f"⚠️  Yahoo Financeへの接続がタイムアウトしました ({symbol})\n"
            "    原因: ネットワーク接続が不安定、またはYahoo Financeが一時的に応答していません\n"
            "    対処: ネットワーク接続を確認し、再試行してください"
        )
        return None
    except Exception as e:
        if "timed out" in str(e).lower() or "timeout" in str(e).lower():
            print(
                f"⚠️  Yahoo Financeへの接続がタイムアウトしました ({symbol})\n"
                "    原因: ネットワーク接続が不安定、またはYahoo Financeが一時的に応答していません\n"
                "    対処: ネットワーク接続を確認し、再試行してください"
            )
        else:
            print(f"[yahoo_client] Error fetching detail for {symbol}: {e}")
        return None


# ---------------------------------------------------------------------------
# EquityQuery-based screening via yf.screen()
# ---------------------------------------------------------------------------

def screen_stocks(
    query: EquityQuery,
    size: int = 250,
    sort_field: str = "intradaymarketcap",
    sort_asc: bool = False,
    max_results: int = 0,
) -> list[dict]:
    """Screen stocks using yfinance EquityQuery + yf.screen().

    Paginates through all results using the ``offset`` parameter.

    Parameters
    ----------
    query : EquityQuery
        Pre-built EquityQuery object containing all screening conditions.
    size : int
        Number of results per page (max 250 for yf.screen).
    sort_field : str
        Field to sort results by (default: market cap descending).
    sort_asc : bool
        Sort ascending if True, descending if False.
    max_results : int
        Maximum total results to fetch. 0 means no limit (fetch all pages).

    Returns
    -------
    list[dict]
        List of quote dicts returned by yf.screen(). Each dict contains
        raw Yahoo Finance fields such as 'symbol', 'shortName',
        'regularMarketPrice', 'trailingPE', 'priceToBook',
        'dividendYield', 'returnOnEquity', etc.
        Returns an empty list on error.
    """
    all_quotes: list[dict] = []
    offset = 0
    total = None
    page = 1

    try:
        while True:
            # Adjust page size if max_results would be exceeded
            page_size = size
            if max_results > 0:
                remaining = max_results - len(all_quotes)
                if remaining <= 0:
                    break
                page_size = min(size, remaining)

            if total is not None:
                print(f"[yahoo_client] Fetching page {page}... ({len(all_quotes)}/{total})")
            else:
                print(f"[yahoo_client] Fetching page {page}...")

            response = yf.screen(
                query, size=page_size, offset=offset,
                sortField=sort_field, sortAsc=sort_asc,
            )
            if response is None:
                print("[yahoo_client] yf.screen() returned None")
                break

            quotes = response.get("quotes", [])
            if not isinstance(quotes, list):
                print(f"[yahoo_client] Unexpected quotes type: {type(quotes)}")
                break

            if total is None:
                total = response.get("total", 0)
                print(f"[yahoo_client] Total matching stocks: {total}")

            if not quotes:
                break

            all_quotes.extend(quotes)

            # Stop if we have reached the total or max_results
            offset += len(quotes)
            if offset >= (total or 0):
                break
            if max_results > 0 and len(all_quotes) >= max_results:
                break

            page += 1
            time.sleep(1)  # rate-limit between pages

        print(f"[yahoo_client] Fetched {len(all_quotes)} stocks total")
        return all_quotes

    except Exception as e:
        print(f"[yahoo_client] Error in screen_stocks: {e}")
        return all_quotes if all_quotes else []


# ---------------------------------------------------------------------------
# Price history for technical analysis
# ---------------------------------------------------------------------------

def get_price_history(symbol: str, period: str = "1y") -> Optional[pd.DataFrame]:
    """Fetch price history for technical analysis.

    Returns a pandas DataFrame with columns: Open, High, Low, Close, Volume.
    Returns None on error.

    No caching is applied because technical analysis requires the latest data.
    A 1-second sleep is used for rate-limit compliance.
    """
    try:
        time.sleep(1)  # rate-limit
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        if hist is None or hist.empty:
            print(f"[yahoo_client] No price history for {symbol}")
            return None
        # Keep only the standard OHLCV columns
        expected_cols = ["Open", "High", "Low", "Close", "Volume"]
        available_cols = [c for c in expected_cols if c in hist.columns]
        if "Close" not in available_cols:
            print(f"[yahoo_client] No 'Close' column in history for {symbol}")
            return None
        return hist[available_cols]
    except (TimeoutError, socket.timeout) as e:
        print(
            f"⚠️  Yahoo Financeへの接続がタイムアウトしました ({symbol})\n"
            "    原因: ネットワーク接続が不安定、またはYahoo Financeが一時的に応答していません\n"
            "    対処: ネットワーク接続を確認し、再試行してください"
        )
        return None
    except Exception as e:
        if "timed out" in str(e).lower() or "timeout" in str(e).lower():
            print(
                f"⚠️  Yahoo Financeへの接続がタイムアウトしました ({symbol})\n"
                "    原因: ネットワーク接続が不安定、またはYahoo Financeが一時的に応答していません\n"
                "    対処: ネットワーク接続を確認し、再試行してください"
            )
        else:
            print(f"[yahoo_client] Error fetching price history for {symbol}: {e}")
        return None


# ---------------------------------------------------------------------------
# Macro Indicators (KIK-396)
# ---------------------------------------------------------------------------

MACRO_TICKERS = {
    "S&P500": "^GSPC",
    "日経平均": "^N225",
    "VIX": "^VIX",
    "米10年債": "^TNX",
    "USD/JPY": "JPY=X",
    "EUR/USD": "EURUSD=X",
    "原油(WTI)": "CL=F",
    "金": "GC=F",
}

# Tickers where change is expressed as point difference, not percentage
_POINT_DIFF_TICKERS = {"^VIX", "^TNX"}


def get_macro_indicators() -> list[dict]:
    """Fetch macro economic indicators (8 tickers).

    Returns a list of dicts with keys:
        name, symbol, price, daily_change, weekly_change, is_point_diff.

    ``daily_change`` and ``weekly_change`` are percentage changes (0.01 = 1%)
    for normal tickers, or raw point differences for VIX / bond yields
    (``is_point_diff=True``).

    No caching is applied because freshness is important.
    A 1-second sleep is used per ticker for rate-limit compliance.
    """
    results: list[dict] = []

    for name, symbol in MACRO_TICKERS.items():
        try:
            time.sleep(1)
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d")
            if hist is None or hist.empty or "Close" not in hist.columns:
                results.append({
                    "name": name,
                    "symbol": symbol,
                    "price": None,
                    "daily_change": None,
                    "weekly_change": None,
                    "is_point_diff": symbol in _POINT_DIFF_TICKERS,
                })
                continue

            closes = hist["Close"].dropna()
            if len(closes) == 0:
                results.append({
                    "name": name,
                    "symbol": symbol,
                    "price": None,
                    "daily_change": None,
                    "weekly_change": None,
                    "is_point_diff": symbol in _POINT_DIFF_TICKERS,
                })
                continue

            latest = float(closes.iloc[-1])
            is_point = symbol in _POINT_DIFF_TICKERS

            # Daily change
            daily_change = None
            if len(closes) >= 2:
                prev = float(closes.iloc[-2])
                if is_point:
                    daily_change = latest - prev
                elif prev != 0:
                    daily_change = (latest - prev) / prev

            # Weekly change (oldest available in 5d window)
            weekly_change = None
            oldest = float(closes.iloc[0])
            if is_point:
                weekly_change = latest - oldest
            elif oldest != 0:
                weekly_change = (latest - oldest) / oldest

            results.append({
                "name": name,
                "symbol": symbol,
                "price": latest,
                "daily_change": daily_change,
                "weekly_change": weekly_change,
                "is_point_diff": is_point,
            })
        except Exception as e:
            print(f"[yahoo_client] Error fetching macro indicator {name}: {e}")
            continue

    return results


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

def get_stock_news(symbol: str, count: int = 10) -> list[dict]:
    """Fetch recent news for a stock symbol.

    Returns a list of news items with title, publisher, link, and publish time.
    No caching is applied because news freshness is important.

    Parameters
    ----------
    symbol : str
        Stock ticker symbol (e.g. "AAPL", "7203.T").
    count : int
        Maximum number of news items to return (default 10).

    Returns
    -------
    list[dict]
        Each dict contains: title, publisher, link, publish_time (ISO format str).
        Returns an empty list on error.
    """
    try:
        ticker = yf.Ticker(symbol)
        raw_news = ticker.news
        if not raw_news:
            return []

        results = []
        for item in raw_news[:count]:
            content = item.get("content", item)  # yfinance wraps in "content" sometimes
            if isinstance(content, dict):
                publish_time = content.get("pubDate") or content.get("providerPublishTime")
            else:
                publish_time = item.get("providerPublishTime")

            # Handle providerPublishTime as unix timestamp
            if isinstance(publish_time, (int, float)):
                publish_time = datetime.fromtimestamp(publish_time).isoformat()

            news_item = {
                "title": content.get("title", "") if isinstance(content, dict) else item.get("title", ""),
                "publisher": content.get("provider", {}).get("displayName", "") if isinstance(content, dict) else item.get("publisher", ""),
                "link": content.get("canonicalUrl", {}).get("url", "") if isinstance(content, dict) else item.get("link", ""),
                "publish_time": str(publish_time) if publish_time else "",
            }
            results.append(news_item)
        return results
    except Exception as e:
        print(f"[yahoo_client] Error fetching news for {symbol}: {e}")
        return []
