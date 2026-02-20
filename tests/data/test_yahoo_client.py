"""Tests for src/data/yahoo_client.py (mock-based, no real API calls)."""

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
from unittest.mock import MagicMock

from src.data.yahoo_client import (
    CACHE_TTL_HOURS,
    MACRO_TICKERS,
    _build_dividend_history_from_actions,
    _cache_path,
    _normalize_ratio,
    _read_cache,
    _safe_get,
    _sanitize_anomalies,
    _write_cache,
    get_macro_indicators,
)

# Patch target for CACHE_DIR: must target the submodule where it's defined (KIK-449)
_CACHE_DIR_PATCH = "src.data.yahoo_client._cache.CACHE_DIR"


# ---------------------------------------------------------------------------
# _normalize_ratio
# ---------------------------------------------------------------------------

class TestNormalizeRatio:
    """Tests for _normalize_ratio().

    yfinance always returns dividendYield as percentage (e.g. 3.87 for 3.87%).
    _normalize_ratio always divides by 100 to convert to ratio.
    """

    def test_none_returns_none(self):
        """None input returns None."""
        assert _normalize_ratio(None) is None

    def test_typical_percentage(self):
        """Typical dividend yield percentage (2.52%) -> ratio 0.0252."""
        assert _normalize_ratio(2.52) == pytest.approx(0.0252)

    def test_high_percentage(self):
        """High dividend yield (5.36%) -> ratio 0.0536."""
        assert _normalize_ratio(5.36) == pytest.approx(0.0536)

    def test_sub_one_percent(self):
        """Sub-1% yields (0.41% like AAPL) are correctly converted."""
        assert _normalize_ratio(0.41) == pytest.approx(0.0041)
        assert _normalize_ratio(0.7) == pytest.approx(0.007)
        assert _normalize_ratio(0.25) == pytest.approx(0.0025)

    def test_exactly_one_percent(self):
        """1.0% -> 0.01."""
        assert _normalize_ratio(1.0) == pytest.approx(0.01)

    def test_large_percentage_value(self):
        """Large percentage-like values are properly converted."""
        result = _normalize_ratio(50.0)
        assert result == pytest.approx(0.50)

    def test_very_small_percentage(self):
        """Very small percentage (0.025%) -> ratio 0.00025."""
        assert _normalize_ratio(0.025) == pytest.approx(0.00025)


# ---------------------------------------------------------------------------
# _safe_get
# ---------------------------------------------------------------------------

class TestSafeGet:
    """Tests for _safe_get()."""

    def test_returns_value_for_existing_key(self):
        """Returns the value when key exists."""
        info = {"trailingPE": 15.5}
        assert _safe_get(info, "trailingPE") == 15.5

    def test_returns_none_for_missing_key(self):
        """Returns None when key is missing."""
        info = {"trailingPE": 15.5}
        assert _safe_get(info, "forwardPE") is None

    def test_returns_none_for_none_value(self):
        """Returns None when value is None."""
        info = {"trailingPE": None}
        assert _safe_get(info, "trailingPE") is None

    def test_returns_none_for_nan(self):
        """Returns None for NaN float values."""
        info = {"trailingPE": float("nan")}
        assert _safe_get(info, "trailingPE") is None

    def test_returns_none_for_infinity(self):
        """Returns None for infinity float values."""
        info = {"trailingPE": float("inf")}
        assert _safe_get(info, "trailingPE") is None

    def test_returns_none_for_negative_infinity(self):
        """Returns None for negative infinity."""
        info = {"trailingPE": float("-inf")}
        assert _safe_get(info, "trailingPE") is None

    def test_returns_string_value(self):
        """Returns string values correctly."""
        info = {"shortName": "Toyota"}
        assert _safe_get(info, "shortName") == "Toyota"

    def test_returns_zero(self):
        """Returns zero (falsy but valid) correctly."""
        info = {"beta": 0}
        assert _safe_get(info, "beta") == 0


# ---------------------------------------------------------------------------
# _cache_path
# ---------------------------------------------------------------------------

class TestCachePath:
    """Tests for _cache_path()."""

    def test_returns_path_object(self):
        """_cache_path returns a Path object."""
        result = _cache_path("7203.T")
        assert isinstance(result, Path)

    def test_dots_replaced_with_underscores(self):
        """Dots in symbol names are replaced with underscores."""
        result = _cache_path("7203.T")
        assert result.name == "7203_T.json"

    def test_slashes_replaced_with_underscores(self):
        """Slashes in symbol names are replaced with underscores."""
        result = _cache_path("D05.SI")
        assert result.name == "D05_SI.json"

    def test_plain_symbol(self):
        """Plain symbol (no special chars) maps to <symbol>.json."""
        result = _cache_path("AAPL")
        assert result.name == "AAPL.json"

    def test_path_is_under_cache_dir(self):
        """Cache path is under the data/cache/ directory."""
        result = _cache_path("AAPL")
        assert "cache" in str(result)
        assert result.suffix == ".json"


# ---------------------------------------------------------------------------
# Cache read/write tests (using tmp_path)
# ---------------------------------------------------------------------------

class TestCacheReadWrite:
    """Tests for _read_cache() and _write_cache() using tmp_path."""

    def test_write_and_read_cache(self, tmp_path):
        """Written cache data can be read back."""
        # Patch CACHE_DIR to use tmp_path
        with patch(_CACHE_DIR_PATCH, tmp_path):
            data = {"symbol": "7203.T", "price": 2850.0}
            _write_cache("7203.T", data)

            # Verify file was created
            cache_file = tmp_path / "7203_T.json"
            assert cache_file.exists()

            # Read back
            result = _read_cache("7203.T")
            assert result is not None
            assert result["symbol"] == "7203.T"
            assert result["price"] == 2850.0

    def test_read_cache_adds_timestamp(self, tmp_path):
        """_write_cache adds a _cached_at timestamp."""
        with patch(_CACHE_DIR_PATCH, tmp_path):
            data = {"symbol": "TEST"}
            _write_cache("TEST", data)

            cache_file = tmp_path / "TEST.json"
            with open(cache_file, "r", encoding="utf-8") as f:
                stored = json.load(f)
            assert "_cached_at" in stored

    def test_read_cache_returns_none_for_missing(self, tmp_path):
        """_read_cache returns None when cache file does not exist."""
        with patch(_CACHE_DIR_PATCH, tmp_path):
            result = _read_cache("NONEXISTENT")
            assert result is None

    def test_cache_valid_within_ttl(self, tmp_path):
        """Cache data is returned when within TTL."""
        with patch(_CACHE_DIR_PATCH, tmp_path):
            data = {"symbol": "7203.T", "price": 2850.0}
            _write_cache("7203.T", data)

            # Read immediately (well within 24h TTL)
            result = _read_cache("7203.T")
            assert result is not None
            assert result["symbol"] == "7203.T"

    def test_cache_expired_beyond_ttl(self, tmp_path):
        """Cache data returns None when beyond TTL."""
        with patch(_CACHE_DIR_PATCH, tmp_path):
            # Write with a timestamp that is 25 hours ago (beyond 24h TTL)
            expired_time = (datetime.now() - timedelta(hours=CACHE_TTL_HOURS + 1)).isoformat()
            data = {"symbol": "7203.T", "price": 2850.0, "_cached_at": expired_time}

            cache_file = tmp_path / "7203_T.json"
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f)

            result = _read_cache("7203.T")
            assert result is None

    def test_cache_valid_just_before_ttl(self, tmp_path):
        """Cache data is still valid just before TTL expiry."""
        with patch(_CACHE_DIR_PATCH, tmp_path):
            # Write with a timestamp that is 23 hours ago (just within 24h TTL)
            recent_time = (datetime.now() - timedelta(hours=CACHE_TTL_HOURS - 1)).isoformat()
            data = {"symbol": "7203.T", "price": 2850.0, "_cached_at": recent_time}

            cache_file = tmp_path / "7203_T.json"
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f)

            result = _read_cache("7203.T")
            assert result is not None

    def test_read_cache_handles_corrupt_json(self, tmp_path):
        """_read_cache returns None for corrupt JSON files."""
        with patch(_CACHE_DIR_PATCH, tmp_path):
            cache_file = tmp_path / "CORRUPT.json"
            cache_file.write_text("not valid json {{{")

            result = _read_cache("CORRUPT")
            assert result is None

    def test_read_cache_handles_missing_timestamp(self, tmp_path):
        """_read_cache returns None if _cached_at is missing from data."""
        with patch(_CACHE_DIR_PATCH, tmp_path):
            cache_file = tmp_path / "NOTIME.json"
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({"symbol": "NOTIME"}, f)

            result = _read_cache("NOTIME")
            assert result is None

    def test_write_cache_creates_directory(self, tmp_path):
        """_write_cache creates the cache directory if it doesn't exist."""
        nested_dir = tmp_path / "nested" / "cache"
        with patch(_CACHE_DIR_PATCH, nested_dir):
            _write_cache("TEST", {"symbol": "TEST"})
            assert nested_dir.exists()
            assert (nested_dir / "TEST.json").exists()


# ---------------------------------------------------------------------------
# _sanitize_anomalies
# ---------------------------------------------------------------------------

class TestSanitizeAnomalies:
    """Tests for _sanitize_anomalies() -- anomaly value guard."""

    def test_normal_values_unchanged(self):
        data = {"dividend_yield": 0.035, "pbr": 0.85, "per": 12.5, "roe": 0.15}
        result = _sanitize_anomalies(data)
        assert result["dividend_yield"] == 0.035
        assert result["pbr"] == 0.85
        assert result["per"] == 12.5
        assert result["roe"] == 0.15

    def test_extreme_dividend_yield_sanitized(self):
        data = {"dividend_yield": 0.78}  # 78%
        assert _sanitize_anomalies(data)["dividend_yield"] is None

    def test_dividend_yield_at_boundary(self):
        data = {"dividend_yield": 0.15}
        assert _sanitize_anomalies(data)["dividend_yield"] == 0.15

    def test_dividend_yield_just_over_boundary(self):
        data = {"dividend_yield": 0.151}
        assert _sanitize_anomalies(data)["dividend_yield"] is None

    def test_extreme_low_pbr_sanitized(self):
        data = {"pbr": 0.01}  # シーラHD case
        assert _sanitize_anomalies(data)["pbr"] is None

    def test_pbr_at_boundary(self):
        data = {"pbr": 0.05}
        assert _sanitize_anomalies(data)["pbr"] == 0.05

    def test_pbr_just_under_boundary(self):
        data = {"pbr": 0.049}
        assert _sanitize_anomalies(data)["pbr"] is None

    def test_anomalous_low_per_sanitized(self):
        data = {"per": 0.5}
        assert _sanitize_anomalies(data)["per"] is None

    def test_per_at_boundary(self):
        data = {"per": 1.0}
        assert _sanitize_anomalies(data)["per"] == 1.0

    def test_per_negative_not_touched(self):
        data = {"per": -5.0}
        assert _sanitize_anomalies(data)["per"] == -5.0

    def test_per_zero_not_touched(self):
        data = {"per": 0.0}
        assert _sanitize_anomalies(data)["per"] == 0.0

    def test_extreme_roe_high_sanitized(self):
        data = {"roe": 2.5}
        assert _sanitize_anomalies(data)["roe"] is None

    def test_extreme_roe_low_sanitized(self):
        data = {"roe": -1.5}
        assert _sanitize_anomalies(data)["roe"] is None

    def test_roe_at_upper_boundary(self):
        data = {"roe": 2.0}
        assert _sanitize_anomalies(data)["roe"] == 2.0

    def test_roe_at_lower_boundary(self):
        data = {"roe": -1.0}
        assert _sanitize_anomalies(data)["roe"] == -1.0

    def test_none_values_unchanged(self):
        data = {"dividend_yield": None, "pbr": None, "per": None, "roe": None}
        result = _sanitize_anomalies(data)
        assert all(result[k] is None for k in ["dividend_yield", "pbr", "per", "roe"])

    def test_missing_keys_no_error(self):
        data = {"symbol": "TEST", "price": 100.0}
        result = _sanitize_anomalies(data)
        assert result["symbol"] == "TEST"

    def test_multiple_anomalies_all_sanitized(self):
        data = {"dividend_yield": 0.68, "pbr": 0.01, "per": 0.5, "roe": 3.0}
        result = _sanitize_anomalies(data)
        assert all(result[k] is None for k in ["dividend_yield", "pbr", "per", "roe"])

    def test_returns_same_dict(self):
        data = {"dividend_yield": 0.78}
        result = _sanitize_anomalies(data)
        assert result is data


# ---------------------------------------------------------------------------
# _build_dividend_history_from_actions (KIK-388)
# ---------------------------------------------------------------------------

class TestBuildDividendHistoryFromActions:
    """Tests for _build_dividend_history_from_actions() (KIK-388)."""

    def test_normal_multi_year(self):
        """Multi-year dividend history is built correctly."""
        mock_ticker = MagicMock()
        dates = pd.to_datetime([
            "2024-06-01", "2024-12-01",
            "2023-06-01", "2023-12-01",
            "2022-06-01", "2022-12-01",
        ])
        divs = pd.Series([30.0, 35.0, 28.0, 32.0, 25.0, 28.0], index=dates)
        mock_ticker.dividends = divs

        shares = 1_000_000.0
        amounts, years = _build_dividend_history_from_actions(mock_ticker, shares)

        assert len(amounts) == 3
        assert years == [2024, 2023, 2022]
        assert amounts[0] == pytest.approx(-(30 + 35) * 1_000_000)
        assert amounts[1] == pytest.approx(-(28 + 32) * 1_000_000)
        assert amounts[2] == pytest.approx(-(25 + 28) * 1_000_000)
        assert all(a < 0 for a in amounts)

    def test_no_shares_outstanding(self):
        """Returns empty when shares_outstanding is None."""
        mock_ticker = MagicMock()
        mock_ticker.dividends = pd.Series([30.0], index=pd.to_datetime(["2024-06-01"]))
        amounts, years = _build_dividend_history_from_actions(mock_ticker, None)
        assert amounts == []
        assert years == []

    def test_zero_shares_outstanding(self):
        """Returns empty when shares_outstanding is 0."""
        mock_ticker = MagicMock()
        mock_ticker.dividends = pd.Series([30.0], index=pd.to_datetime(["2024-06-01"]))
        amounts, years = _build_dividend_history_from_actions(mock_ticker, 0)
        assert amounts == []
        assert years == []

    def test_empty_dividends(self):
        """Returns empty when ticker.dividends is empty."""
        mock_ticker = MagicMock()
        mock_ticker.dividends = pd.Series([], dtype=float)
        amounts, years = _build_dividend_history_from_actions(mock_ticker, 1e6)
        assert amounts == []
        assert years == []

    def test_none_dividends(self):
        """Returns empty when ticker.dividends is None."""
        mock_ticker = MagicMock()
        mock_ticker.dividends = None
        amounts, years = _build_dividend_history_from_actions(mock_ticker, 1e6)
        assert amounts == []
        assert years == []

    def test_single_year(self):
        """Single year of dividends returns 1 entry."""
        mock_ticker = MagicMock()
        dates = pd.to_datetime(["2024-03-01", "2024-09-01"])
        divs = pd.Series([25.0, 25.0], index=dates)
        mock_ticker.dividends = divs
        amounts, years = _build_dividend_history_from_actions(mock_ticker, 1e6)
        assert len(amounts) == 1
        assert years == [2024]
        assert amounts[0] == pytest.approx(-50.0 * 1e6)

    def test_max_years_limit(self):
        """Respects max_years parameter."""
        mock_ticker = MagicMock()
        dates = pd.to_datetime([f"{y}-06-01" for y in range(2018, 2025)])
        divs = pd.Series([30.0] * 7, index=dates)
        mock_ticker.dividends = divs
        amounts, years = _build_dividend_history_from_actions(mock_ticker, 1e6, max_years=3)
        assert len(amounts) == 3
        assert years == [2024, 2023, 2022]

    def test_exception_returns_empty(self):
        """Exceptions are caught and return empty."""
        mock_ticker = MagicMock()
        type(mock_ticker).dividends = property(lambda self: (_ for _ in ()).throw(RuntimeError("fail")))
        amounts, years = _build_dividend_history_from_actions(mock_ticker, 1e6)
        assert amounts == []
        assert years == []


# ---------------------------------------------------------------------------
# get_macro_indicators (KIK-396)
# ---------------------------------------------------------------------------

def _make_mock_history(closes):
    """Build a minimal DataFrame with Close column from a list of floats."""
    return pd.DataFrame({"Close": closes})


class TestGetMacroIndicators:
    """Tests for get_macro_indicators()."""

    def test_returns_list(self, monkeypatch):
        """All 8 tickers return data → 8 entries."""
        monkeypatch.setattr(time, "sleep", lambda _: None)

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = _make_mock_history([100.0, 101.0, 102.0, 103.0, 104.0])

        import yfinance as yf
        monkeypatch.setattr(yf, "Ticker", lambda symbol: mock_ticker)

        result = get_macro_indicators()
        assert isinstance(result, list)
        assert len(result) == len(MACRO_TICKERS)

    def test_indicator_fields(self, monkeypatch):
        """Each dict has required fields: name, symbol, price, daily_change, weekly_change, is_point_diff."""
        monkeypatch.setattr(time, "sleep", lambda _: None)

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = _make_mock_history([100.0, 102.0, 101.0, 103.0, 105.0])

        import yfinance as yf
        monkeypatch.setattr(yf, "Ticker", lambda symbol: mock_ticker)

        result = get_macro_indicators()
        for ind in result:
            assert "name" in ind
            assert "symbol" in ind
            assert "price" in ind
            assert "daily_change" in ind
            assert "weekly_change" in ind
            assert "is_point_diff" in ind
            assert ind["price"] == 105.0

    def test_daily_and_weekly_change(self, monkeypatch):
        """Daily and weekly changes are calculated correctly (percentage)."""
        monkeypatch.setattr(time, "sleep", lambda _: None)

        # 5 days: 100, 102, 104, 103, 106
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = _make_mock_history([100.0, 102.0, 104.0, 103.0, 106.0])

        import yfinance as yf
        monkeypatch.setattr(yf, "Ticker", lambda symbol: mock_ticker)

        result = get_macro_indicators()
        # Find S&P500 (not point_diff)
        sp = next(i for i in result if i["name"] == "S&P500")
        assert sp["is_point_diff"] is False
        # daily: (106 - 103) / 103
        assert sp["daily_change"] == pytest.approx((106.0 - 103.0) / 103.0)
        # weekly: (106 - 100) / 100
        assert sp["weekly_change"] == pytest.approx((106.0 - 100.0) / 100.0)

    def test_point_diff_tickers(self, monkeypatch):
        """VIX and bond yield use point difference, not percentage."""
        monkeypatch.setattr(time, "sleep", lambda _: None)

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = _make_mock_history([20.0, 22.0, 21.0, 23.0, 25.0])

        import yfinance as yf
        monkeypatch.setattr(yf, "Ticker", lambda symbol: mock_ticker)

        result = get_macro_indicators()
        vix = next(i for i in result if i["name"] == "VIX")
        assert vix["is_point_diff"] is True
        # daily: 25 - 23 = 2.0 (point diff)
        assert vix["daily_change"] == pytest.approx(2.0)
        # weekly: 25 - 20 = 5.0 (point diff)
        assert vix["weekly_change"] == pytest.approx(5.0)

    def test_exception_skips_ticker(self, monkeypatch):
        """One ticker raising → that ticker is skipped, rest returned."""
        monkeypatch.setattr(time, "sleep", lambda _: None)

        call_count = [0]

        def mock_ticker_factory(symbol):
            call_count[0] += 1
            t = MagicMock()
            if symbol == "^GSPC":
                t.history.side_effect = RuntimeError("Network error")
            else:
                t.history.return_value = _make_mock_history([100.0, 101.0])
            return t

        import yfinance as yf
        monkeypatch.setattr(yf, "Ticker", mock_ticker_factory)

        result = get_macro_indicators()
        assert len(result) == len(MACRO_TICKERS) - 1
        names = [i["name"] for i in result]
        assert "S&P500" not in names

    def test_empty_history(self, monkeypatch):
        """Empty DataFrame → None values in result."""
        monkeypatch.setattr(time, "sleep", lambda _: None)

        mock_ticker = MagicMock()
        mock_ticker.history.return_value = pd.DataFrame()

        import yfinance as yf
        monkeypatch.setattr(yf, "Ticker", lambda symbol: mock_ticker)

        result = get_macro_indicators()
        assert len(result) == len(MACRO_TICKERS)
        for ind in result:
            assert ind["price"] is None
            assert ind["daily_change"] is None
            assert ind["weekly_change"] is None
