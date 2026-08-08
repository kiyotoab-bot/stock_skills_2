"""Tests for src/data/jquants_client/ (margin_interest)."""

import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

pytestmark = pytest.mark.no_auto_mock

def _no_credentials(monkeypatch):
    """Simulate an environment with no J-Quants credentials.

    ``_client._ensure_env()`` reads ``.env`` itself so that ``src/data/`` entry
    points work (before 2026-08-05 only ``tools/jquants.py`` loaded it, so the
    client was silently disabled everywhere else). That means deleting the env
    vars is not enough — the loader has to be switched off too, otherwise the
    real credentials come back.
    """
    monkeypatch.delenv("JQUANTS_API_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
    monkeypatch.setenv("JQUANTS_SKIP_DOTENV", "1")
    import src.data.jquants_client._client as _c
    monkeypatch.setattr(_c, "_env_loaded", False)



def _make_margin_df(rows=None) -> pd.DataFrame:
    """Minimal DataFrame matching J-Quants margin interest response."""
    if rows is None:
        rows = [
            {"Date": "2026-04-17", "Code": "54010", "LongVol": 34472000.0, "ShrtVol": 1656600.0},
            {"Date": "2026-04-24", "Code": "54010", "LongVol": 35414600.0, "ShrtVol": 1936100.0},
        ]
    return pd.DataFrame(rows)


@pytest.fixture(autouse=True)
def _reset_client():
    """Reset cached client between tests."""
    from src.data.jquants_client import _client
    _client.reset_client()
    yield
    _client.reset_client()


class TestNormalizeCode:
    def test_with_t_suffix(self):
        from src.data.jquants_client.margin_interest import _normalize_code
        assert _normalize_code("5401.T") == "54010"

    def test_4digit(self):
        from src.data.jquants_client.margin_interest import _normalize_code
        assert _normalize_code("7203") == "72030"

    def test_5digit_unchanged(self):
        from src.data.jquants_client.margin_interest import _normalize_code
        assert _normalize_code("54010") == "54010"

    def test_uppercase(self):
        from src.data.jquants_client.margin_interest import _normalize_code
        assert _normalize_code("7203.t") == "72030"


class TestGetStockMargin:
    def test_successful_fetch(self, monkeypatch):
        monkeypatch.setenv("JQUANTS_API_REFRESH_TOKEN", "dummy_token")

        mock_client = MagicMock()
        mock_client.get_mkt_margin_interest.return_value = _make_margin_df()

        with patch("src.data.jquants_client._client._make_client", return_value=mock_client):
            from src.data.jquants_client.margin_interest import get_stock_margin
            result = get_stock_margin("5401.T")

        assert result["available"] is True
        assert result["code"] == "54010"
        assert result["long_vol"] == 35414600
        assert result["shrt_vol"] == 1936100
        assert result["margin_ratio"] == pytest.approx(18.29, rel=0.01)
        assert result["date"] == "2026-04-24"
        assert result["error"] is None

    def test_wow_change_calculated(self, monkeypatch):
        monkeypatch.setenv("JQUANTS_API_REFRESH_TOKEN", "dummy_token")

        mock_client = MagicMock()
        mock_client.get_mkt_margin_interest.return_value = _make_margin_df()

        with patch("src.data.jquants_client._client._make_client", return_value=mock_client):
            from src.data.jquants_client.margin_interest import get_stock_margin
            result = get_stock_margin("5401.T")

        # prev ratio = 34472000/1656600 ≈ 20.81, curr = 18.29 → wow ≈ -12.1%
        assert result["wow_change_pct"] is not None
        assert result["wow_change_pct"] < 0

    def test_no_api_key_returns_empty(self, monkeypatch):
        _no_credentials(monkeypatch)

        from src.data.jquants_client.margin_interest import get_stock_margin
        result = get_stock_margin("5401.T")
        assert result["available"] is False
        assert "JQUANTS_API_REFRESH_TOKEN" in result["error"]

    def test_empty_df_returns_error(self, monkeypatch):
        monkeypatch.setenv("JQUANTS_API_REFRESH_TOKEN", "dummy_token")

        mock_client = MagicMock()
        mock_client.get_mkt_margin_interest.return_value = pd.DataFrame()

        with patch("src.data.jquants_client._client._make_client", return_value=mock_client):
            from src.data.jquants_client.margin_interest import get_stock_margin
            result = get_stock_margin("9999.T")

        assert result["available"] is False
        assert result["margin_ratio"] is None

    def test_api_exception_returns_error(self, monkeypatch):
        monkeypatch.setenv("JQUANTS_API_REFRESH_TOKEN", "dummy_token")

        mock_client = MagicMock()
        mock_client.get_mkt_margin_interest.side_effect = ConnectionError("network error")

        with patch("src.data.jquants_client._client._make_client", return_value=mock_client):
            from src.data.jquants_client.margin_interest import get_stock_margin
            result = get_stock_margin("5401.T")

        assert result["available"] is False
        assert "network error" in result["error"]

    def test_single_row_no_wow(self, monkeypatch):
        monkeypatch.setenv("JQUANTS_API_REFRESH_TOKEN", "dummy_token")

        single_row = _make_margin_df([
            {"Date": "2026-04-24", "Code": "54010", "LongVol": 35414600.0, "ShrtVol": 1936100.0}
        ])
        mock_client = MagicMock()
        mock_client.get_mkt_margin_interest.return_value = single_row

        with patch("src.data.jquants_client._client._make_client", return_value=mock_client):
            from src.data.jquants_client.margin_interest import get_stock_margin
            result = get_stock_margin("5401.T")

        assert result["margin_ratio"] is not None
        assert result["wow_change_pct"] is None


class TestIsAvailable:
    def test_available_with_refresh_token(self, monkeypatch):
        monkeypatch.setenv("JQUANTS_API_REFRESH_TOKEN", "dummy")
        from src.data.jquants_client._client import is_available
        assert is_available() is True

    def test_available_with_api_key(self, monkeypatch):
        monkeypatch.delenv("JQUANTS_API_REFRESH_TOKEN", raising=False)
        monkeypatch.setenv("JQUANTS_API_KEY", "dummy")
        from src.data.jquants_client._client import is_available
        assert is_available() is True

    def test_unavailable_without_keys(self, monkeypatch):
        _no_credentials(monkeypatch)
        from src.data.jquants_client._client import is_available
        assert is_available() is False
