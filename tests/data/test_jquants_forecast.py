"""Tests for J-Quants company-forecast integration (KIK-730).

Background (2026-08-05): yfinance's forecast fields carry wrong values often
enough to matter — 2 of 5 verified names were wrong:
  6436.T アマノ   dividendRate 250 (company forecast 180) -> 6.44% yield, made it
                  into a Phase-1 recommendation before being caught
  6701.T 日本電気  forwardEps 718.96 (~3.3x the company forecast) -> forward PER 6.4
J-Quants returns the 決算短信 itself, so it becomes the primary source for
Japanese names and yfinance is demoted to fallback.
"""

import datetime
from unittest.mock import patch

import pytest

from src.data.jquants_client.fin_summary import _num, normalize_code
from src.data.yahoo_client.detail import _merge_jquants_forecast


class TestNormalizeCode:
    @pytest.mark.parametrize("raw,want", [
        ("7751.T", "7751"),
        ("7751", "7751"),
        ("77510", "7751"),      # J-Quants の5桁表記
        ("7751.t", "7751"),
        (" 7751.T ", "7751"),
    ])
    def test_variants(self, raw, want):
        assert normalize_code(raw) == want

    def test_five_digit_not_ending_in_zero_is_kept(self):
        """135A のような英字入り新形式を誤って削らない。"""
        assert normalize_code("13250") == "1325"
        assert normalize_code("1325A") == "1325A"


class TestNum:
    @pytest.mark.parametrize("raw,want", [
        (254.07, 254.07), ("254.07", 254.07), (0, 0.0), ("0", 0.0),
    ])
    def test_parses(self, raw, want):
        assert _num(raw) == want

    @pytest.mark.parametrize("raw", [None, "", "—", "n/a", float("nan")])
    def test_rejects(self, raw):
        assert _num(raw) is None


def _fc(**kw):
    base = {
        "available": True, "disclosed_date": "2026-07-28", "has_forecast": True,
        "forecast_eps": None, "forecast_dps_annual": None,
        "forecast_net_income": None, "forecast_operating_profit": None,
    }
    base.update(kw)
    return base


class TestMergeJQuantsForecast:
    def _run(self, symbol, result, fc):
        with patch("src.data.jquants_client.get_company_forecast", return_value=fc):
            _merge_jquants_forecast(symbol, result)
        return result

    def test_amano_divergence_is_flagged(self):
        """The exact 2026-08-05 failure: forecast 180 vs yfinance 250."""
        r = {"price": 3880.0, "dividend_rate": 250.0, "forward_eps": 251.65}
        self._run("6436.T", r, _fc(forecast_eps=254.07, forecast_dps_annual=180.0))
        assert r["forecast_source"] == "jquants"
        assert r["forecast_dps_company"] == 180.0
        assert r["forecast_suspect"] is True
        assert r["forecast_divergence"] == pytest.approx(250 / 180 - 1, abs=1e-6)

    def test_company_values_do_not_overwrite_yfinance_fields(self):
        """The guard must add fields, never silently mutate the originals."""
        r = {"price": 3880.0, "dividend_rate": 250.0, "forward_eps": 251.65}
        self._run("6436.T", r, _fc(forecast_eps=254.07, forecast_dps_annual=180.0))
        assert r["dividend_rate"] == 250.0
        assert r["forward_eps"] == 251.65

    def test_consistent_values_are_not_flagged(self):
        r = {"price": 4459.0, "dividend_rate": 160.0, "forward_eps": 362.49}
        self._run("7751.T", r, _fc(forecast_eps=398.84, forecast_dps_annual=160.0))
        assert r["forecast_suspect"] is False
        assert r["per_forward_company"] == pytest.approx(4459 / 398.84)
        assert r["dividend_yield_company"] == pytest.approx(160 / 4459)

    def test_missing_forecast_falls_back_to_yfinance(self):
        """IFRS filers (6701 / 4568 / 9364) return no forecast EPS."""
        r = {"price": 4631.0, "dividend_rate": 40.0, "forward_per": 6.44,
             "forward_eps": 718.96}
        self._run("6701.T", r, _fc(has_forecast=False))
        assert r["forecast_source"] == "yfinance"
        assert r.get("forecast_eps_company") is None
        assert r.get("per_forward_company") is None

    def test_dividend_only_forecast_still_compares(self):
        """6701 has FDivAnn but no FEPS — the dividend leg must still be checked."""
        r = {"price": 4631.0, "dividend_rate": 40.0, "forward_eps": 718.96}
        self._run("6701.T", r, _fc(forecast_dps_annual=40.0))
        assert r["forecast_source"] == "jquants"
        assert r["forecast_divergence"] == pytest.approx(0.0)
        assert r["forecast_suspect"] is False

    def test_non_japanese_symbol_is_skipped(self):
        r = {"price": 200.0, "dividend_rate": 1.0, "forward_eps": 10.0}
        with patch("src.data.jquants_client.get_company_forecast") as m:
            _merge_jquants_forecast("AAPL", r)
        m.assert_not_called()
        assert r["forecast_source"] is None

    def test_unavailable_api_leaves_result_untouched(self):
        r = {"price": 3880.0, "dividend_rate": 250.0}
        self._run("6436.T", r, {"available": False, "reason": "no key"})
        assert r["forecast_source"] is None
        assert "forecast_dps_company" not in r

    def test_api_exception_does_not_break_get_stock_info(self):
        r = {"price": 3880.0, "dividend_rate": 250.0}
        with patch("src.data.jquants_client.get_company_forecast",
                   side_effect=RuntimeError("429 rate limit")):
            _merge_jquants_forecast("6436.T", r)
        assert r["forecast_source"] is None

    def test_zero_price_does_not_divide(self):
        r = {"price": 0, "dividend_rate": 160.0, "forward_eps": 362.49}
        self._run("7751.T", r, _fc(forecast_eps=398.84, forecast_dps_annual=160.0))
        assert "per_forward_company" not in r
        assert "dividend_yield_company" not in r

    def test_divergence_uses_the_larger_of_eps_and_dps(self):
        r = {"price": 1000.0, "dividend_rate": 110.0, "forward_eps": 200.0}
        # dps gap +10%, eps gap +100% -> the eps gap must win
        self._run("9999.T", r, _fc(forecast_eps=100.0, forecast_dps_annual=100.0))
        assert r["forecast_divergence"] == pytest.approx(1.0)
        assert r["forecast_suspect"] is True

    def test_threshold_boundary(self):
        """20% exactly is not suspect; just over is."""
        r = {"price": 1000.0, "dividend_rate": 120.0, "forward_eps": None}
        self._run("9999.T", r, _fc(forecast_dps_annual=100.0))
        assert r["forecast_suspect"] is False
        r2 = {"price": 1000.0, "dividend_rate": 120.1, "forward_eps": None}
        self._run("9999.T", r2, _fc(forecast_dps_annual=100.0))
        assert r2["forecast_suspect"] is True


class TestFiscalYearRollover:
    """7453.T 良品計画（8月決算）の DQ2 誤検知。

    2026-08-07 時点で当期末 2026-08-31 まで24日。会社予想EPS 126.19 は FY2026/8、
    yfinance forwardEps 157.49 は FY2027/8 のコンセンサスで、+24.8% の乖離は
    「決算期が違う」だけだった（2025-08-28 に 1:2 分割済みなのも別要因）。
    どちらも正しい数字なので、これをデータ異常として FAIL にしてはいけない。
    """

    def _run(self, result, fc, today):
        with patch("src.data.jquants_client.get_company_forecast", return_value=fc):
            _merge_jquants_forecast("7453.T", result, today=today)
        return result

    def test_ryohin_keikaku_is_not_suspect(self):
        r = {"price": 4395.0, "forward_eps": 157.49}
        self._run(r, _fc(forecast_eps=126.19, fiscal_year_end="2026-08-31"),
                  datetime.date(2026, 8, 7))
        assert r["forecast_fy_rollover_likely"] is True
        assert r["forecast_suspect"] is False
        assert r["forecast_divergence"] == pytest.approx(157.49 / 126.19 - 1, abs=1e-6)
        assert r["per_forward_company"] == pytest.approx(4395.0 / 126.19)

    def test_same_gap_far_from_fy_end_is_suspect(self):
        """乖離が同じでも期末が遠ければ説明がつかない。"""
        r = {"price": 4395.0, "forward_eps": 157.49}
        self._run(r, _fc(forecast_eps=126.19, fiscal_year_end="2026-08-31"),
                  datetime.date(2026, 1, 15))
        assert r["forecast_fy_rollover_likely"] is False
        assert r["forecast_suspect"] is True

    def test_dividend_gap_still_flags_during_rollover(self):
        """配当の乖離は決算期ずれで説明できない。アマノ型を見逃さないこと。"""
        r = {"price": 3880.0, "dividend_rate": 250.0}
        self._run(r, _fc(forecast_dps_annual=180.0, fiscal_year_end="2026-08-31"),
                  datetime.date(2026, 8, 7))
        assert r["forecast_fy_rollover_likely"] is True
        assert r["forecast_suspect"] is True

    def test_fy_end_recorded(self):
        r = {"price": 4395.0, "forward_eps": 157.49}
        self._run(r, _fc(forecast_eps=126.19, fiscal_year_end="2026-08-31"),
                  datetime.date(2026, 8, 7))
        assert r["forecast_fiscal_year_end"] == "2026-08-31"

    @pytest.mark.parametrize("days,expect", [(0, True), (90, True), (91, False), (-30, True)])
    def test_boundary(self, days, expect):
        today = datetime.date(2026, 8, 7)
        fy = today + datetime.timedelta(days=days)
        r = {"price": 100.0, "forward_eps": 20.0}
        self._run(r, _fc(forecast_eps=10.0, fiscal_year_end=fy.isoformat()), today)
        assert r["forecast_fy_rollover_likely"] is expect

    @pytest.mark.parametrize("bad", [None, "NaT", "", "not-a-date"])
    def test_unparsable_fy_end_does_not_raise(self, bad):
        r = {"price": 100.0, "forward_eps": 20.0}
        self._run(r, _fc(forecast_eps=10.0, fiscal_year_end=bad),
                  datetime.date(2026, 8, 7))
        assert r["forecast_fy_rollover_likely"] is False
        assert r["forecast_suspect"] is True
        assert r["forecast_fiscal_year_end"] is None

    def test_pandas_timestamp_fy_end(self):
        """get_forecast_history は pandas の Timestamp を返す経路がある。"""
        import pandas as pd
        r = {"price": 4395.0, "forward_eps": 157.49}
        self._run(r, _fc(forecast_eps=126.19, fiscal_year_end=pd.Timestamp("2026-08-31")),
                  datetime.date(2026, 8, 7))
        assert r["forecast_fy_rollover_likely"] is True
        assert r["forecast_fiscal_year_end"] == "2026-08-31"

    def test_pandas_nat_is_safe(self):
        import pandas as pd
        r = {"price": 4395.0, "forward_eps": 157.49}
        self._run(r, _fc(forecast_eps=126.19, fiscal_year_end=pd.NaT),
                  datetime.date(2026, 8, 7))
        assert r["forecast_fy_rollover_likely"] is False


class TestDividendConfirmedByCompany:
    """7453.T 良品計画 の dividend_yield_suspect 誤検知。

    ``_dividend_suspect`` は yfinance 内部の 予想配当32円 vs 実績配当18.2円 だけを
    見るので、2025-08-28 の1:2分割と増配をまたぐと必ず立つ。だが J-Quants の
    会社予想も32円で完全一致しており、予想値は2ソースで裏が取れている。
    """

    def _run(self, result, fc):
        with patch("src.data.jquants_client.get_company_forecast", return_value=fc):
            _merge_jquants_forecast("7453.T", result, today=datetime.date(2026, 8, 7))
        return result

    def test_matching_company_forecast_clears_suspect(self):
        r = {"price": 4395.0, "dividend_rate": 32.0,
             "dividend_rate_trailing": 18.2, "dividend_yield_suspect": True}
        self._run(r, _fc(forecast_dps_annual=32.0, fiscal_year_end="2026-08-31"))
        assert r["dividend_yield_suspect"] is False
        assert r["dividend_rate_confirmed_by"] == "jquants"

    def test_disagreeing_company_forecast_keeps_suspect(self):
        """6436.T アマノ型（予想250 vs 会社180）は解除してはいけない。"""
        r = {"price": 3880.0, "dividend_rate": 250.0,
             "dividend_rate_trailing": 180.0, "dividend_yield_suspect": True}
        self._run(r, _fc(forecast_dps_annual=180.0, fiscal_year_end="2027-03-31"))
        assert r["dividend_yield_suspect"] is True
        assert "dividend_rate_confirmed_by" not in r
        assert r["forecast_suspect"] is True

    def test_no_company_dividend_leaves_flag_untouched(self):
        r = {"price": 100.0, "dividend_rate": 5.0,
             "dividend_rate_trailing": 2.0, "dividend_yield_suspect": True}
        self._run(r, _fc(forecast_eps=10.0, fiscal_year_end="2027-03-31"))
        assert r["dividend_yield_suspect"] is True


class TestStaleFiscalYear:
    """analyze_revisions が終わった決算期を掴む件（2026-08-07 発覚）。

    ``current_fy`` は「field が入っている最新の開示」で決まるため、今期の F* 開示が
    まだ無い銘柄では前期を指す。
      8725.T MS&AD  : +34.7% は FY2026/3（終了済）。今期 FY2027/3 は 4,250億で
                      前期 7,800億から -45.5%。上方修正銘柄として扱いかけた
      6701.T 日本電気: +10.3% は FY2025/3（2年前）
    """

    def _hist(self, rows):
        return [dict(r) for r in rows]

    def _run(self, rows, today):
        from src.data.jquants_client.fin_summary import analyze_revisions
        with patch("src.data.jquants_client.fin_summary.get_forecast_history",
                   return_value=self._hist(rows)):
            return analyze_revisions("8725.T", today=today)

    MSAD = [
        {"disclosed_date": "2026-06-29", "fiscal_year_end": "2026-03-31",
         "forecast_net_income": None, "next_fiscal_year_end": "2027-03-31",
         "next_fy_net_income": 425_000_000_000.0},
        {"disclosed_date": "2026-05-11", "fiscal_year_end": "2026-03-31",
         "forecast_net_income": 780_000_000_000.0, "next_fiscal_year_end": None,
         "next_fy_net_income": None},
        {"disclosed_date": "2026-02-13", "fiscal_year_end": "2026-03-31",
         "forecast_net_income": 590_000_000_000.0, "next_fiscal_year_end": None,
         "next_fy_net_income": None},
        {"disclosed_date": "2025-05-15", "fiscal_year_end": "2025-03-31",
         "forecast_net_income": 500_000_000_000.0,
         "next_fiscal_year_end": "2026-03-31",
         "next_fy_net_income": 579_000_000_000.0},
    ]

    def test_msad_stale_fy_is_flagged(self):
        got = self._run(self.MSAD, datetime.date(2026, 8, 7))
        assert got["current_fy"] == "2026-03-31"
        assert got["revision_in_fy"] == pytest.approx(34.715, abs=0.01)
        assert got["fy_end_passed"] is True

    def test_msad_next_fy_guidance_is_exposed(self):
        """終了済FYを掴んだときに、実際の今期予想が取れること。"""
        got = self._run(self.MSAD, datetime.date(2026, 8, 7))
        assert got["next_fy_end"] == "2027-03-31"
        assert got["next_fy_guidance"] == 425_000_000_000.0
        drop = got["next_fy_guidance"] / got["current_value"] - 1
        assert drop == pytest.approx(-0.455, abs=0.001)

    def test_live_fy_is_not_flagged(self):
        """商船三井型: 今期の1Q開示があるので current_fy は進行中。"""
        rows = [
            {"disclosed_date": "2026-08-03", "fiscal_year_end": "2027-03-31",
             "forecast_net_income": 240_000_000_000.0,
             "next_fiscal_year_end": None, "next_fy_net_income": None},
            {"disclosed_date": "2026-04-30", "fiscal_year_end": "2026-03-31",
             "forecast_net_income": None, "next_fiscal_year_end": "2027-03-31",
             "next_fy_net_income": 170_000_000_000.0},
        ]
        got = self._run(rows, datetime.date(2026, 8, 7))
        assert got["current_fy"] == "2027-03-31"
        assert got["fy_end_passed"] is False
        assert got["revision_in_fy"] == pytest.approx(41.18, abs=0.01)
        assert got["next_fy_guidance"] is None

    def test_fy_end_today_is_not_passed(self):
        rows = [{"disclosed_date": "2026-03-31", "fiscal_year_end": "2026-03-31",
                 "forecast_net_income": 100.0, "next_fiscal_year_end": None,
                 "next_fy_net_income": None}]
        got = self._run(rows, datetime.date(2026, 3, 31))
        assert got["fy_end_passed"] is False

    def test_unparsable_fy_end_gives_none(self):
        rows = [{"disclosed_date": "2026-03-31", "fiscal_year_end": "NaT",
                 "forecast_net_income": 100.0, "next_fiscal_year_end": None,
                 "next_fy_net_income": None}]
        got = self._run(rows, datetime.date(2026, 8, 7))
        assert got["fy_end_passed"] is None

    def test_po3_warns_on_stale_fy(self):
        """発注前チェックが終了済FYの改訂を PASS にしないこと。"""
        from src.data.checklist_review import WARN as W, check_order
        rev = self._run(self.MSAD, datetime.date(2026, 8, 7))
        po3 = [r for r in check_order("8725.T", {"price": 4827.0}, rev) if r["id"] == "PO3"][0]
        assert po3["status"] == W
        assert "終了済" in po3["detail"]
        assert "2026-03-31" in po3["detail"]
