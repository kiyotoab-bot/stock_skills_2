"""Tests for src/data/jpx_client/ (margin, investor_type, short_selling, get_demand_supply)."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

pytestmark = pytest.mark.no_auto_mock


# ---------------------------------------------------------------------------
# Helpers: minimal DataFrame fixtures matching actual XLS structure
# ---------------------------------------------------------------------------

def _make_margin_df() -> pd.DataFrame:
    """Minimal DataFrame matching mtdailyk*.xls structure."""
    rows = []
    # row 0: title
    rows.append([None] * 15)
    # row 1: date header in col 1
    rows.append([None, "as of 2026/4/27 application based"] + [None] * 13)
    # rows 2-6: filler
    for _ in range(5):
        rows.append([None] * 15)
    # rows 7+: per-stock data (col[8]=sell, col[11]=buy)
    for _ in range(3):
        row = [None] * 15
        row[8] = "1000"
        row[11] = "3000"
        rows.append(row)

    return pd.DataFrame(rows)


def _make_investor_df() -> pd.DataFrame:
    """Minimal DataFrame matching stock_val_1_*.xls structure.

    Keyword rows at indices 26 (Individuals), 30 (Foreigners), 37 (Inv Trusts).
    Balance (col[6]) appears in adjacent rows within ±2 offset.
    """
    num_rows = 45
    num_cols = 10
    rows = [[None] * num_cols for _ in range(num_rows)]

    # row 0: week label
    rows[0][0] = "2026年4月 week3 (4/13 - 4/17)"

    # Foreigners: keyword row=30, balance in row=30 col=6
    rows[30][0] = "Foreigners"
    rows[30][6] = "1,635,174,762"

    # Individuals: keyword row=27, balance in row=26 col=6
    rows[27][0] = "Individuals"
    rows[26][6] = "-785,711,849"

    # Investment Trusts: keyword row=39, balance in row=37 col=6
    rows[39][0] = "Investment Trusts"
    rows[37][6] = "-149,154,920"

    return pd.DataFrame(rows)


def _make_pdf_bytes() -> bytes:
    return b"2026/4/28\n12,345,678 shares total short"


# ---------------------------------------------------------------------------
# Cache TTL helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """Redirect JPX cache to a temp directory for each test."""
    import src.data.jpx_client._cache as cache_mod
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# TestCacheReadWrite
# ---------------------------------------------------------------------------

class TestCacheReadWrite:
    def test_write_and_read_within_ttl(self, tmp_path, monkeypatch):
        import src.data.jpx_client._cache as cache_mod
        monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
        cache_mod.write_cache("margin", "202618", {"margin_ratio": 3.36})
        result = cache_mod.read_cache("margin", "202618", "weekly")
        assert result is not None
        assert result["margin_ratio"] == 3.36

    def test_expired_cache_returns_none(self, tmp_path, monkeypatch):
        import src.data.jpx_client._cache as cache_mod
        from datetime import datetime, timedelta
        monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)

        # Write with old timestamp
        path = tmp_path / "jpx_margin_202618.json"
        old_time = (datetime.now() - timedelta(hours=200)).isoformat()
        path.write_text(
            json.dumps({"margin_ratio": 3.36, "_cached_at": old_time}),
            encoding="utf-8"
        )
        result = cache_mod.read_cache("margin", "202618", "weekly")
        assert result is None

    def test_missing_cache_returns_none(self, tmp_path, monkeypatch):
        import src.data.jpx_client._cache as cache_mod
        monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
        assert cache_mod.read_cache("margin", "999999", "weekly") is None

    def test_week_key_format(self):
        from src.data.jpx_client._cache import week_key
        key = week_key()
        assert len(key) == 6
        assert key[:4].isdigit()
        assert key[4:].isdigit()


# ---------------------------------------------------------------------------
# TestMarginScraping
# ---------------------------------------------------------------------------

class TestMarginScraping:
    def test_successful_scrape(self, monkeypatch):
        from src.data.jpx_client import margin as margin_mod

        html = '<a href="/markets/statistics-equities/margin/tvd0000001r92-att/mtdailyk12345.xls">link</a>'
        xls_bytes = b"\xd0\xcf\x11\xe0" + b"\x00" * 512  # xlrd magic

        monkeypatch.setattr(
            "src.data.jpx_client._common.requests.get",
            lambda url, **kw: _mock_response(html if "index.html" in url else None, xls_bytes),
        )
        with patch("src.data.jpx_client.margin.read_xls", return_value=_make_margin_df()):
            result = margin_mod.get_margin()

        assert result["available"] is True
        assert result["margin_ratio"] == 3.0  # 9000/3000
        assert result["buy_shares"] == 9000
        assert result["sell_shares"] == 3000
        assert result["signal"] == "neutral"
        assert result["week_of"] == "2026-04-27"

    def test_fetch_failure_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            "src.data.jpx_client._common.requests.get",
            lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("no internet")),
        )
        from src.data.jpx_client.margin import get_margin
        result = get_margin()
        assert result["available"] is False
        assert result["margin_ratio"] is None

    def test_xls_link_not_found(self, monkeypatch):
        monkeypatch.setattr(
            "src.data.jpx_client._common.requests.get",
            lambda url, **kw: _mock_response("<html>no links here</html>", b""),
        )
        from src.data.jpx_client.margin import get_margin
        result = get_margin()
        assert result["available"] is False

    def test_signal_high(self, monkeypatch):
        from src.data.jpx_client import margin as margin_mod

        html = '<a href="/margins/tvd/mtdailyk9.xls">x</a>'
        monkeypatch.setattr(
            "src.data.jpx_client._common.requests.get",
            lambda url, **kw: _mock_response(html if "index.html" in url else None, b"\xd0\xcf\x11\xe0"),
        )
        df = _make_margin_df()
        # set buy to 5x sell
        for i in range(7, len(df)):
            df.iat[i, 8] = "1000"
            df.iat[i, 11] = "5000"
        with patch("src.data.jpx_client.margin.read_xls", return_value=df):
            result = margin_mod.get_margin()
        assert result["signal"] == "high"

    def test_wow_change_computed_from_cache(self, monkeypatch, tmp_path):
        import src.data.jpx_client._cache as cache_mod
        monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)

        # Write previous week cache（前週 2.5 → 今週 3.0 なので +20%）
        cache_mod.write_cache("margin", "202617", {"margin_ratio": 2.5, "week_of": "2026-04-20"})

        from src.data.jpx_client import margin as margin_mod
        html = '<a href="/margins/tvd/mtdailyk9.xls">x</a>'
        monkeypatch.setattr(
            "src.data.jpx_client._common.requests.get",
            lambda url, **kw: _mock_response(html if "index.html" in url else None, b"\xd0\xcf\x11\xe0"),
        )
        # margin.py は `from ._cache import week_key` でモジュールグローバルに
        # 束縛しているため、_cache 側を差し替えても効かない。import 先を差し替える。
        with patch("src.data.jpx_client.margin.read_xls", return_value=_make_margin_df()):
            with patch("src.data.jpx_client.margin.week_key", return_value="202618"):
                result = margin_mod.get_margin()

        # 実値まで固定する（is not None だけでは前週比ロジックの退行を拾えない）
        assert result["wow_change_pct"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# TestInvestorTypeScraping
# ---------------------------------------------------------------------------

class TestInvestorTypeScraping:
    def test_successful_parse(self, monkeypatch):
        from src.data.jpx_client import investor_type as inv_mod

        html = '<a href="/markets/statistics-equities/investor-type/tvd/stock_val_1_99999.xls">x</a>'
        monkeypatch.setattr(
            "src.data.jpx_client._common.requests.get",
            lambda url, **kw: _mock_response(html if "index.html" in url else None, b"\xd0\xcf\x11\xe0"),
        )
        with patch("src.data.jpx_client.investor_type.read_xls", return_value=_make_investor_df()):
            result = inv_mod.get_investor_type()

        assert result["available"] is True
        assert result["foreign_net_bn"] == pytest.approx(16351.7, rel=0.01)
        assert result["individual_net_bn"] == pytest.approx(-7857.1, rel=0.01)
        assert result["trust_net_bn"] == pytest.approx(-1491.5, rel=0.01)
        assert result["week_of"] == "2026-04-17"

    def test_fetch_failure_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            "src.data.jpx_client._common.requests.get",
            lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("offline")),
        )
        from src.data.jpx_client.investor_type import get_investor_type
        result = get_investor_type()
        assert result["available"] is False
        assert result["foreign_net_bn"] is None

    def test_consecutive_weeks_single(self, monkeypatch):
        from src.data.jpx_client import investor_type as inv_mod
        html = '<a href="/markets/statistics-equities/investor-type/tvd/stock_val_1_1.xls">x</a>'
        monkeypatch.setattr(
            "src.data.jpx_client._common.requests.get",
            lambda url, **kw: _mock_response(html if "index.html" in url else None, b"\xd0\xcf\x11\xe0"),
        )
        with patch("src.data.jpx_client.investor_type.read_xls", return_value=_make_investor_df()):
            result = inv_mod.get_investor_type()
        assert result["foreign_consecutive_buy_weeks"] == 1

    def test_week_of_extraction(self):
        from src.data.jpx_client.investor_type import _parse_week_of
        df = _make_investor_df()
        assert _parse_week_of(df) == "2026-04-17"


# ---------------------------------------------------------------------------
# TestShortSellingParse
# ---------------------------------------------------------------------------

class TestShortSellingParse:
    def test_successful_parse(self, monkeypatch):
        from src.data.jpx_client import short_selling as ss_mod

        html = '<a href="/markets/statistics-equities/short-selling/tvd/240430-m.pdf">x</a>'
        monkeypatch.setattr(
            "src.data.jpx_client._common.requests.get",
            lambda url, **kw: _mock_response(html if "index.html" in url else None, b"%PDF-1.4"),
        )

        mock_text = "2026/4/28\n12,345,678 total"
        with patch("src.data.jpx_client.short_selling._pdf_extract", return_value=mock_text):
            result = ss_mod.get_short_selling()

        assert result["available"] is True
        assert result["short_volume"] == 12345678
        assert result["date"] == "2026-04-28"

    def test_no_pdfminer(self, monkeypatch):
        import src.data.jpx_client.short_selling as ss_mod
        monkeypatch.setattr(ss_mod, "_HAS_PDFMINER", False)
        result = ss_mod.get_short_selling()
        assert result["available"] is False
        assert "pdfminer" in result["error"]

    def test_fetch_failure(self, monkeypatch):
        monkeypatch.setattr(
            "src.data.jpx_client._common.requests.get",
            lambda *a, **kw: (_ for _ in ()).throw(ConnectionError("offline")),
        )
        from src.data.jpx_client.short_selling import get_short_selling
        result = get_short_selling()
        assert result["available"] is False

    def test_invalid_volume_out_of_range(self, monkeypatch):
        from src.data.jpx_client import short_selling as ss_mod
        html = '<a href="/tvd/240430-m.pdf">x</a>'
        monkeypatch.setattr(
            "src.data.jpx_client._common.requests.get",
            lambda url, **kw: _mock_response(html if "index.html" in url else None, b"%PDF"),
        )
        # max integer way too small
        with patch("src.data.jpx_client.short_selling._pdf_extract", return_value="2026/4/28\n123"):
            result = ss_mod.get_short_selling()
        assert result["available"] is False


# ---------------------------------------------------------------------------
# TestGetDemandSupply
# ---------------------------------------------------------------------------

class TestGetDemandSupply:
    def test_all_available(self, monkeypatch):
        margin_result = {
            "buy_shares": 9000, "sell_shares": 3000, "margin_ratio": 3.0,
            "week_of": "2026-04-27", "signal": "neutral", "wow_change_pct": None,
            "available": True, "error": None,
        }
        investor_result = {
            "foreign_net_bn": 16351.7, "individual_net_bn": -7857.1, "trust_net_bn": -1491.5,
            "week_of": "2026-04-17", "foreign_consecutive_buy_weeks": 1,
            "available": True, "error": None,
        }
        short_result = {
            "short_volume": 12345678, "dod_change_pct": None, "date": "2026-04-28",
            "available": True, "error": None,
        }
        monkeypatch.setattr("src.data.jpx_client.get_margin", lambda: margin_result)
        monkeypatch.setattr("src.data.jpx_client.get_investor_type", lambda: investor_result)
        monkeypatch.setattr("src.data.jpx_client.get_short_selling", lambda: short_result)

        from src.data.jpx_client import get_demand_supply
        result = get_demand_supply()

        assert result["available"] is True
        assert result["error"] is None
        assert result["margin"]["margin_ratio"] == 3.0
        assert result["investor_type"]["foreign_net_bn"] == 16351.7
        assert result["short_selling"]["short_volume"] == 12345678
        # meta keys stripped from sub-dicts
        assert "available" not in result["margin"]
        assert "error" not in result["margin"]

    def test_partial_failure_still_available(self, monkeypatch):
        monkeypatch.setattr(
            "src.data.jpx_client.get_margin",
            lambda: {"available": False, "error": "network error", "buy_shares": None,
                     "sell_shares": None, "margin_ratio": None, "week_of": None,
                     "signal": None, "wow_change_pct": None},
        )
        monkeypatch.setattr(
            "src.data.jpx_client.get_investor_type",
            lambda: {"available": True, "error": None, "foreign_net_bn": 100.0,
                     "individual_net_bn": -50.0, "trust_net_bn": -20.0,
                     "week_of": "2026-04-17", "foreign_consecutive_buy_weeks": 1},
        )
        monkeypatch.setattr(
            "src.data.jpx_client.get_short_selling",
            lambda: {"available": True, "error": None, "short_volume": 5000000,
                     "dod_change_pct": None, "date": "2026-04-28"},
        )
        from src.data.jpx_client import get_demand_supply
        result = get_demand_supply()
        assert result["available"] is True
        assert result["error"] == "network error"


# ---------------------------------------------------------------------------
# TestFindCategoryNet (unit test for _find_category_net)
# ---------------------------------------------------------------------------

class TestFindCategoryNet:
    def test_finds_foreign_balance(self):
        from src.data.jpx_client.investor_type import _find_category_net
        df = _make_investor_df()
        val = _find_category_net(df, ["foreigners", "foreign"])
        assert val == pytest.approx(1635174762.0)

    def test_finds_individual_balance(self):
        from src.data.jpx_client.investor_type import _find_category_net
        df = _make_investor_df()
        val = _find_category_net(df, ["individuals", "individual"])
        assert val == pytest.approx(-785711849.0)

    def test_returns_none_when_not_found(self):
        from src.data.jpx_client.investor_type import _find_category_net
        df = pd.DataFrame([[None] * 10 for _ in range(5)])
        assert _find_category_net(df, ["foreigners"]) is None

    def test_insufficient_columns(self):
        from src.data.jpx_client.investor_type import _find_category_net
        df = pd.DataFrame([["Foreigners", "x"]])
        assert _find_category_net(df, ["foreigners"]) is None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _mock_response(html_text, binary_content):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.text = html_text or ""
    resp.content = binary_content or b""
    resp.apparent_encoding = "utf-8"
    return resp
