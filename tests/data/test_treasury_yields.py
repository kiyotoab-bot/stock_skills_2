"""米国債 10Y-2Y を一次ソースから取る（KIK-779）.

2YY=F（先物）が 2026-10-01 から財務省より約 20bp 低く出て、10Y-2Y を 0.45 → +0.63 と
誤り、10/8 の発注ゲート「10Y-2Y < 0.5%」を見落としかけた。
"""

import datetime

import pytest

from src.data import treasury_yields as T

TREASURY_CSV = (
    'Date,"1 Mo","1.5 Month","2 Mo","3 Mo","4 Mo","6 Mo","1 Yr","2 Yr","3 Yr","5 Yr","7 Yr","10 Yr","20 Yr","30 Yr"\n'
    "10/02/2026,4.04,4.09,4.11,4.19,4.26,4.27,4.46,4.83,4.96,5.06,5.17,5.28,5.67,5.63\n"
    "10/01/2026,4.06,4.10,4.13,4.17,4.26,4.27,4.44,4.78,4.91,5.01,5.12,5.24,5.64,5.61\n"
    "09/25/2026,4.05,4.10,4.12,4.18,4.25,4.30,4.50,4.81,4.95,5.03,5.10,5.17,5.60,5.58\n"
)
TODAY = datetime.date(2026, 10, 3)


def _fetcher(pages: dict):
    calls = []

    def fetch(url):
        calls.append(url)
        for key, body in pages.items():
            if key in url:
                if isinstance(body, Exception):
                    raise body
                return body
        raise RuntimeError(f"unexpected url {url}")
    fetch.calls = calls
    return fetch


class TestTreasury:
    def test_latest_spread_uses_2yr_not_1yr(self):
        """1 Yr（4.46）ではなく 2 Yr（4.83）を取る。10/2 の 10Y-2Y は 0.45."""
        r = T.get_treasury_curve(TODAY, _fetcher({"/2026/": TREASURY_CSV}))
        assert r["available"] and r["source"] == "treasury" and r["warning"] is None
        assert (r["date"], r["y2"], r["y10"]) == ("2026-10-02", 4.83, 5.28)
        assert r["spread"] == pytest.approx(0.45)

    def test_history_is_sorted_and_has_spreads(self):
        r = T.get_treasury_curve(TODAY, _fetcher({"/2026/": TREASURY_CSV}))
        assert [h["date"] for h in r["history"]] == ["2026-09-25", "2026-10-01", "2026-10-02"]
        assert r["history"][0]["spread"] == pytest.approx(0.36)

    def test_rows_missing_2yr_are_skipped(self):
        csv_text = ('Date,"2 Yr","10 Yr"\n10/02/2026,N/A,5.28\n10/01/2026,4.78,5.24\n')
        r = T.get_treasury_curve(TODAY, _fetcher({"/2026/": csv_text}))
        assert r["date"] == "2026-10-01" and r["spread"] == pytest.approx(0.46)

    def test_early_january_reads_previous_year(self):
        header = 'Date,"2 Yr","10 Yr"\n'
        f = _fetcher({"/2027/": header, "/2026/": header + "12/31/2026,4.50,5.00\n"})
        r = T.get_treasury_curve(datetime.date(2027, 1, 1), f)
        assert r["date"] == "2026-12-31" and r["source"] == "treasury"


class TestFredFallback:
    FRED2 = "observation_date,DGS2\n2026-09-30,4.88\n2026-10-01,4.78\n2026-10-02,.\n"
    FRED10 = "observation_date,DGS10\n2026-09-30,5.29\n2026-10-01,5.24\n"

    def test_falls_back_and_says_why(self):
        f = _fetcher({"treasury.gov": RuntimeError("403"),
                      "DGS2": self.FRED2, "DGS10": self.FRED10})
        r = T.get_treasury_curve(TODAY, f)
        assert r["available"] and r["source"] == "fred"
        assert r["date"] == "2026-10-01" and r["spread"] == pytest.approx(0.46)
        assert "403" in r["warning"]                 # 黙って切り替えない

    def test_both_fail_is_unavailable_not_futures(self):
        f = _fetcher({"treasury.gov": RuntimeError("timeout"), "fred": RuntimeError("503")})
        r = T.get_treasury_curve(TODAY, f)
        assert r["available"] is False and r["spread"] is None
        assert "timeout" in r["error"] and "503" in r["error"]
        assert not any("2YY" in u for u in f.calls)


def test_tool_facade_reexports():
    from tools import rates
    assert rates.HAS_RATES and rates.get_treasury_curve is T.get_treasury_curve


class TestStaleness:
    """当年 CSV の取得に失敗し、前年の値だけが取れたときに最新と読まない（レビュー指摘）."""

    OLD = 'Date,"2 Yr","10 Yr"\n12/31/2025,4.20,4.60\n'

    def test_current_year_failure_with_old_previous_year_falls_back_to_fred(self):
        f = _fetcher({"/2026/": RuntimeError("timeout"), "/2025/": self.OLD,
                      "DGS2": "d,DGS2\n2026-10-01,4.78\n", "DGS10": "d,DGS10\n2026-10-01,5.24\n"})
        r = T.get_treasury_curve(TODAY, f)
        assert r["source"] == "fred" and r["date"] == "2026-10-01"
        assert "timeout" in r["warning"] and "2025-12-31" in r["warning"]

    def test_everything_stale_is_unavailable(self):
        f = _fetcher({"/2026/": "<html>maintenance</html>", "/2025/": self.OLD,
                      "DGS2": "d,DGS2\n2025-12-31,4.20\n", "DGS10": "d,DGS10\n2025-12-31,4.60\n"})
        r = T.get_treasury_curve(TODAY, f)
        assert r["available"] is False and r["spread"] is None
        assert "古い" in r["error"]

    def test_early_january_previous_year_within_limit_is_fresh(self):
        header = 'Date,"2 Yr","10 Yr"\n'
        f = _fetcher({"/2027/": header, "/2026/": header + "12/31/2026,4.50,5.00\n"})
        r = T.get_treasury_curve(datetime.date(2027, 1, 4), f)
        assert r["available"] and r["date"] == "2026-12-31"
