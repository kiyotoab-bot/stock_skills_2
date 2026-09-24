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


def _row(date, long_vol, shrt_vol, pub_date=None, long_val=None, shrt_val=None):
    r = {"Date": date, "Code": "80310", "LongVol": float(long_vol), "ShrtVol": float(shrt_vol)}
    if pub_date is not None:
        r["PubDate"] = pub_date
    if long_val is not None:
        r["LongVal"] = float(long_val)
    if shrt_val is not None:
        r["ShrtVal"] = float(shrt_val)
    return r


def _ratio(long_vol, shrt_vol):
    return long_vol / shrt_vol


class TestDailyMarginInterest:
    """KIK-776: 2026-09-28 の日次化後も前週比の意味を変えない。

    隣接2行の比較だと、日次化後は前日比が「前週比」として PO7 / SD1 /
    margin_surge に流れ、週次で較正した +50% 閾値が事実上効かなくなる。
    """

    # 週次のみ（日次化前の形）
    WEEKLY = [
        _row("2026-09-04", 5631900, 147300),
        _row("2026-09-11", 5085500, 175100),
    ]
    # 日次のみ（2026-09-25 申込分以降。9/26-27 は土日）
    DAILY = [
        _row("2026-09-25", 5000000, 200000, "2026-09-28", 1.5e10, 6e8),
        _row("2026-09-28", 5100000, 200000, "2026-09-29", 1.53e10, 6e8),
        _row("2026-09-29", 5200000, 200000, "2026-09-30"),
        _row("2026-09-30", 5300000, 200000, "2026-10-01"),
        _row("2026-10-01", 5400000, 200000, "2026-10-02"),
        _row("2026-10-02", 6000000, 200000, "2026-10-05"),
    ]
    # 混在（週次 9/4・9/11・9/18 → 日次 9/25・9/28・9/29）
    MIXED = [
        _row("2026-09-04", 5631900, 147300),
        _row("2026-09-11", 5085500, 175100),
        _row("2026-09-18", 5200000, 160000),
        _row("2026-09-25", 5000000, 200000, "2026-09-28"),
        _row("2026-09-28", 5100000, 200000, "2026-09-29"),
        _row("2026-09-29", 5600000, 200000, "2026-09-30"),
    ]

    def test_weekly_keeps_previous_week_as_basis(self):
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        r = summarize_margin_frame(pd.DataFrame(self.WEEKLY), code="80310")
        assert r["frequency"] == "weekly"
        assert r["wow_basis_date"] == "2026-09-04"
        expected = (_ratio(5085500, 175100) - _ratio(5631900, 147300)) / _ratio(5631900, 147300) * 100
        assert r["wow_change_pct"] == pytest.approx(expected, abs=0.1)
        assert r["dod_change_pct"] is None          # 週次に前日比は無い
        assert r["pub_date"] is None and r["long_val"] is None

    def test_daily_wow_uses_row_seven_days_back_not_adjacent(self):
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        r = summarize_margin_frame(pd.DataFrame(self.DAILY), code="80310")
        assert r["frequency"] == "daily"
        assert r["date"] == "2026-10-02" and r["pub_date"] == "2026-10-05"
        # 10/2 の 7 日前 = 9/25 が基準。隣接行（10/1）ではない
        assert r["wow_basis_date"] == "2026-09-25"
        assert r["wow_change_pct"] == pytest.approx(20.0, abs=0.1)   # 30倍 vs 25倍
        assert r["dod_change_pct"] == pytest.approx(11.1, abs=0.1)   # 30倍 vs 27倍

    def test_daily_returns_money_fields_and_history(self):
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        r = summarize_margin_frame(pd.DataFrame(self.DAILY), code="80310")
        assert len(r["history"]) == 5
        assert [h["date"] for h in r["history"]][0] == "2026-09-28"
        assert r["history"][0]["long_val"] == pytest.approx(1.53e10)
        assert r["history"][-1]["margin_ratio"] == pytest.approx(30.0)
        assert r["long_val"] is None                # 金額が欠損（null）の行は None を許す

    def test_mixed_weekly_and_daily_rows(self):
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        r = summarize_margin_frame(pd.DataFrame(self.MIXED), code="80310")
        assert r["frequency"] == "daily"
        # 9/29 の 7 日前 = 9/22 以前で最も近い行は週次の 9/18
        assert r["wow_basis_date"] == "2026-09-18"
        assert r["wow_change_pct"] == pytest.approx((28.0 - 32.5) / 32.5 * 100, abs=0.1)
        assert r["dod_change_pct"] == pytest.approx((28.0 - 25.5) / 25.5 * 100, abs=0.1)

    def test_daily_without_seven_days_of_history_has_no_wow(self):
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        r = summarize_margin_frame(pd.DataFrame(self.DAILY[:3]), code="80310")
        assert r["wow_change_pct"] is None and r["wow_basis_date"] is None
        assert r["dod_change_pct"] is not None

    def test_unsorted_and_duplicate_rows_are_normalized(self):
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        rows = list(reversed(self.DAILY)) + [self.DAILY[-1]]
        r = summarize_margin_frame(pd.DataFrame(rows), code="80310")
        assert r["date"] == "2026-10-02"
        assert len(r["history"]) == 5

    def test_nan_short_volume_gives_no_ratio_but_no_crash(self):
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        rows = self.WEEKLY + [_row("2026-09-18", 5200000, float("nan"))]
        r = summarize_margin_frame(pd.DataFrame(rows), code="80310")
        assert r["available"] is True
        assert r["margin_ratio"] is None
        assert r["wow_change_pct"] is None

    def test_first_daily_row_after_weekly_history(self):
        """日次化初日: 9/25 の日次行1本 + 週次 9/11・9/18。前週比は隣接の 9/18 と比べる。"""
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        rows = [_row("2026-09-11", 5085500, 175100), _row("2026-09-18", 5200000, 160000),
                _row("2026-09-25", 5000000, 200000, "2026-09-28")]
        r = summarize_margin_frame(pd.DataFrame(rows), code="80310")
        assert r["frequency"] == "weekly"          # 中央値 7 日 → まだ週次扱い
        assert r["wow_basis_date"] == "2026-09-18"
        assert r["dod_change_pct"] is None
        assert r["pub_date"] == "2026-09-28"

    def test_daily_wow_falls_back_to_nearest_older_row_when_seven_days_back_is_holiday(self):
        """7日前（9/23 祝日）の行が無い → それより前で最も近い 9/18（週次行）を拾う。"""
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        rows = [_row("2026-09-18", 5200000, 160000), _row("2026-09-25", 5000000, 200000),
                _row("2026-09-28", 5100000, 200000), _row("2026-09-29", 5200000, 200000),
                _row("2026-09-30", 5300000, 200000)]
        r = summarize_margin_frame(pd.DataFrame(rows), code="80310")
        assert r["frequency"] == "daily"
        assert r["wow_basis_date"] == "2026-09-18"

    def test_daily_after_long_weekend_keeps_daily_and_dod(self):
        """GW 明け（4/30 → 5/7 は 7 日空く）。frequency は中央値で daily のまま、dod は 6 日超なので None。"""
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        rows = [_row("2027-04-27", 5000000, 200000), _row("2027-04-28", 5050000, 200000),
                _row("2027-04-30", 5100000, 200000), _row("2027-05-07", 5500000, 200000)]
        r = summarize_margin_frame(pd.DataFrame(rows), code="80310")
        assert r["frequency"] == "daily"
        assert r["wow_basis_date"] == "2027-04-30"   # 5/7 の 7 日前 = 4/30 を含む
        assert r["dod_change_pct"] is None
        rows2 = rows[:3] + [_row("2027-05-06", 5500000, 200000)]
        r2 = summarize_margin_frame(pd.DataFrame(rows2), code="80310")
        assert r2["dod_change_pct"] == pytest.approx((27.5 - 25.5) / 25.5 * 100, abs=0.1)

    def test_weekly_with_shifted_application_date_uses_adjacent_week(self):
        """年末: 12/30 申込（金曜休場で前倒し）。前週比は 12/25 と比べる。12/18 に飛ばない（M1）。"""
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        rows = [_row("2026-12-11", 5000000, 200000), _row("2026-12-18", 5000000, 200000),
                _row("2026-12-25", 5000000, 200000), _row("2026-12-30", 6000000, 200000)]
        r = summarize_margin_frame(pd.DataFrame(rows), code="80310")
        assert r["frequency"] == "weekly"
        assert r["wow_basis_date"] == "2026-12-25"
        assert r["wow_change_pct"] == pytest.approx(20.0, abs=0.1)

    def test_missing_date_column_is_unavailable_not_exception(self):
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        r = summarize_margin_frame(pd.DataFrame([{"Code": "80310", "LongVol": 1.0, "ShrtVol": 1.0}]), code="80310")
        assert r["available"] is False and "Date" in r["error"]

    def test_unparseable_dates_are_dropped_and_reported(self):
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        rows = self.WEEKLY + [{"Date": "not-a-date", "Code": "80310", "LongVol": 1.0, "ShrtVol": 1.0}]
        r = summarize_margin_frame(pd.DataFrame(rows), code="80310")
        assert r["available"] is True and r["date"] == "2026-09-11"
        assert "1 rows dropped" in r["warning"]
        assert r["error"] is None                   # 診断は warning。error は失敗専用

    def test_transition_day_does_not_use_three_day_old_row_as_previous_week(self):
        """週次→日次の切替日（9/28）: 中央値は 7 日でまだ weekly だが、隣接行 9/25 は 3 日前。

        コードレビュー 2026-09-25 の指摘。ここで隣接行を取ると 3 日差が「前週比」として
        PO7 / SD1 / margin_surge の +50% 閾値に流れる（KIK-776 が防ぐはずだった欠陥そのもの）。
        """
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        rows = [_row("2026-09-04", 5631900, 147300), _row("2026-09-11", 5085500, 175100),
                _row("2026-09-18", 5200000, 160000), _row("2026-09-25", 5000000, 200000, "2026-09-28"),
                _row("2026-09-28", 7000000, 200000, "2026-09-29")]
        r = summarize_margin_frame(pd.DataFrame(rows), code="80310")
        assert r["frequency"] == "daily"           # 隣接行が 3 日前 → 最新行は日次行
        assert r["wow_basis_date"] == "2026-09-18"  # 9/28 の 7 日前 = 9/21 以前で最も近い行
        assert r["wow_change_pct"] == pytest.approx((35.0 - 32.5) / 32.5 * 100, abs=0.1)
        assert r["dod_change_pct"] == pytest.approx((35.0 - 25.0) / 25.0 * 100, abs=0.1)  # 9/25 比

    def test_wow_is_none_when_basis_row_is_too_old(self):
        """9/18 の週次行が欠けている: 9/28 の基準候補は 9/11（17 日前）→ 前週比とは呼べないので None。"""
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        rows = [_row("2026-09-11", 5085500, 175100), _row("2026-09-25", 5000000, 200000),
                _row("2026-09-28", 7000000, 200000)]
        r = summarize_margin_frame(pd.DataFrame(rows), code="80310")
        assert r["frequency"] == "daily"
        assert r["wow_change_pct"] is None and r["wow_basis_date"] is None
        assert r["dod_change_pct"] == pytest.approx(40.0, abs=0.1)

    def test_weekly_with_missing_week_has_no_wow(self):
        """週次で 1 週欠落（9/11 → 9/25 = 14 日）: 隣接行でも前週ではないので None。"""
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        rows = [_row("2026-09-04", 5631900, 147300), _row("2026-09-11", 5085500, 175100),
                _row("2026-09-25", 5000000, 200000)]
        r = summarize_margin_frame(pd.DataFrame(rows), code="80310")
        assert r["frequency"] == "weekly"
        assert r["wow_change_pct"] is None

    def test_mixed_date_formats_are_not_dropped(self):
        """"20260918"（旧行）と "2026-09-25"（新行）が混在しても最新行を落とさない。"""
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        rows = [_row("20260911", 5085500, 175100), _row("20260918", 5200000, 160000),
                _row("2026-09-25", 5000000, 200000, "2026-09-28")]
        r = summarize_margin_frame(pd.DataFrame(rows), code="80310")
        assert r["date"] == "2026-09-25" and r["warning"] is None
        assert r["wow_basis_date"] == "2026-09-18"

    def test_transition_day_two_rows_only_has_no_wow(self):
        """9/25・9/28 の 2 行しか無い: 隣接 3 日・7 日前の行も無い → 前週比は出さない（None）。"""
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        rows = [_row("2026-09-25", 5000000, 200000), _row("2026-09-28", 7000000, 200000)]
        r = summarize_margin_frame(pd.DataFrame(rows), code="80310")
        assert r["wow_change_pct"] is None and r["wow_basis_date"] is None

    @pytest.mark.parametrize("missing", ["LongVol", "ShrtVol"])
    def test_missing_volume_column_is_unavailable_not_silent_none(self, missing):
        """列名変更・部分応答で LongVol/ShrtVol が無い → available=False（黙って None を並べない）。"""
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        rows = [{k: v for k, v in _row("2026-09-11", 5085500, 175100).items() if k != missing}]
        r = summarize_margin_frame(pd.DataFrame(rows), code="80310")
        assert r["available"] is False and missing in r["error"]
        assert r["history"] == [] and r["margin_ratio"] is None

    def test_infinite_volume_is_treated_as_missing(self):
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        rows = self.WEEKLY + [_row("2026-09-18", float("inf"), 160000)]
        r = summarize_margin_frame(pd.DataFrame(rows), code="80310")
        assert r["available"] is True and r["margin_ratio"] is None and r["long_vol"] is None

    def test_success_result_has_every_schema_key(self):
        from src.data.jquants_client.margin_interest import summarize_margin_frame, _EMPTY
        r = summarize_margin_frame(pd.DataFrame(self.DAILY), code="80310")
        assert set(r) == set(_EMPTY)

    def test_compact_date_strings_are_normalized(self):
        from src.data.jquants_client.margin_interest import summarize_margin_frame
        rows = [_row("20260904", 5631900, 147300), _row("20260911", 5085500, 175100, "20260915")]
        r = summarize_margin_frame(pd.DataFrame(rows), code="80310")
        assert r["date"] == "2026-09-11" and r["pub_date"] == "2026-09-15"
        assert r["wow_basis_date"] == "2026-09-04"

    def test_sdk_missing_is_reported_as_not_installed(self, monkeypatch):
        """SDK 未導入なら error は「not installed」。トークン未設定と混同しない。"""
        import sys
        monkeypatch.setitem(sys.modules, "jquantsapi", None)
        from src.data.jquants_client.margin_interest import get_stock_margin
        r = get_stock_margin("7203.T")
        assert r["available"] is False and "not installed" in r["error"]
        assert r["history"] == [] and r["frequency"] is None

    def test_error_results_do_not_share_history_list(self, monkeypatch):
        _no_credentials(monkeypatch)
        from src.data.jquants_client.margin_interest import get_stock_margin
        a, b = get_stock_margin("5401.T"), get_stock_margin("7203.T")
        assert a["history"] == [] and a["history"] is not b["history"]

    def test_get_stock_margin_passes_35_day_window(self, monkeypatch):
        monkeypatch.setenv("JQUANTS_API_REFRESH_TOKEN", "dummy_token")
        mock_client = MagicMock()
        mock_client.get_mkt_margin_interest.return_value = pd.DataFrame(self.DAILY)
        with patch("src.data.jquants_client._client._make_client", return_value=mock_client):
            from src.data.jquants_client.margin_interest import get_stock_margin, FETCH_WINDOW_DAYS
            r = get_stock_margin("8031.T")
        kw = mock_client.get_mkt_margin_interest.call_args.kwargs
        from datetime import datetime
        span = datetime.strptime(kw["to_yyyymmdd"], "%Y%m%d") - datetime.strptime(kw["from_yyyymmdd"], "%Y%m%d")
        assert span.days == FETCH_WINDOW_DAYS
        assert r["frequency"] == "daily" and r["code"] == "80310"


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

