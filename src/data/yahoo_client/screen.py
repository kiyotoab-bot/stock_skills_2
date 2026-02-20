"""EquityQuery-based screening via yf.screen() (KIK-449)."""

import time

import yfinance as yf
from yfinance import EquityQuery


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
