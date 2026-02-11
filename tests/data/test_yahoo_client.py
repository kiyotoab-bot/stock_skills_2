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

from src.data.yahoo_client import (
    CACHE_TTL_HOURS,
    _cache_path,
    _normalize_ratio,
    _read_cache,
    _safe_get,
    _write_cache,
)


# ---------------------------------------------------------------------------
# _normalize_ratio
# ---------------------------------------------------------------------------

class TestNormalizeRatio:
    """Tests for _normalize_ratio()."""

    def test_none_returns_none(self):
        """None input returns None."""
        assert _normalize_ratio(None) is None

    def test_value_less_than_one_unchanged(self):
        """Values <= 1 are returned as-is (already a ratio)."""
        assert _normalize_ratio(0.025) == 0.025
        assert _normalize_ratio(0.5) == 0.5
        assert _normalize_ratio(1.0) == 1.0

    def test_value_greater_than_one_divided_by_100(self):
        """Values > 1 are assumed to be percentages and divided by 100."""
        result = _normalize_ratio(2.56)
        assert result == pytest.approx(0.0256)

    def test_large_percentage_value(self):
        """Large percentage-like values are properly converted."""
        result = _normalize_ratio(50.0)
        assert result == pytest.approx(0.50)

    def test_value_exactly_one(self):
        """Value of exactly 1.0 is returned unchanged (not divided)."""
        # _normalize_ratio: if value > 1 -> divide.  value == 1 -> unchanged.
        assert _normalize_ratio(1.0) == 1.0

    def test_small_positive_value(self):
        """Small positive values (typical ratios) are unchanged."""
        assert _normalize_ratio(0.001) == 0.001


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
        with patch("src.data.yahoo_client.CACHE_DIR", tmp_path):
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
        with patch("src.data.yahoo_client.CACHE_DIR", tmp_path):
            data = {"symbol": "TEST"}
            _write_cache("TEST", data)

            cache_file = tmp_path / "TEST.json"
            with open(cache_file, "r", encoding="utf-8") as f:
                stored = json.load(f)
            assert "_cached_at" in stored

    def test_read_cache_returns_none_for_missing(self, tmp_path):
        """_read_cache returns None when cache file does not exist."""
        with patch("src.data.yahoo_client.CACHE_DIR", tmp_path):
            result = _read_cache("NONEXISTENT")
            assert result is None

    def test_cache_valid_within_ttl(self, tmp_path):
        """Cache data is returned when within TTL."""
        with patch("src.data.yahoo_client.CACHE_DIR", tmp_path):
            data = {"symbol": "7203.T", "price": 2850.0}
            _write_cache("7203.T", data)

            # Read immediately (well within 24h TTL)
            result = _read_cache("7203.T")
            assert result is not None
            assert result["symbol"] == "7203.T"

    def test_cache_expired_beyond_ttl(self, tmp_path):
        """Cache data returns None when beyond TTL."""
        with patch("src.data.yahoo_client.CACHE_DIR", tmp_path):
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
        with patch("src.data.yahoo_client.CACHE_DIR", tmp_path):
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
        with patch("src.data.yahoo_client.CACHE_DIR", tmp_path):
            cache_file = tmp_path / "CORRUPT.json"
            cache_file.write_text("not valid json {{{")

            result = _read_cache("CORRUPT")
            assert result is None

    def test_read_cache_handles_missing_timestamp(self, tmp_path):
        """_read_cache returns None if _cached_at is missing from data."""
        with patch("src.data.yahoo_client.CACHE_DIR", tmp_path):
            cache_file = tmp_path / "NOTIME.json"
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({"symbol": "NOTIME"}, f)

            result = _read_cache("NOTIME")
            assert result is None

    def test_write_cache_creates_directory(self, tmp_path):
        """_write_cache creates the cache directory if it doesn't exist."""
        nested_dir = tmp_path / "nested" / "cache"
        with patch("src.data.yahoo_client.CACHE_DIR", nested_dir):
            _write_cache("TEST", {"symbol": "TEST"})
            assert nested_dir.exists()
            assert (nested_dir / "TEST.json").exists()
