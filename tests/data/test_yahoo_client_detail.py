"""Tests for src/data/yahoo_client/detail.py helpers (KIK-727)."""

from datetime import date, datetime, timedelta, timezone

import pytest

from src.data.yahoo_client.detail import _earnings_date


def _ts(d: date, hour: int = 15, tz_name: str = "Asia/Tokyo") -> float:
    """指定タイムゾーンの d 日 hour 時を POSIX タイムスタンプにする。"""
    from zoneinfo import ZoneInfo

    return datetime(d.year, d.month, d.day, hour, tzinfo=ZoneInfo(tz_name)).timestamp()


class TestEarningsDate:
    def test_missing_returns_none(self):
        assert _earnings_date({}) is None

    def test_none_value_returns_none(self):
        assert _earnings_date({"earningsTimestamp": None}) is None

    def test_all_unparsable_returns_none(self):
        assert _earnings_date(
            {"earningsTimestamp": "x", "earningsTimestampStart": []}
        ) is None

    def test_parses_future_timestamp(self):
        target = date.today() + timedelta(days=3)
        info = {
            "earningsTimestamp": _ts(target),
            "exchangeTimezoneName": "Asia/Tokyo",
        }
        assert _earnings_date(info) == target.isoformat()

    def test_uses_exchange_timezone_not_utc(self):
        """JST 00:00 は UTC では前日になる。取引所TZで日付化すること。

        UTC で日付化すると1日前倒しされ、detect_alerts の
        ``0 <= days_until`` 判定により決算当日にアラートが消える。
        """
        target = date.today() + timedelta(days=2)
        info = {
            "earningsTimestamp": _ts(target, hour=0),  # JST 00:00
            "exchangeTimezoneName": "Asia/Tokyo",
        }
        assert _earnings_date(info) == target.isoformat()
        # 参考: 同じ値を UTC で日付化すると前日になる
        utc_date = datetime.fromtimestamp(
            info["earningsTimestamp"], tz=timezone.utc
        ).date()
        assert utc_date == target - timedelta(days=1)

    def test_picks_nearest_future_not_first_key(self):
        """earningsTimestamp が過去日でも、未来の候補を採る。

        yfinance の earningsTimestamp は直近の確定済み（過去の）決算日を
        指すことがある。先頭優先で確定すると過去日を掴み、アラートが出ない。
        """
        past = date.today() - timedelta(days=40)
        future = date.today() + timedelta(days=5)
        info = {
            "earningsTimestamp": _ts(past),
            "earningsTimestampStart": _ts(future),
            "exchangeTimezoneName": "Asia/Tokyo",
        }
        assert _earnings_date(info) == future.isoformat()

    def test_picks_earliest_of_multiple_future(self):
        near = date.today() + timedelta(days=2)
        far = date.today() + timedelta(days=9)
        info = {
            "earningsTimestamp": _ts(far),
            "earningsTimestampStart": _ts(near),
            "exchangeTimezoneName": "Asia/Tokyo",
        }
        assert _earnings_date(info) == near.isoformat()

    def test_all_past_returns_latest_past(self):
        older = date.today() - timedelta(days=100)
        newer = date.today() - timedelta(days=30)
        info = {
            "earningsTimestamp": _ts(older),
            "earningsTimestampStart": _ts(newer),
            "exchangeTimezoneName": "Asia/Tokyo",
        }
        assert _earnings_date(info) == newer.isoformat()

    def test_today_counts_as_future(self):
        """決算当日は「今日以降」に含める（当日こそ知りたい）。"""
        today = date.today()
        info = {
            "earningsTimestamp": _ts(today),
            "exchangeTimezoneName": "Asia/Tokyo",
        }
        assert _earnings_date(info) == today.isoformat()

    def test_unparsable_key_skipped(self):
        target = date.today() + timedelta(days=3)
        info = {
            "earningsTimestamp": "garbage",
            "earningsTimestampStart": _ts(target),
            "exchangeTimezoneName": "Asia/Tokyo",
        }
        assert _earnings_date(info) == target.isoformat()

    def test_falls_back_to_utc_on_bad_timezone(self):
        target = date.today() + timedelta(days=3)
        info = {
            "earningsTimestamp": _ts(target, hour=12, tz_name="UTC"),
            "exchangeTimezoneName": "Not/AZone",
        }
        assert _earnings_date(info) == target.isoformat()

    def test_us_exchange_timezone(self):
        """米国株は取引所TZ（America/New_York）で日付化する。"""
        target = date.today() + timedelta(days=4)
        info = {
            "earningsTimestamp": _ts(target, hour=16, tz_name="America/New_York"),
            "exchangeTimezoneName": "America/New_York",
        }
        assert _earnings_date(info) == target.isoformat()
