"""Stock info and detail fetching (KIK-449, KIK-531)."""

import datetime
import socket
import time
from typing import Any, Optional

import pandas as pd
import yfinance as yf

from src.data.yahoo_client._cache import (
    _read_cache,
    _write_cache,
    _read_detail_cache,
    _write_detail_cache,
)
from src.data.yahoo_client._memory_cache import stock_detail_cache
from src.data.yahoo_client._normalize import (
    _normalize_ratio,
    _safe_get,
    _sanitize_anomalies,
)


def _earnings_date(info: dict) -> Optional[str]:
    """Extract the next earnings date as YYYY-MM-DD from a yfinance info dict.

    yfinance は POSIX タイムスタンプで ``earningsTimestamp`` /
    ``earningsTimestampStart`` / ``earningsTimestampEnd`` を返す。

    取引所ローカルのタイムゾーン（``exchangeTimezoneName``）で日付化する。
    UTC で日付化すると JST 09:00 より前を指す値が前日になり、推定日を
    「現地 00:00」で持つケース（``isEarningsDateEstimate`` が真のとき）は
    確実に1日前倒しされる。前倒しされると ``detect_alerts`` の
    ``0 <= days_until <= 7`` 判定で決算当日に ``days_until = -1`` となり、
    最も知りたい日にアラートが消える。

    複数のキーのうち **今日以降で最も近い日** を採る。``earningsTimestamp``
    は直近の確定済み（過去の）決算日を指すことがあり、単純に先頭優先で
    確定させると過去日を掴んで同じくアラートが出なくなる。
    全て過去なら最も新しい過去日を返す（情報として保持する）。
    """
    from datetime import datetime, timezone

    tz = timezone.utc
    tz_name = _safe_get(info, "exchangeTimezoneName")
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            tz = ZoneInfo(str(tz_name))
        except Exception:
            tz = timezone.utc

    today = datetime.now(tz).date()
    candidates = []
    for key in ("earningsTimestamp", "earningsTimestampStart", "earningsTimestampEnd"):
        ts = _safe_get(info, key)
        if ts is None:
            continue
        try:
            candidates.append(datetime.fromtimestamp(float(ts), tz=tz).date())
        except (ValueError, OSError, OverflowError, TypeError):
            continue

    if not candidates:
        return None

    future = [d for d in candidates if d >= today]
    return (min(future) if future else max(candidates)).isoformat()


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


_DIVIDEND_DIVERGENCE_LIMIT = 0.30


def _dividend_suspect(rate, trailing_rate) -> Optional[bool]:
    """Flag a forecast dividend that diverges wildly from the trailing actual.

    yfinance の ``dividendRate``（会社予想 DPS）は実測で誤値が混入する。既知の実害:
      2026-05-31 9928.T : 130円（実際60円）→ 利回り 7.67% と表示され候補入りしかけた
      2026-08-05 6436.T : 250円（会社予想180円）→ 利回り 6.44% と誤認して第1弾の推奨に載せた
    既存の ``_sanitize_anomalies`` は利回り 15% 超しか弾かないため、この帯域を素通りする。

    ⚠️ 自動補正はしない。7453.T 良品計画のように実際に急増配している銘柄も
    +75.8% で引っかかるため、真偽はエージェントが一次情報で確認する。
    ここは「そのまま信じるな」という印にとどめる。

    Returns True (要確認) / False (整合) / None (判定不能).
    """
    try:
        r = float(rate)
        t = float(trailing_rate)
    except (TypeError, ValueError):
        return None
    if r <= 0 or t <= 0:
        return None
    # abs(r / t - 1) 形式だと 130/100 - 1 が 0.30000000000000004 になり
    # ちょうど閾値の値を超過と誤判定する。減算を先に行って誤差を避ける。
    return abs(r - t) > t * _DIVIDEND_DIVERGENCE_LIMIT


_JQ_DIVERGENCE_LIMIT = 0.20

#: 当期末までこの日数を切ると、yfinance の forward 予想は翌期に切り替わっている
#: 可能性が高い。7453.T 良品計画（8月決算）が 2026-08-07 時点で該当し、
#: 会社予想EPS 126.19（FY2026/8）と yfinance 157.49（FY2027/8）の +24.8% 乖離を
#: 「データ異常」と誤検知していた。実際はどちらも正しく、決算期が違うだけ。
_JQ_FY_ROLLOVER_DAYS = 90


def _merge_jquants_forecast(symbol: str, result: dict, today=None) -> None:
    """日本株の会社予想を J-Quants（決算短信）から上書きマージする。

    yfinance の予想値は第三者推定で、実測で誤りが混入していた:
      6436.T アマノ  dividendRate 250円（会社予想 180円）→ 利回りを 6.44% と誤認
      6701.T 日本電気 forwardEps 718.96（会社予想の約3.3倍）→ PER 6.4 と誤認
    J-Quants は JPX 公式の決算短信そのものなので、取れる限りこちらを一次情報とする。

    追加されるキー:
      forecast_source            "jquants" / "yfinance" / None
      forecast_eps_company       会社予想EPS（円）
      forecast_dps_company       会社予想 年間配当（円）
      dividend_yield_company     会社予想配当 ÷ 株価
      per_forward_company        株価 ÷ 会社予想EPS
      forecast_divergence        yfinance と会社予想の乖離（EPS/配当の最大絶対値）
      forecast_suspect           説明のつかない乖離が 20% を超えたら True
      forecast_fy_rollover_likely 当期末が近く yfinance が翌期予想を指している可能性
      forecast_fiscal_year_end   会社予想が対象とする決算期末
      jquants_disclosed_date     参照した開示日

    ⚠️ IFRS/Non-GAAP 開示だと FEPS/FNP が空になる（実測: 6701 / 4568 / 9364）。
      その場合は yfinance の値を残し、``forecast_source`` を "yfinance" にする。
      値を捏造せず「取れなかった」ことを残すのが目的。
    """
    result.setdefault("forecast_source", None)
    if not str(symbol).upper().endswith(".T"):
        return  # J-Quants は日本株のみ
    try:
        from src.data.jquants_client import get_company_forecast
    except ImportError:
        return
    try:
        fc = get_company_forecast(symbol)
    except Exception:  # noqa: BLE001
        return
    if not fc.get("available"):
        return

    result["jquants_disclosed_date"] = fc.get("disclosed_date")
    price = _num_or_none(result.get("price"))
    eps_c = fc.get("forecast_eps")
    dps_c = fc.get("forecast_dps_annual")

    result["forecast_eps_company"] = eps_c
    result["forecast_dps_company"] = dps_c
    result["forecast_net_income_company"] = fc.get("forecast_net_income")
    result["forecast_operating_profit_company"] = fc.get("forecast_operating_profit")

    rollover = _fy_rollover_likely(fc.get("fiscal_year_end"), today)
    result["forecast_fy_rollover_likely"] = rollover
    result["forecast_fiscal_year_end"] = _fy_end_str(fc.get("fiscal_year_end"))

    gaps = []          # suspect の判定に使う乖離
    all_gaps = []      # 記録用（説明のつくものも含む）
    if eps_c and eps_c > 0:
        if price and price > 0:
            result["per_forward_company"] = price / eps_c
        yf_eps = _num_or_none(result.get("forward_eps"))
        if yf_eps and yf_eps > 0:
            gap = abs(yf_eps - eps_c) / eps_c
            all_gaps.append(gap)
            # 期末が近いと yfinance は翌期予想に切り替わる。決算期の違いを
            # データ異常と呼ばない（CP1 と同じ型の誤り）。
            if not rollover:
                gaps.append(gap)
    if dps_c and dps_c > 0:
        if price and price > 0:
            result["dividend_yield_company"] = dps_c / price
        yf_dps = _num_or_none(result.get("dividend_rate"))
        if yf_dps and yf_dps > 0:
            gap = abs(yf_dps - dps_c) / dps_c
            all_gaps.append(gap)
            gaps.append(gap)
            # dividend_yield_suspect は yfinance 内部の 予想配当 vs 実績配当 の
            # 比較でしか立たないので、増配・株式分割でも発火する（7453.T 良品計画:
            # 予想32円 / 実績18.2円、間に 2025-08-28 の1:2分割と増配）。
            # 会社予想が予想配当を裏付けているならデータ異常ではない。
            if gap <= _JQ_DIVERGENCE_LIMIT:
                result["dividend_yield_suspect"] = False
                result["dividend_rate_confirmed_by"] = "jquants"

    if fc.get("has_forecast"):
        result["forecast_source"] = "jquants"
    elif result.get("forward_per") or result.get("dividend_rate"):
        result["forecast_source"] = "yfinance"

    if all_gaps:
        result["forecast_divergence"] = max(all_gaps)
        result["forecast_suspect"] = bool(
            gaps and max(gaps) > _JQ_DIVERGENCE_LIMIT
        )


def _fy_end_str(fy_end) -> Optional[str]:
    """決算期末を ``YYYY-MM-DD`` に正規化する（date / datetime / str / NaT）。"""
    if fy_end is None:
        return None
    # datetime / pd.Timestamp は "2026-08-31T00:00:00" 形式になるので日付部分だけ取る。
    # pd.NaT は .isoformat() が例外ではなく 'NaT' を返すため、
    # 最後に必ず fromisoformat で通るかを確かめる。
    raw = fy_end.isoformat() if isinstance(fy_end, datetime.date) else str(fy_end)
    text = raw[:10]
    try:
        datetime.date.fromisoformat(text)
    except ValueError:
        return None
    return text


def _fy_rollover_likely(fy_end, today=None) -> bool:
    """当期末が近く、yfinance の forward 予想が翌期を指している可能性が高いか。

    決算期末までの残日数が ``_JQ_FY_ROLLOVER_DAYS`` 以内なら True。
    既に期末を過ぎている（新しい開示待ち）場合も True 扱いにする。
    """
    text = _fy_end_str(fy_end)
    if not text:
        return False
    today = today or datetime.date.today()
    return (datetime.date.fromisoformat(text) - today).days <= _JQ_FY_ROLLOVER_DAYS


def _num_or_none(value) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


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
            # 会社予想との突合に使うため EPS も持つ（forwardPE だけだと乖離を検出できない）
            "forward_eps": _safe_get(info, "forwardEps"),
            "trailing_eps": _safe_get(info, "trailingEps"),
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
            # Per-share dividend amounts, kept so the forecast can be cross-checked
            "dividend_rate": _safe_get(info, "dividendRate"),
            "dividend_rate_trailing": _safe_get(info, "trailingAnnualDividendRate"),
            "dividend_yield_suspect": _dividend_suspect(
                _safe_get(info, "dividendRate"),
                _safe_get(info, "trailingAnnualDividendRate"),
            ),
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
            # Quote type (KIK-469)
            "quoteType": _safe_get(info, "quoteType"),
            # Next earnings date (KIK-727)
            # portfolio.csv の next_earnings 列は手動更新前提で常に空欄のままだったため
            # detect_alerts の earnings_soon が一度も発火していなかった。ここで自動取得する。
            "next_earnings": _earnings_date(info),
            # 「推定でない」と「決算日が取れていない」を潰さないよう None を許す
            "earnings_date_estimated": (
                bool(_safe_get(info, "isEarningsDateEstimate"))
                if _earnings_date(info) else None
            ),
        }

        _sanitize_anomalies(result)
        _merge_jquants_forecast(symbol, result)
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
# get_stock_detail
# ---------------------------------------------------------------------------

def get_stock_detail(symbol: str) -> Optional[dict]:
    """Fetch detailed stock information including financial statements.

    Extends the base data from ``get_stock_info`` with price history,
    balance-sheet ratios, cash-flow, EPS growth, and debt/EBITDA figures.

    Returns a merged dict or None if the base data cannot be fetched.
    Uses memory → file → API three-tier cache (KIK-531).
    """
    # 0. Check in-memory cache first (KIK-531)
    mem_cached = stock_detail_cache.get(symbol)
    if mem_cached is not None:
        return mem_cached

    # 1. Get base data first
    base = get_stock_info(symbol)
    if base is None:
        return None

    # 2. Check file-based detail cache
    cached = _read_detail_cache(symbol)
    if cached is not None:
        stock_detail_cache.set(symbol, cached)
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
        depreciation: Optional[float] = None  # KIK-708
        # KIK-743: try ブロック外で初期化（API失敗時の未定義参照回避）
        dividend_paid_history: list[float] = []
        stock_repurchase_history: list[float] = []
        cashflow_fiscal_years: list[int] = []
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
            # KIK-708: Depreciation for adjusted cash conversion
            depreciation = _try_get_field(cf, [
                "Depreciation And Amortization",
                "Depreciation",
                "DepreciationAndAmortization",
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
            # （初期化は try ブロック前に移動済み: KIK-743）
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
        operating_income_history: list[float] = []  # KIK-708
        interest_expense: Optional[float] = None    # KIK-708
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

                # KIK-708: Operating income history (3 periods) for scoring
                operating_income_history = _try_get_history(inc, [
                    "Operating Income",
                    "EBIT",
                    "OperatingIncome",
                ])

                # KIK-708: Interest expense for interest coverage ratio
                interest_expense = _try_get_field(inc, [
                    "Interest Expense",
                    "InterestExpense",
                    "Interest Expense Non Operating",
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
        # KIK-743: ETF系変数を try ブロック外で初期化（info取得失敗時の未定義参照回避）
        expense_ratio: Optional[float] = None
        total_assets_fund: Optional[float] = None
        fund_category: Optional[str] = None
        fund_family: Optional[str] = None
        quote_type: Optional[str] = None
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
            # ETF-specific fields (KIK-469)
            expense_ratio = _safe_get(info, "annualReportExpenseRatio")
            total_assets_fund = _safe_get(info, "totalAssets")  # AUM
            fund_category = _safe_get(info, "category")
            fund_family = _safe_get(info, "fundFamily")
            quote_type = _safe_get(info, "quoteType")
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
            # Scoring fields (KIK-708)
            "operating_income_history": operating_income_history,
            "interest_expense": interest_expense,
            "depreciation": depreciation,
            # ETF fields (KIK-469)
            "quoteType": quote_type,
            "expense_ratio": expense_ratio,
            "total_assets_fund": total_assets_fund,
            "fund_category": fund_category,
            "fund_family": fund_family,
        })

        # 5. Cache the result (file + memory)
        _write_detail_cache(symbol, result)
        stock_detail_cache.set(symbol, result)
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
